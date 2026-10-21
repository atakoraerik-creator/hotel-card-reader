from __future__ import annotations

from doorcard import diagnostics as diag
from doorcard.models import DiagnosticCode, Severity


class FakeNoCardException(Exception):
    pass


class FakeCardConnectionException(Exception):
    pass


def test_no_reader_diagnostic_has_remediation() -> None:
    item = diag.no_reader("PC/SC reader")
    assert item.code is DiagnosticCode.NO_READER
    assert item.severity is Severity.ERROR
    assert "PC/SC" in item.message
    assert any("Connect a PC/SC" in step for step in item.remediation)


def test_card_error_diagnostic_explains_hardware_limit() -> None:
    item = diag.card_error("vendor firmware: Card Error")
    assert item.code is DiagnosticCode.CARD_ERROR_VENDOR
    assert "hardware" in item.message.lower()
    combined = " ".join(item.remediation).lower()
    assert "frequency" in combined
    assert "software cannot overcome" in combined


def test_from_exception_maps_no_card() -> None:
    item = diag.from_exception(FakeNoCardException("No card in reader"))
    assert item.code is DiagnosticCode.NO_CARD
    assert item.severity is Severity.ERROR


def test_from_exception_maps_service_failure() -> None:
    item = diag.from_exception(Exception("Failed to establish context (0x8010001D)"))
    assert item.code is DiagnosticCode.PCSC_SERVICE_STOPPED


def test_from_exception_maps_unsupported_card_status() -> None:
    item = diag.from_exception(Exception("SCARD_E_CARD_UNSUPPORTED (0x8010001C)"))
    assert item.code is DiagnosticCode.CARD_UNSUPPORTED


def test_from_exception_maps_access_denied_status() -> None:
    item = diag.from_exception(Exception("SCARD_E_NO_ACCESS (0x80100027)"))
    assert item.code is DiagnosticCode.ACCESS_DENIED


def test_from_exception_maps_removed_card_status() -> None:
    item = diag.from_exception(Exception("SCARD_W_REMOVED_CARD (0x80100069)"))
    assert item.code is DiagnosticCode.CARD_REMOVED


def test_from_exception_maps_missing_card_status() -> None:
    item = diag.from_exception(Exception("SCARD_E_NO_SMARTCARD (0x8010000C)"))
    assert item.code is DiagnosticCode.NO_CARD


def test_from_exception_maps_vendor_card_error() -> None:
    item = diag.from_exception(Exception("Card Error"), context="vendor scan")
    assert item.code is DiagnosticCode.CARD_ERROR_VENDOR
    assert "hardware" in " ".join(item.remediation).lower()


def test_from_exception_maps_communication() -> None:
    item = diag.from_exception(FakeCardConnectionException("The smart card is not answering"))
    assert item.code is DiagnosticCode.COMMUNICATION_FAILURE


def test_status_word_mapping() -> None:
    assert diag.from_status_word(0x63, 0x00).code is DiagnosticCode.AUTHENTICATION_FAILED
    assert diag.from_status_word(0x69, 0x82).code is DiagnosticCode.ACCESS_DENIED
    assert diag.from_status_word(0x6A, 0x81, context="UID read").code is DiagnosticCode.UID_UNAVAILABLE
    assert diag.from_status_word(0x6D, 0x00).code is DiagnosticCode.MEMORY_READ_UNSUPPORTED


def test_partial_memory_diagnostic() -> None:
    item = diag.partial_memory(8, 4)
    assert item.code is DiagnosticCode.MEMORY_READ_PARTIAL
    assert "8" in (item.detail or "")
    assert "4" in (item.detail or "")


def test_diagnostic_to_dict_is_json_safe() -> None:
    item = diag.diagnostic(DiagnosticCode.INTERNAL_ERROR, detail="boom")
    data = item.to_dict()
    assert data["code"] == "internal_error"
    assert data["severity"] == "error"
    assert data["detail"] == "boom"
