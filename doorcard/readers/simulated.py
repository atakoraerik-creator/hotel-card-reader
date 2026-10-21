from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass

from .. import diagnostics as diag
from ..identification import aggregate_access, identify_card
from ..models import (
    CardInfo,
    CardTechnology,
    DataAccess,
    Diagnostic,
    DiagnosticCode,
    MemoryBlock,
    ReaderInfo,
    ReaderKind,
    ScanResult,
    Severity,
    utc_timestamp,
)
from .base import BackendAvailability, ReaderBackend, ReaderBackendError

_SIM_READER_NAME = "Simulated Reader (demo)"


@dataclass(frozen=True)
class SimulatedCard:
    key: str
    label: str
    description: str
    card: CardInfo | None
    diagnostics: tuple[Diagnostic, ...] = ()


def _classic_memory(*, four_k: bool, readable_sectors: set[int]) -> list[MemoryBlock]:
    sectors = 40 if four_k else 16
    blocks: list[MemoryBlock] = []
    for sector in range(sectors):
        if sector < 32:
            first = sector * 4
            count = 4
        else:
            first = 128 + (sector - 32) * 16
            count = 16
        for index in range(count):
            block = first + index
            address = block
            if index == count - 1:
                blocks.append(
                    MemoryBlock(
                        sector=sector,
                        block=block,
                        address=address,
                        data=None,
                        access=DataAccess.PROTECTED,
                        note="Sector trailer (keys and access bits) is never read.",
                    )
                )
                continue
            if sector in readable_sectors:
                text = f"SIM S{sector:02d} B{index} PUBLIC DATA"
                data = text.encode("ascii")[:16].ljust(16, b"\x00")
                blocks.append(
                    MemoryBlock(
                        sector=sector,
                        block=block,
                        address=address,
                        data=data,
                        access=DataAccess.READABLE,
                    )
                )
            else:
                blocks.append(
                    MemoryBlock(
                        sector=sector,
                        block=block,
                        address=address,
                        data=None,
                        access=DataAccess.AUTH_REQUIRED,
                        note="Authentication required; no key was supplied.",
                    )
                )
    return blocks


def _classic_card(
    uid_hex: str,
    technology: CardTechnology,
    *,
    four_k: bool,
    readable_sectors: set[int],
) -> tuple[CardInfo, tuple[Diagnostic, ...]]:
    uid = bytes.fromhex(uid_hex)
    atr_hex = (
        "3B8F8001804F0CA000000306030002000000006B"
        if four_k
        else "3B8F8001804F0CA000000306030001000000006A"
    )
    card = identify_card(bytes.fromhex(atr_hex), uid, protocol="T=1", reader_name=_SIM_READER_NAME)
    card.memory = _classic_memory(four_k=four_k, readable_sectors=readable_sectors)
    card.access_state = aggregate_access(card.memory)
    card.details["Simulation"] = "Deterministic sample; no hardware was accessed."
    readable = sum(1 for block in card.memory if block.access is DataAccess.READABLE)
    protected = len(card.memory) - readable
    diagnostics: list[Diagnostic] = []
    if readable:
        diagnostics.append(diag.partial_memory(readable, protected))
    else:
        diagnostics.append(diag.diagnostic(DiagnosticCode.AUTH_REQUIRED))
    return card, tuple(diagnostics)


def _ultralight_card() -> tuple[CardInfo, tuple[Diagnostic, ...]]:
    uid = bytes.fromhex("04C1D2E3F40506")
    atr = bytes.fromhex("3B8F8001804F0CA0000003060300030000000068")
    card = identify_card(atr, uid, protocol="T=1", reader_name=_SIM_READER_NAME)
    page_data = [
        b"\x04\xC1\xD2\xE3",
        b"\xF4\x05\x06\x08",
        b"SIM ULTRALIGHT\x00",
        b"PUBLIC PAGE DATA",
        b"NDEF-LIKE DEMO\x00\x00",
        b"END OF DEMO\x00\x00\x00\x00",
    ]
    memory: list[MemoryBlock] = []
    for page in range(16):
        data = page_data[page] if page < len(page_data) else b"\x00\x00\x00\x00"
        memory.append(
            MemoryBlock(
                sector=None,
                block=page,
                address=page * 4,
                data=data,
                access=DataAccess.READABLE,
                note="Simulated Ultralight page dump.",
            )
        )
    card.memory = memory
    card.access_state = DataAccess.READABLE
    card.details["Simulation"] = "Deterministic sample; no hardware was accessed."
    return card, (
        diag.diagnostic(
            DiagnosticCode.MEMORY_READ_PARTIAL,
            severity=Severity.INFO,
            message="Simulated Ultralight page dump. Real Ultralight memory access is reader/SDK-specific.",
            detail="16 public pages simulated",
        ),
    )


def _desfire_card() -> tuple[CardInfo, tuple[Diagnostic, ...]]:
    uid = bytes.fromhex("04D1E2F3A4B5C6")
    atr = bytes.fromhex("3B86800106757781028000")
    card = identify_card(atr, uid, protocol="T=1", reader_name=_SIM_READER_NAME)
    card.access_state = DataAccess.AUTH_REQUIRED
    card.details["Simulation"] = "Deterministic sample; DESFire applications require authentication."
    return card, (diag.diagnostic(DiagnosticCode.AUTH_REQUIRED),)


def _iso15693_card() -> tuple[CardInfo, tuple[Diagnostic, ...]]:
    card = CardInfo(
        technology=CardTechnology.ISO15693,
        uid="E0A1B2C3D4E5F607",
        uid_bytes=bytes.fromhex("E0A1B2C3D4E5F607"),
        protocol="ISO/IEC 15693",
        manufacturer=None,
        memory_size="Varies by tag",
        frequency="13.56 MHz (ISO/IEC 15693)",
        confidence="medium",
        readable=True,
        access_state=DataAccess.NOT_SUPPORTED,
        details={
            "Simulation": "Deterministic sample; no hardware was accessed.",
            "Identification": "Simulated ISO/IEC 15693 tag",
        },
    )
    return card, (
        diag.diagnostic(
            DiagnosticCode.MEMORY_READ_UNSUPPORTED,
            severity=Severity.WARNING,
            message="ISO/IEC 15693 tag identified, but memory reading is not implemented.",
        ),
    )


def _unsupported_card() -> tuple[CardInfo, tuple[Diagnostic, ...]]:
    card = CardInfo(
        technology=CardTechnology.UNSUPPORTED,
        uid=None,
        uid_bytes=None,
        atr=None,
        protocol=None,
        manufacturer=None,
        memory_size=None,
        frequency="125 kHz (presumed)",
        confidence="low",
        readable=False,
        access_state=DataAccess.NOT_SUPPORTED,
        details={
            "Simulation": "Deterministic sample of a 125 kHz card.",
            "Expected hardware": "A 125 kHz reader/writer, not a 13.56 MHz PC/SC NFC reader.",
        },
        warnings=["A 13.56 MHz NFC reader cannot read this card."],
    )
    return card, (
        diag.diagnostic(DiagnosticCode.FREQUENCY_MISMATCH_SUSPECTED),
        diag.diagnostic(DiagnosticCode.CARD_UNSUPPORTED),
    )


def _card_error() -> tuple[CardInfo | None, tuple[Diagnostic, ...]]:
    detail = (
        "Simulated vendor firmware response: 'Card Error'. "
        "This sample demonstrates how a hardware/firmware compatibility failure is reported."
    )
    return None, (diag.card_error(detail),)


def _build_cards() -> dict[str, SimulatedCard]:
    classic_1k, classic_1k_diags = _classic_card(
        "04A1B2C3D4E5F6",
        CardTechnology.MIFARE_CLASSIC_1K,
        four_k=False,
        readable_sectors={1, 2},
    )
    classic_4k, classic_4k_diags = _classic_card(
        "04B1C2D3E4F50607",
        CardTechnology.MIFARE_CLASSIC_4K,
        four_k=True,
        readable_sectors={1, 2, 32},
    )
    protected_1k, protected_diags = _classic_card(
        "04D4E5F6A1B2C3",
        CardTechnology.MIFARE_CLASSIC_1K,
        four_k=False,
        readable_sectors=set(),
    )
    ultralight, ultralight_diags = _ultralight_card()
    desfire, desfire_diags = _desfire_card()
    iso15693, iso15693_diags = _iso15693_card()
    unsupported, unsupported_diags = _unsupported_card()
    error_card, error_diags = _card_error()

    return {
        "mifare_classic_1k": SimulatedCard(
            key="mifare_classic_1k",
            label="MIFARE Classic 1K - mixed access",
            description="UID/ATR identified; sectors 1-2 public, other sectors require authentication.",
            card=classic_1k,
            diagnostics=classic_1k_diags,
        ),
        "mifare_classic_4k": SimulatedCard(
            key="mifare_classic_4k",
            label="MIFARE Classic 4K - mixed access",
            description="UID/ATR identified; 4K sector layout with partial public data.",
            card=classic_4k,
            diagnostics=classic_4k_diags,
        ),
        "mifare_classic_protected": SimulatedCard(
            key="mifare_classic_protected",
            label="MIFARE Classic 1K - protected",
            description="UID/ATR identified; all data sectors require authentication.",
            card=protected_1k,
            diagnostics=protected_diags,
        ),
        "mifare_ultralight": SimulatedCard(
            key="mifare_ultralight",
            label="MIFARE Ultralight - public pages",
            description="UID/ATR identified; simulated public page dump.",
            card=ultralight,
            diagnostics=ultralight_diags,
        ),
        "mifare_desfire": SimulatedCard(
            key="mifare_desfire",
            label="MIFARE DESFire - protected applications",
            description="UID identified; application data requires authentication.",
            card=desfire,
            diagnostics=desfire_diags,
        ),
        "iso15693": SimulatedCard(
            key="iso15693",
            label="ISO/IEC 15693 - UID only",
            description="UID identified; memory reading is not implemented.",
            card=iso15693,
            diagnostics=iso15693_diags,
        ),
        "unsupported_125khz": SimulatedCard(
            key="unsupported_125khz",
            label="125 kHz card - unsupported frequency",
            description="Demonstrates a frequency mismatch and a clear unsupported-card diagnosis.",
            card=unsupported,
            diagnostics=unsupported_diags,
        ),
        "vendor_card_error": SimulatedCard(
            key="vendor_card_error",
            label="Vendor firmware 'Card Error'",
            description="Demonstrates how a hardware/firmware compatibility error is reported.",
            card=error_card,
            diagnostics=error_diags,
        ),
        "no_card": SimulatedCard(
            key="no_card",
            label="No card (waiting)",
            description="The simulated reader has no card in the field.",
            card=None,
            diagnostics=(diag.diagnostic(DiagnosticCode.NO_CARD),),
        ),
    }


_CARDS = _build_cards()


class SimulatedBackend(ReaderBackend):
    kind = ReaderKind.SIMULATED
    display_name = "Simulated reader (demo)"

    def __init__(self) -> None:
        self._selected = "mifare_classic_1k"
        self._connected_name: str | None = None

    def availability(self) -> BackendAvailability:
        return BackendAvailability(True, "Simulation is always available.")

    def available_cards(self) -> list[SimulatedCard]:
        return list(_CARDS.values())

    def select_card(self, key: str) -> None:
        if key not in _CARDS:
            raise KeyError(f"Unknown simulated card: {key}")
        self._selected = key

    @property
    def selected_card_key(self) -> str:
        return self._selected

    def list_readers(self) -> list[ReaderInfo]:
        return [
            ReaderInfo(
                name=_SIM_READER_NAME,
                kind=ReaderKind.SIMULATED,
                vendor="Built-in",
                model="Deterministic card simulator",
                interface="In-process simulation",
                supports_pcsc=False,
                notes=("No hardware is accessed in simulation mode.",),
            )
        ]

    def connect(self, reader_name: str) -> ReaderInfo:
        if reader_name not in {reader.name for reader in self.list_readers()}:
            raise ReaderBackendError(diag.diagnostic(DiagnosticCode.READER_NOT_FOUND))
        self._connected_name = reader_name
        return self.list_readers()[0]

    def disconnect(self) -> None:
        self._connected_name = None

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
        events = [f"{utc_timestamp()} simulated scan started"]
        sample = _CARDS[self._selected]

        delay = min(0.15, max(0.0, timeout_s))
        if cancel is not None:
            if cancel.wait(delay):
                return self._result(
                    reader_name, None, [diag.diagnostic(DiagnosticCode.STOPPED)], started, events
                )
        else:
            time.sleep(delay)

        if sample.card is None:
            events.append(f"{utc_timestamp()} no card in simulated field")
            return self._result(
                reader_name, None, list(sample.diagnostics), started, events
            )

        card = copy.deepcopy(sample.card)
        card.details["Simulation card"] = sample.label
        if key is not None:
            events.append(f"{utc_timestamp()} session key supplied (not logged)")
        events.append(
            f"{utc_timestamp()} identified {card.technology.value}; UID {card.uid_display}"
        )
        return self._result(reader_name, card, list(sample.diagnostics), started, events)

    def _result(
        self,
        reader_name: str | None,
        card: CardInfo | None,
        diagnostics: list[Diagnostic],
        started: float,
        events: list[str],
    ) -> ScanResult:
        reader = self.list_readers()[0]
        if reader_name and reader_name != reader.name:
            reader = ReaderInfo(name=reader_name, kind=ReaderKind.SIMULATED)
        return ScanResult(
            reader=reader,
            card=card,
            diagnostics=diagnostics,
            backend="simulated",
            duration_ms=int((time.perf_counter() - started) * 1000),
            simulated=True,
            events=events,
        )


