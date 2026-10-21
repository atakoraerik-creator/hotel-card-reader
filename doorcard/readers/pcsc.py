from __future__ import annotations

import threading
import time
from typing import Any

from .. import diagnostics as diag
from ..identification import aggregate_access, identify_card
from ..models import (
    CardInfo,
    CardTechnology,
    DataAccess,
    Diagnostic,
    DiagnosticCode,
    ReaderInfo,
    ReaderKind,
    ScanResult,
    Severity,
    utc_timestamp,
)
from .base import BackendAvailability, ReaderBackend, ReaderBackendError
from .mifare_pcsc import MifareClassicMemoryReader, MifareMemoryReadError


def _import_readers():
    try:
        from smartcard.System import readers as system_readers
    except Exception as exc:  # pragma: no cover - depends on installed runtime
        raise ReaderBackendError(diag.from_exception(exc, context="loading pyscard")) from exc
    return system_readers


class PcscBackend(ReaderBackend):
    kind = ReaderKind.PCSC
    display_name = "PC/SC reader"

    def __init__(self) -> None:
        self._reader_name: str | None = None

    def availability(self) -> BackendAvailability:
        try:
            _import_readers()
        except ReaderBackendError as exc:
            return BackendAvailability(False, exc.diagnostic.message, (exc.diagnostic,))
        return BackendAvailability(
            True,
            "pyscard is installed. Connect a PC/SC reader and refresh.",
        )

    def list_readers(self) -> list[ReaderInfo]:
        system_readers = _import_readers()
        try:
            readers = list(system_readers())
        except Exception as exc:
            raise ReaderBackendError(diag.from_exception(exc, context="enumerating readers")) from exc
        return [self._reader_info(getattr(reader, "name", str(reader))) for reader in readers]

    def connect(self, reader_name: str) -> ReaderInfo:
        readers = self.list_readers()
        for reader in readers:
            if reader.name == reader_name:
                self._reader_name = reader_name
                return reader
        raise ReaderBackendError(
            diag.diagnostic(
                DiagnosticCode.READER_NOT_FOUND,
                detail=f"Reader name: {reader_name}",
            )
        )

    def disconnect(self) -> None:
        self._reader_name = None

    def scan(
        self,
        *,
        reader_name: str | None = None,
        timeout_s: float = 10.0,
        key: bytes | None = None,
        read_memory: bool = False,
        cancel: threading.Event | None = None,
    ) -> ScanResult:
        started = time.perf_counter()
        cancel = cancel or threading.Event()
        events: list[str] = []
        target = reader_name or self._reader_name

        system_readers = _import_readers()
        try:
            available = list(system_readers())
        except Exception as exc:
            return self._result(
                target,
                None,
                [diag.from_exception(exc, context="enumerating readers")],
                started,
                events,
            )

        if not available:
            return self._result(target, None, [diag.no_reader("PC/SC reader")], started, events)
        if target is None:
            target = getattr(available[0], "name", str(available[0]))
        selected = next((item for item in available if getattr(item, "name", None) == target), None)
        if selected is None:
            return self._result(
                target,
                None,
                [
                    diag.diagnostic(
                        DiagnosticCode.READER_NOT_FOUND,
                        detail=f"Reader name: {target}",
                    )
                ],
                started,
                events,
            )

        reader_info = self._reader_info(target)
        events.append(f"{utc_timestamp()} using reader {target}")

        while not cancel.is_set():
            elapsed = time.perf_counter() - started
            if elapsed >= timeout_s:
                break
            connection = None
            try:
                connection = selected.createConnection()
                connection.connect()
                events.append(f"{utc_timestamp()} card connection established")
                card, card_diagnostics = self._read_card(
                    connection, target, key=key, read_memory=read_memory, events=events
                )
                return self._result(reader_info, card, card_diagnostics, started, events)
            except Exception as exc:
                diagnostic = diag.from_exception(exc, context="PC/SC scan")
                if diagnostic.code is DiagnosticCode.NO_CARD:
                    events.append(f"{utc_timestamp()} no card; waiting")
                    if cancel.wait(0.25):
                        break
                    continue
                events.append(f"{utc_timestamp()} {diagnostic.code.value}: {diagnostic.message}")
                return self._result(reader_info, None, [diagnostic], started, events)
            finally:
                if connection is not None:
                    try:
                        connection.disconnect()
                    except Exception:
                        pass

        if cancel.is_set():
            return self._result(
                reader_info, None, [diag.diagnostic(DiagnosticCode.STOPPED)], started, events
            )
        return self._result(
            reader_info, None, [diag.diagnostic(DiagnosticCode.NO_CARD)], started, events
        )

    def _read_card(
        self,
        connection: Any,
        reader_name: str,
        *,
        key: bytes | None,
        read_memory: bool,
        events: list[str],
    ) -> tuple[CardInfo, list[Diagnostic]]:
        diagnostics: list[Diagnostic] = []
        atr = b""
        try:
            atr = bytes(connection.getATR())
        except Exception as exc:
            diagnostics.append(diag.from_exception(exc, context="reading ATR"))

        protocol = self._protocol_name(connection)
        uid, uid_diagnostics = self._get_uid(connection)
        diagnostics.extend(uid_diagnostics)

        card = identify_card(atr, uid, protocol=protocol, reader_name=reader_name)
        events.append(
            f"{utc_timestamp()} identified {card.technology.value}; "
            f"UID {card.uid_display if card.uid else 'unavailable'}"
        )

        if card.technology is CardTechnology.UNKNOWN:
            diagnostics.append(
                diag.diagnostic(
                    DiagnosticCode.CARD_NOT_IDENTIFIED,
                    detail=f"ATR: {card.atr_hex or 'unavailable'}",
                )
            )

        if read_memory:
            if card.technology.is_mifare_classic:
                keys = [key] if key else []
                try:
                    reader = MifareClassicMemoryReader(connection, reader_name)
                    memory, memory_diagnostics = reader.read(keys, card.technology)
                    card.memory = memory
                    card.access_state = aggregate_access(memory)
                    diagnostics.extend(memory_diagnostics)
                    events.append(
                        f"{utc_timestamp()} read {len(memory)} memory block records "
                        "(sector trailers excluded)"
                    )
                except MifareMemoryReadError as exc:
                    diagnostics.append(exc.diagnostic)
                    card.access_state = DataAccess.UNAVAILABLE
                except Exception as exc:
                    diagnostics.append(diag.from_exception(exc, context="MIFARE memory read"))
                    card.access_state = DataAccess.UNAVAILABLE
            else:
                card.access_state = DataAccess.NOT_SUPPORTED
                diagnostics.append(
                    diag.diagnostic(
                        DiagnosticCode.MEMORY_READ_UNSUPPORTED,
                        severity=Severity.WARNING,
                        message=(
                            "Read-only memory access is implemented only for MIFARE Classic "
                            "in this version."
                        ),
                        detail=f"Card technology: {card.technology.value}",
                    )
                )
        elif card.technology.is_mifare_classic:
            card.access_state = DataAccess.NOT_ATTEMPTED
            diagnostics.append(
                diag.diagnostic(
                    DiagnosticCode.MEMORY_READ_DISABLED,
                    severity=Severity.INFO,
                    message="MIFARE memory reading was not requested; only identification data was read.",
                )
            )

        return card, diagnostics

    def _get_uid(self, connection: Any) -> tuple[bytes | None, list[Diagnostic]]:
        try:
            data, sw1, sw2 = connection.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        except Exception as exc:
            return None, [diag.from_exception(exc, context="UID read")]
        if (sw1, sw2) == (0x90, 0x00) and len(data or []) >= 4:
            return bytes(data), []
        return None, [diag.from_status_word(sw1, sw2, context="UID read")]

    def _protocol_name(self, connection: Any) -> str | None:
        try:
            protocol = connection.getProtocol()
        except Exception:
            return None
        if protocol == 1:
            return "T=0"
        if protocol == 2:
            return "T=1"
        return f"0x{protocol:02X}" if isinstance(protocol, int) else str(protocol)

    def _reader_info(self, name: str) -> ReaderInfo:
        upper = name.upper()
        vendor = None
        if "ACS" in upper or "ACR" in upper:
            vendor = "ACS"
        elif "OMNIKEY" in upper or "HID" in upper:
            vendor = "HID Global"
        elif "SCM" in upper:
            vendor = "SCM Microsystems"
        elif "SONY" in upper:
            vendor = "Sony"
        elif "IDENTIV" in upper:
            vendor = "Identiv"
        elif "BRASSCO" in upper:
            vendor = "Brassco"
        notes: list[str] = []
        if "BRASSCO" in upper:
            notes.append(
                "Vendor device: PC/SC capabilities and card support are unverified. "
                "Do not assume MIFARE read support."
            )
        return ReaderInfo(
            name=name,
            kind=ReaderKind.PCSC,
            vendor=vendor,
            model=name,
            interface="PC/SC",
            supports_pcsc=True,
            notes=tuple(notes),
        )

    def _result(
        self,
        reader_name: str | None,
        card: CardInfo | None,
        diagnostics: list[Diagnostic],
        started: float,
        events: list[str],
    ) -> ScanResult:
        reader = self._reader_info(reader_name) if reader_name else None
        return ScanResult(
            reader=reader,
            card=card,
            diagnostics=diagnostics,
            backend="pcsc",
            duration_ms=int((time.perf_counter() - started) * 1000),
            simulated=False,
            events=events,
        )
