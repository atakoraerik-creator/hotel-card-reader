from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReaderKind(str, Enum):
    PCSC = "pcsc"
    SIMULATED = "simulated"
    VENDOR = "vendor"

    @property
    def label(self) -> str:
        return {
            ReaderKind.PCSC: "PC/SC reader",
            ReaderKind.SIMULATED: "Simulated reader (demo)",
            ReaderKind.VENDOR: "Vendor SDK adapter",
        }[self]


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class CardTechnology(str, Enum):
    MIFARE_CLASSIC_1K = "MIFARE Classic 1K"
    MIFARE_CLASSIC_4K = "MIFARE Classic 4K"
    MIFARE_ULTRALIGHT = "MIFARE Ultralight"
    MIFARE_DESFIRE = "MIFARE DESFire"
    ISO14443A = "ISO/IEC 14443 Type A"
    ISO14443B = "ISO/IEC 14443 Type B"
    ISO15693 = "ISO/IEC 15693"
    UNKNOWN = "Unknown contactless card"
    UNSUPPORTED = "Unsupported card technology"

    @property
    def is_mifare_classic(self) -> bool:
        return self in (CardTechnology.MIFARE_CLASSIC_1K, CardTechnology.MIFARE_CLASSIC_4K)


class DataAccess(str, Enum):
    READABLE = "Readable"
    AUTH_REQUIRED = "Authentication required"
    PROTECTED = "Protected"
    UNREADABLE = "Unreadable"
    UNAVAILABLE = "Unavailable"
    NOT_ATTEMPTED = "Not attempted"
    NOT_SUPPORTED = "Not supported"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(str, Enum):
    SCAN_OK = "scan_ok"
    NO_READER = "no_reader"
    READER_NOT_FOUND = "reader_not_found"
    PCSC_UNAVAILABLE = "pcsc_unavailable"
    PCSC_SERVICE_STOPPED = "pcsc_service_stopped"
    NO_CARD = "no_card"
    CARD_REMOVED = "card_removed"
    CARD_UNSUPPORTED = "card_unsupported"
    CARD_NOT_IDENTIFIED = "card_not_identified"
    FREQUENCY_MISMATCH_SUSPECTED = "frequency_mismatch_suspected"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    COMMUNICATION_FAILURE = "communication_failure"
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTH_REQUIRED = "auth_required"
    ACCESS_DENIED = "access_denied"
    DATA_PROTECTED = "data_protected"
    DATA_UNREADABLE = "data_unreadable"
    UID_UNAVAILABLE = "uid_unavailable"
    ATR_UNAVAILABLE = "atr_unavailable"
    MEMORY_READ_DISABLED = "memory_read_disabled"
    MEMORY_READ_UNSUPPORTED = "memory_read_unsupported"
    MEMORY_READ_PARTIAL = "memory_read_partial"
    INVALID_KEY_FORMAT = "invalid_key_format"
    VENDOR_ADAPTER_NOT_CONFIGURED = "vendor_adapter_not_configured"
    VENDOR_DEVICE_UNVERIFIED = "vendor_device_unverified"
    CARD_ERROR_VENDOR = "card_error_vendor"
    SDK_MISSING = "sdk_missing"
    STOPPED = "stopped"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class Diagnostic:
    code: DiagnosticCode
    severity: Severity
    title: str
    message: str
    remediation: tuple[str, ...] = ()
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "remediation": list(self.remediation),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ReaderInfo:
    name: str
    kind: ReaderKind
    vendor: str | None = None
    model: str | None = None
    interface: str | None = None
    supports_pcsc: bool | None = None
    driver: str | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "vendor": self.vendor,
            "model": self.model,
            "interface": self.interface,
            "supports_pcsc": self.supports_pcsc,
            "driver": self.driver,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MemoryBlock:
    block: int
    address: int
    data: bytes | None
    access: DataAccess
    sector: int | None = None
    note: str | None = None

    @property
    def hex_data(self) -> str:
        if self.data is None:
            return ""
        return self.data.hex(" ").upper()

    @property
    def ascii_data(self) -> str:
        if self.data is None:
            return ""
        return bytes_to_ascii(self.data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "block": self.block,
            "address": self.address,
            "data_hex": self.hex_data,
            "data_ascii": self.ascii_data,
            "access": self.access.value,
            "note": self.note,
        }


@dataclass
class CardInfo:
    technology: CardTechnology = CardTechnology.UNKNOWN
    uid: str | None = None
    uid_bytes: bytes | None = None
    atr: bytes | None = None
    protocol: str | None = None
    manufacturer: str | None = None
    memory_size: str | None = None
    frequency: str | None = None
    confidence: str = "low"
    readable: bool = False
    access_state: DataAccess = DataAccess.NOT_ATTEMPTED
    details: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    memory: list[MemoryBlock] = field(default_factory=list)

    @property
    def atr_hex(self) -> str:
        if not self.atr:
            return ""
        return self.atr.hex(" ").upper()

    @property
    def uid_display(self) -> str:
        if not self.uid:
            return "Unavailable"
        return ":".join(self.uid[i : i + 2] for i in range(0, len(self.uid), 2))

    def to_dict(self) -> dict[str, Any]:
        return {
            "technology": self.technology.value,
            "uid": self.uid,
            "uid_display": self.uid_display,
            "uid_length_bytes": len(self.uid_bytes) if self.uid_bytes else None,
            "atr": self.atr_hex,
            "protocol": self.protocol,
            "manufacturer": self.manufacturer,
            "memory_size": self.memory_size,
            "frequency": self.frequency,
            "confidence": self.confidence,
            "readable": self.readable,
            "access_state": self.access_state.value,
            "details": dict(self.details),
            "warnings": list(self.warnings),
            "memory": [block.to_dict() for block in self.memory],
        }


@dataclass
class ScanResult:
    reader: ReaderInfo | None
    card: CardInfo | None
    diagnostics: list[Diagnostic]
    backend: str
    duration_ms: int = 0
    simulated: bool = False
    events: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def card_detected(self) -> bool:
        return self.card is not None

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def ok(self) -> bool:
        return self.card_detected and not self.has_errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "backend": self.backend,
            "simulated": self.simulated,
            "duration_ms": self.duration_ms,
            "card_detected": self.card_detected,
            "ok": self.ok,
            "reader": self.reader.to_dict() if self.reader else None,
            "card": self.card.to_dict() if self.card else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "events": list(self.events),
        }


def bytes_to_ascii(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
