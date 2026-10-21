from __future__ import annotations

import importlib
import os
import threading
from typing import Any

from .. import diagnostics as diag
from ..models import Diagnostic, DiagnosticCode, ReaderInfo, ReaderKind, ScanResult
from .base import BackendAvailability, ReaderBackend, ReaderBackendError, VendorAdapter


class VendorBackend(ReaderBackend):
    """Opt-in adapter for a documented vendor SDK.

    Configure with:

        set DOORCARD_VENDOR_ADAPTER=my_vendor_adapter:create_adapter

    The factory must return an object implementing doorcard.readers.base.VendorAdapter.
    No vendor protocol is implemented or guessed by this class.
    """

    kind = ReaderKind.VENDOR
    display_name = "Vendor SDK adapter"

    def __init__(self, spec: str | None = None) -> None:
        configured = spec if spec is not None else os.environ.get("DOORCARD_VENDOR_ADAPTER", "")
        self._spec = configured.strip() or None
        self._adapter: VendorAdapter | None = None
        self._load_error: Diagnostic | None = None
        self._loaded = False
        self._reader_name: str | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._spec:
            self._load_error = diag.diagnostic(DiagnosticCode.VENDOR_ADAPTER_NOT_CONFIGURED)
            return
        module_name, _, factory_name = self._spec.partition(":")
        try:
            module = importlib.import_module(module_name)
            factory: Any = getattr(module, factory_name) if factory_name else module
            adapter = factory()
            for method in ("vendor_name", "list_readers", "scan"):
                if not callable(getattr(adapter, method, None)):
                    raise TypeError(f"Vendor adapter is missing required method: {method}")
            self._adapter = adapter
        except Exception as exc:
            self._load_error = diag.diagnostic(
                DiagnosticCode.SDK_MISSING,
                detail=f"Adapter spec: {self._spec}; {type(exc).__name__}: {exc}",
            )

    def availability(self) -> BackendAvailability:
        self._ensure_loaded()
        if self._adapter is None:
            diagnostic = self._load_error or diag.diagnostic(
                DiagnosticCode.VENDOR_ADAPTER_NOT_CONFIGURED
            )
            return BackendAvailability(False, diagnostic.message, (diagnostic,))
        try:
            vendor = self._adapter.vendor_name()
        except Exception:
            vendor = "vendor"
        return BackendAvailability(True, f"Loaded vendor adapter: {vendor}")

    def list_readers(self) -> list[ReaderInfo]:
        self._ensure_loaded()
        if self._adapter is None:
            return []
        try:
            return list(self._adapter.list_readers())
        except Exception as exc:
            raise ReaderBackendError(diag.from_exception(exc, context="vendor reader enumeration")) from exc

    def connect(self, reader_name: str) -> ReaderInfo:
        readers = self.list_readers()
        for reader in readers:
            if reader.name == reader_name:
                self._reader_name = reader_name
                return reader
        raise ReaderBackendError(
            diag.diagnostic(
                DiagnosticCode.READER_NOT_FOUND,
                detail=f"Vendor reader name: {reader_name}",
            )
        )

    def scan(
        self,
        *,
        reader_name: str | None = None,
        timeout_s: float = 10.0,
        key: bytes | None = None,
        read_memory: bool = False,
        cancel: threading.Event | None = None,
    ) -> ScanResult:
        self._ensure_loaded()
        if self._adapter is None:
            diagnostic = self._load_error or diag.diagnostic(
                DiagnosticCode.VENDOR_ADAPTER_NOT_CONFIGURED
            )
            return ScanResult(
                reader=None,
                card=None,
                diagnostics=[diagnostic],
                backend="vendor",
            )
        target = reader_name or self._reader_name
        try:
            return self._adapter.scan(
                reader_name=target,
                timeout_s=timeout_s,
                key=key,
                read_memory=read_memory,
                cancel=cancel,
            )
        except Exception as exc:
            raise ReaderBackendError(diag.from_exception(exc, context="vendor scan")) from exc

    def disconnect(self) -> None:
        self._reader_name = None
