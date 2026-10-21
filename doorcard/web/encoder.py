from __future__ import annotations

import threading

from .. import diagnostics as diag
from ..models import Diagnostic, DiagnosticCode, ReaderKind, ScanResult, Severity, utc_timestamp
from ..readers.base import ReaderBackend, ReaderBackendError
from ..readers.simulated import SimulatedBackend
from ..service import build_backend

MODE_LABELS = {
    "simulated": "Simulation mode",
    "pcsc": "PC/SC reader",
    "vendor": "Vendor SDK adapter",
}


class EncoderBridge:
    def __init__(self, mode: str = "simulated") -> None:
        self.mode = mode
        self._lock = threading.RLock()
        self._backend: ReaderBackend | None = None
        self._connected = mode == "simulated"
        self._readers: list[dict] = []
        self._diagnostics: list[Diagnostic] = []
        self._message = (
            "Simulated encoder is ready. No physical card will be read or written."
            if mode == "simulated"
            else "Encoder has not been checked yet."
        )
        self._last_scan: ScanResult | None = None
        self._last_checked: str | None = None

    def status(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        diagnostics = list(self._diagnostics)
        if self._last_scan is not None:
            for item in self._last_scan.diagnostics:
                if item not in diagnostics:
                    diagnostics.append(item)
        errors = [item for item in diagnostics if item.severity is Severity.ERROR]
        card = self._last_scan.card if self._last_scan else None
        return {
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode.title()),
            "connected": self._connected,
            "card_detected": card is not None,
            "message": self._message,
            "readers": list(self._readers),
            "diagnostics": [item.to_dict() for item in diagnostics],
            "has_error": bool(errors),
            "card": card.to_dict() if card else None,
            "last_scan": self._last_scan.to_dict() if self._last_scan else None,
            "last_checked": self._last_checked,
            "hardware_write_enabled": False,
        }

    def check(self) -> dict:
        with self._lock:
            self._last_checked = utc_timestamp()
            self._diagnostics = []
            try:
                backend = build_backend(self.mode)
                availability = backend.availability()
                self._backend = backend
                if not availability.available:
                    self._connected = False
                    self._readers = []
                    self._diagnostics = list(availability.diagnostics)
                    self._message = availability.message
                    return self._snapshot()
                readers = backend.list_readers()
                self._readers = [reader.to_dict() for reader in readers]
                self._connected = bool(readers) or self.mode == "simulated"
                if readers:
                    self._message = f"Encoder connected: {readers[0].name}."
                elif self.mode == "simulated":
                    self._message = (
                        "Simulated encoder is ready. No physical card will be read or written."
                    )
                else:
                    self._message = "No supported encoder or reader was found."
                    self._diagnostics = [
                        diag.diagnostic(
                            DiagnosticCode.NO_READER,
                            message="No supported encoder or reader was found.",
                            detail="The backend is available but returned no readers.",
                        )
                    ]
            except ReaderBackendError as exc:
                self._backend = None
                self._connected = False
                self._readers = []
                self._diagnostics = [exc.diagnostic]
                self._message = exc.diagnostic.message
            except Exception as exc:
                self._backend = None
                self._connected = False
                self._readers = []
                self._diagnostics = [diag.from_exception(exc, context="encoder check")]
                self._message = self._diagnostics[0].message
            return self._snapshot()

    def detect(self, sample_key: str = "mifare_classic_1k") -> dict:
        with self._lock:
            if self.mode == "simulated":
                backend = SimulatedBackend()
                if sample_key not in {card.key for card in backend.available_cards()}:
                    sample_key = "mifare_classic_1k"
                backend.select_card(sample_key)
                reader_name = backend.list_readers()[0].name
                timeout = 1.0
            else:
                if self._backend is None:
                    self.check()
                backend = self._backend
                reader_name = None
                timeout = 3.0
                if backend is None:
                    return self._snapshot()

            self._last_checked = utc_timestamp()
            try:
                result = backend.scan(
                    reader_name=reader_name,
                    timeout_s=timeout,
                    read_memory=False,
                )
                self._last_scan = result
                if result.card is not None:
                    self._connected = True
                    self._message = (
                        f"Card detected: {result.card.technology.value}. "
                        "Read-only detection; no write was attempted."
                    )
                else:
                    self._message = "No card detected. Place a compatible card on the encoder."
            except ReaderBackendError as exc:
                self._last_scan = None
                self._diagnostics = [exc.diagnostic]
                self._message = exc.diagnostic.message
            except Exception as exc:
                self._last_scan = None
                self._diagnostics = [diag.from_exception(exc, context="encoder detection")]
                self._message = self._diagnostics[0].message
            return self._snapshot()

    def sample_cards(self) -> list[dict]:
        backend = SimulatedBackend()
        return [
            {"key": card.key, "label": card.label, "description": card.description}
            for card in backend.available_cards()
        ]

    @property
    def reader_kind(self) -> ReaderKind:
        return ReaderKind(self.mode)
