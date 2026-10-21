from __future__ import annotations

import threading

import pytest

from doorcard.models import CardTechnology, DataAccess, DiagnosticCode
from doorcard.readers.simulated import SimulatedBackend


@pytest.fixture()
def backend() -> SimulatedBackend:
    item = SimulatedBackend()
    item.connect("Simulated Reader (demo)")
    return item


def test_all_samples_scan_without_crashing(backend: SimulatedBackend) -> None:
    for sample in backend.available_cards():
        backend.select_card(sample.key)
        result = backend.scan(timeout_s=1.0)
        assert result.simulated is True
        if sample.key == "no_card":
            assert result.card is None
            assert any(item.code is DiagnosticCode.NO_CARD for item in result.diagnostics)
        elif sample.key == "vendor_card_error":
            assert result.card is None
            assert any(item.code is DiagnosticCode.CARD_ERROR_VENDOR for item in result.diagnostics)
        else:
            assert result.card is not None


def test_classic_memory_has_readable_and_protected_sectors(backend: SimulatedBackend) -> None:
    backend.select_card("mifare_classic_1k")
    result = backend.scan(timeout_s=1.0)
    assert result.card is not None
    assert result.card.technology is CardTechnology.MIFARE_CLASSIC_1K
    assert result.card.memory
    assert any(block.access is DataAccess.READABLE for block in result.card.memory)
    assert any(block.access is DataAccess.AUTH_REQUIRED for block in result.card.memory)
    assert any(block.access is DataAccess.PROTECTED for block in result.card.memory)
    assert any(item.code is DiagnosticCode.MEMORY_READ_PARTIAL for item in result.diagnostics)


def test_protected_classic_has_no_readable_data(backend: SimulatedBackend) -> None:
    backend.select_card("mifare_classic_protected")
    result = backend.scan(timeout_s=1.0)
    assert result.card is not None
    assert not any(block.access is DataAccess.READABLE for block in result.card.memory)
    assert any(item.code is DiagnosticCode.AUTH_REQUIRED for item in result.diagnostics)


def test_desfire_requires_authentication(backend: SimulatedBackend) -> None:
    backend.select_card("mifare_desfire")
    result = backend.scan(timeout_s=1.0)
    assert result.card is not None
    assert result.card.technology is CardTechnology.MIFARE_DESFIRE
    assert result.card.access_state is DataAccess.AUTH_REQUIRED


def test_unsupported_frequency_diagnostic(backend: SimulatedBackend) -> None:
    backend.select_card("unsupported_125khz")
    result = backend.scan(timeout_s=1.0)
    assert result.card is not None
    assert result.card.technology is CardTechnology.UNSUPPORTED
    codes = {item.code for item in result.diagnostics}
    assert DiagnosticCode.FREQUENCY_MISMATCH_SUSPECTED in codes
    assert DiagnosticCode.CARD_UNSUPPORTED in codes


def test_vendor_card_error_is_clear(backend: SimulatedBackend) -> None:
    backend.select_card("vendor_card_error")
    result = backend.scan(timeout_s=1.0)
    assert result.card is None
    diagnostic = next(
        item for item in result.diagnostics if item.code is DiagnosticCode.CARD_ERROR_VENDOR
    )
    assert "hardware" in diagnostic.message.lower()


def test_scan_can_be_cancelled(backend: SimulatedBackend) -> None:
    cancel = threading.Event()
    cancel.set()
    result = backend.scan(timeout_s=1.0, cancel=cancel)
    assert result.card is None
    assert any(item.code is DiagnosticCode.STOPPED for item in result.diagnostics)


def test_supplied_key_is_not_logged_in_events(backend: SimulatedBackend) -> None:
    key = bytes.fromhex("A0A1A2A3A4A5")
    result = backend.scan(timeout_s=0.01, key=key)
    joined = "\n".join(result.events)
    assert "a0a1a2a3a4a5" not in joined.lower()
    assert "not logged" in joined
