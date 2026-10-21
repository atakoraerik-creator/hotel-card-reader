from __future__ import annotations

import json
import logging

from doorcard import diagnostics as diag
from doorcard.diagnostics import from_exception
from doorcard.export import export_auto, export_csv, export_json
from doorcard.logging_setup import (
    REDACTOR,
    get_logger,
    log_diagnostic,
    log_scan_result,
    setup_logging,
)
from doorcard.readers.simulated import SimulatedBackend


def test_logs_redact_session_key(tmp_path) -> None:
    log_path = setup_logging(tmp_path, console=False)
    key = bytes.fromhex("A0A1A2A3A4A5")
    REDACTOR.add_secret(key)
    logger = get_logger("doorcard.test_redaction")
    try:
        logger.info("session key is %s and %s", key.hex(), key.hex(" "))
        try:
            raise ValueError(f"bad key {key.hex()}")
        except ValueError:
            logger.exception("operation failed")
    finally:
        for handler in logging.getLogger("doorcard").handlers:
            handler.flush()
        REDACTOR.discard_secret(key)

    text = log_path.read_text(encoding="utf-8").lower()
    assert "a0a1a2a3a4a5" not in text
    assert "a0 a1 a2 a3 a4 a5" not in text
    assert "redacted" in text


def test_diagnostic_detail_redacts_session_key() -> None:
    key = bytes.fromhex("A0A1A2A3A4A5")
    REDACTOR.add_secret(key)
    try:
        diagnostic = from_exception(
            RuntimeError(f"transmit failed for FF 82 ... {key.hex()}"),
            context="MIFARE memory read",
        )
    finally:
        REDACTOR.discard_secret(key)
    assert "a0a1a2a3a4a5" not in (diagnostic.detail or "").lower()
    assert "redacted" in (diagnostic.detail or "").lower()


def test_structured_diagnostic_logging(tmp_path) -> None:
    log_path = setup_logging(tmp_path, console=False)
    log_diagnostic(
        get_logger("doorcard.test_diagnostic"),
        diag.card_error("vendor firmware: Card Error"),
        context="unit-test",
    )
    for handler in logging.getLogger("doorcard").handlers:
        handler.flush()

    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    messages = "\n".join(record["message"] for record in records)
    assert '"event": "diagnostic"' in messages
    assert '"context": "unit-test"' in messages
    assert '"code": "card_error_vendor"' in messages
    assert "hardware" in messages.lower()


def test_scan_result_logging_includes_detection(tmp_path) -> None:
    log_path = setup_logging(tmp_path, console=False)
    result = _scan_classic()
    log_scan_result(get_logger("doorcard.test_scan"), result)
    for handler in logging.getLogger("doorcard").handlers:
        handler.flush()

    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    messages = "\n".join(record["message"] for record in records)
    assert '"event": "card_detected"' in messages
    assert '"event": "scan_result"' in messages
    assert "MIFARE Classic 1K" in messages
    assert "04A1B2C3D4E5F6" in messages


def _scan_classic() -> object:
    backend = SimulatedBackend()
    backend.select_card("mifare_classic_1k")
    backend.connect("Simulated Reader (demo)")
    return backend.scan(timeout_s=1.0)


def test_export_json_contains_card_and_no_secret(tmp_path) -> None:
    result = _scan_classic()
    key = b"\xa0\xa1\xa2\xa3\xa4\xa5"
    result = SimulatedBackend().scan(timeout_s=0.01, key=key)
    path = export_json(result, tmp_path / "report.json")
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["card"]["technology"] == "MIFARE Classic 1K"
    assert data["card"]["uid"] == "04A1B2C3D4E5F6"
    assert data["card"]["memory"]
    assert data["security"].startswith("Read-only report")
    assert "a0a1a2a3a4a5" not in text.lower()
    assert "a0 a1 a2 a3 a4 a5" not in text.lower()


def test_export_csv_has_one_row_per_memory_block(tmp_path) -> None:
    result = _scan_classic()
    path = export_csv(result, tmp_path / "report.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(result.card.memory) + 1
    assert "data_hex" in lines[0]
    assert "block_access" in lines[0]
    assert "MIFARE Classic 1K" in lines[1]
    assert "04A1B2C3D4E5F6" in lines[1]


def test_export_auto_chooses_by_suffix(tmp_path) -> None:
    result = _scan_classic()
    json_path = export_auto(result, tmp_path / "report.unknown")
    assert json_path.suffix == ".json"
    csv_path = export_auto(result, tmp_path / "report.csv")
    assert csv_path.suffix == ".csv"
    assert json_path.exists()
    assert csv_path.exists()
