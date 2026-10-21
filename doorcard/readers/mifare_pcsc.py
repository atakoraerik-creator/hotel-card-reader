from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .. import diagnostics as diag
from ..models import (
    CardTechnology,
    DataAccess,
    Diagnostic,
    DiagnosticCode,
    MemoryBlock,
    Severity,
)

# Documented ACS PC/SC pseudo-APDUs for MIFARE Classic.
# These are read-only commands: load key, authenticate, read binary.
# No write/update/decrement command is present anywhere in this module.
_LOAD_KEY = (0xFF, 0x82, 0x00, 0x00, 0x06)
_AUTHENTICATE = (0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00)
_READ_BINARY = (0xFF, 0xB0, 0x00)

_UNSUPPORTED_STATUS = {(0x6A, 0x81), (0x6D, 0x00), (0x6E, 0x00), (0x68, 0x81)}


class MifareMemoryReadError(RuntimeError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class MifareClassicMemoryReader:
    """Read-only MIFARE Classic memory reader using documented ACS pseudo-APDUs.

    This adapter is experimental and was not verified against hardware in the
    environment where it was written. It is intentionally limited to read and
    authenticate operations. Sector trailers are never read or displayed.
    """

    def __init__(self, connection: Any, reader_name: str) -> None:
        self._connection = connection
        self._reader_name = reader_name

    def read(
        self,
        keys: Iterable[bytes],
        technology: CardTechnology,
    ) -> tuple[list[MemoryBlock], list[Diagnostic]]:
        if technology is CardTechnology.MIFARE_CLASSIC_4K:
            sector_count = 40
        elif technology is CardTechnology.MIFARE_CLASSIC_1K:
            sector_count = 16
        else:
            return [], [
                diag.memory_read_unsupported(
                    self._reader_name,
                    detail="This adapter only supports MIFARE Classic 1K/4K.",
                )
            ]

        key_list = [bytes(key) for key in keys if len(key) == 6]
        memory: list[MemoryBlock] = []
        diagnostics: list[Diagnostic] = []
        auth_failures: list[int] = []
        unreadable: list[int] = []
        readable = 0
        protected = 0
        auth_required_blocks = 0
        unsupported = False

        for sector in range(sector_count):
            first, count = _layout(sector)
            trailer = first + count - 1
            auth_ok = False
            unsupported_sector = False

            if key_list:
                for key in key_list:
                    _load_data, load_sw1, load_sw2 = self._transmit(list(_LOAD_KEY) + list(key))
                    if (load_sw1, load_sw2) in _UNSUPPORTED_STATUS or load_sw1 != 0x90:
                        unsupported = True
                        unsupported_sector = True
                        diagnostics.append(
                            diag.from_status_word(
                                load_sw1, load_sw2, context=f"load key for sector {sector}"
                            )
                        )
                        break
                    _auth_data, auth_sw1, auth_sw2 = self._transmit(
                        list(_AUTHENTICATE) + [first, 0x60, 0x00]
                    )
                    if (auth_sw1, auth_sw2) in _UNSUPPORTED_STATUS:
                        unsupported = True
                        unsupported_sector = True
                        diagnostics.append(
                            diag.from_status_word(
                                auth_sw1, auth_sw2, context=f"authenticate sector {sector}"
                            )
                        )
                        break
                    if (auth_sw1, auth_sw2) == (0x90, 0x00):
                        auth_ok = True
                        break

            if unsupported_sector:
                for index in range(count):
                    block = first + index
                    if index == count - 1:
                        memory.append(_trailer(sector, block))
                    else:
                        memory.append(
                            MemoryBlock(
                                sector=sector,
                                block=block,
                                address=block,
                                data=None,
                                access=DataAccess.NOT_SUPPORTED,
                                note="Reader did not accept the documented MIFARE read commands.",
                            )
                        )
                continue

            if not auth_ok:
                auth_failures.append(sector)
                auth_required_blocks += count - 1
                for index in range(count):
                    block = first + index
                    if index == count - 1:
                        memory.append(_trailer(sector, block))
                        protected += 1
                    else:
                        note = (
                            "Authentication failed with the supplied session key."
                            if key_list
                            else "No session key was supplied."
                        )
                        memory.append(
                            MemoryBlock(
                                sector=sector,
                                block=block,
                                address=block,
                                data=None,
                                access=DataAccess.AUTH_REQUIRED,
                                note=note,
                            )
                        )
                continue

            for index in range(count - 1):
                block = first + index
                data, sw1, sw2 = self._transmit(list(_READ_BINARY) + [block, 0x10])
                if (sw1, sw2) == (0x90, 0x00) and len(data) >= 16:
                    memory.append(
                        MemoryBlock(
                            sector=sector,
                            block=block,
                            address=block,
                            data=bytes(data[:16]),
                            access=DataAccess.READABLE,
                        )
                    )
                    readable += 1
                else:
                    unreadable.append(block)
                    if (sw1, sw2) in _UNSUPPORTED_STATUS:
                        unsupported = True
                    memory.append(
                        MemoryBlock(
                            sector=sector,
                            block=block,
                            address=block,
                            data=None,
                            access=DataAccess.UNREADABLE,
                            note=f"Read failed with status {sw1:02X}{sw2:02X}.",
                        )
                    )
            memory.append(_trailer(sector, trailer))
            protected += 1

        if unsupported:
            diagnostics.append(
                diag.memory_read_unsupported(
                    self._reader_name,
                    detail="The reader rejected the documented ACS MIFARE pseudo-APDUs.",
                )
            )
        if auth_failures:
            diagnostics.append(
                diag.diagnostic(
                    DiagnosticCode.AUTH_REQUIRED,
                    detail=(
                        f"{len(auth_failures)} sector(s) require a different key: "
                        + ", ".join(str(item) for item in auth_failures)
                    ),
                )
            )
        if unreadable:
            diagnostics.append(
                diag.diagnostic(
                    DiagnosticCode.DATA_UNREADABLE,
                    detail=(
                        "Unreadable block(s): "
                        + ", ".join(str(item) for item in unreadable[:32])
                        + ("..." if len(unreadable) > 32 else "")
                    ),
                )
            )
        if readable and (auth_failures or unreadable or protected):
            diagnostics.append(
                diag.partial_memory(
                    readable, auth_required_blocks + protected + len(unreadable)
                )
            )
        elif readable and not diagnostics:
            diagnostics.append(
                diag.diagnostic(
                    DiagnosticCode.MEMORY_READ_PARTIAL,
                    severity=Severity.INFO,
                    message="Requested public data blocks were read successfully.",
                    detail=f"{readable} block(s) readable",
                )
            )
        return memory, diagnostics

    def _transmit(self, apdu: list[int]) -> tuple[list[int], int, int]:
        try:
            data, sw1, sw2 = self._connection.transmit(apdu)
        except Exception as exc:  # pragma: no cover - hardware exception mapping
            raise MifareMemoryReadError(diag.from_exception(exc, context="MIFARE memory read")) from exc
        return list(data or []), int(sw1), int(sw2)


def _layout(sector: int) -> tuple[int, int]:
    if sector < 32:
        return sector * 4, 4
    return 128 + (sector - 32) * 16, 16


def _trailer(sector: int, block: int) -> MemoryBlock:
    return MemoryBlock(
        sector=sector,
        block=block,
        address=block,
        data=None,
        access=DataAccess.PROTECTED,
        note="Sector trailer (key A/B and access bits) is never read.",
    )
