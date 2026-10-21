"""Reader backends for the Universal Electronic Door Card Reader."""

from .base import BackendAvailability, ReaderBackend, ReaderBackendError, VendorAdapter
from .simulated import SimulatedBackend
from .vendor import VendorBackend

try:
    from .pcsc import PcscBackend
except Exception:  # pragma: no cover - pyscard import problems are reported at runtime
    PcscBackend = None  # type: ignore[assignment]

__all__ = [
    "BackendAvailability",
    "PcscBackend",
    "ReaderBackend",
    "ReaderBackendError",
    "SimulatedBackend",
    "VendorAdapter",
    "VendorBackend",
]
