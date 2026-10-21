from __future__ import annotations

from .identification import parse_key_hex
from .models import ReaderKind, ScanResult
from .readers.base import ReaderBackend, ReaderBackendError
from .readers.simulated import SimulatedBackend
from .readers.vendor import VendorBackend


def build_backend(kind: ReaderKind | str) -> ReaderBackend:
    if isinstance(kind, str):
        kind = ReaderKind(kind)
    if kind is ReaderKind.SIMULATED:
        return SimulatedBackend()
    if kind is ReaderKind.VENDOR:
        return VendorBackend()
    if kind is ReaderKind.PCSC:
        from .readers.pcsc import PcscBackend

        return PcscBackend()
    raise ValueError(f"Unsupported backend: {kind}")


def result_summary(result: ScanResult) -> str:
    if result.card is None:
        return "No card detected."
    card = result.card
    uid = card.uid_display if card.uid else "UID unavailable"
    return f"{card.technology.value} | {uid} | {card.access_state.value}"


__all__ = [
    "ReaderBackend",
    "ReaderBackendError",
    "build_backend",
    "parse_key_hex",
    "result_summary",
]
