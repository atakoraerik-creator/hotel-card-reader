from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol

from ..models import Diagnostic, ReaderInfo, ReaderKind, ScanResult


@dataclass(frozen=True)
class BackendAvailability:
    available: bool
    message: str
    diagnostics: tuple[Diagnostic, ...] = ()


class ReaderBackendError(RuntimeError):
    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class ReaderBackend(ABC):
    """Contract for a card-reader backend.

    Implementations must be read-only. They must never write to a card, attempt
    to recover keys, or invoke undocumented vendor commands.
    """

    kind: ReaderKind
    display_name: str

    def availability(self) -> BackendAvailability:
        return BackendAvailability(True, "Available")

    @abstractmethod
    def list_readers(self) -> list[ReaderInfo]:
        """Return currently connected readers."""

    @abstractmethod
    def connect(self, reader_name: str) -> ReaderInfo:
        """Select a reader. Raises ReaderBackendError when unavailable."""

    @abstractmethod
    def scan(
        self,
        *,
        reader_name: str | None = None,
        timeout_s: float = 10.0,
        key: bytes | None = None,
        read_memory: bool = False,
        cancel: threading.Event | None = None,
    ) -> ScanResult:
        """Read identification data from a card, waiting up to timeout_s."""

    def disconnect(self) -> None:
        """Release any selected reader."""


class VendorAdapter(Protocol):
    """Documented vendor-SDK adapter contract.

    A vendor adapter is loaded only when the user explicitly configures
    DOORCARD_VENDOR_ADAPTER=module:factory. The factory must return an object
    implementing this protocol. The adapter owns all vendor-specific commands.
    """

    def vendor_name(self) -> str:
        ...

    def list_readers(self) -> list[ReaderInfo]:
        ...

    def scan(
        self,
        *,
        reader_name: str | None,
        timeout_s: float,
        key: bytes | None,
        read_memory: bool,
        cancel: threading.Event | None,
    ) -> ScanResult:
        ...


@dataclass
class BackendStatus:
    available: bool
    message: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
