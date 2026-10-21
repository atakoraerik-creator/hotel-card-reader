from __future__ import annotations

import json

from doorcard.cli import main


def test_cli_simulated_scan_exports_json(tmp_path, capsys) -> None:
    report = tmp_path / "report.json"
    exit_code = main(
        [
            "--simulate",
            "mifare_classic_1k",
            "--scan",
            "--json",
            str(report),
            "--no-console-log",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "MIFARE Classic 1K" in output
    assert "Card detected" not in output
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["card"]["technology"] == "MIFARE Classic 1K"
    assert data["card"]["memory"]


def test_cli_no_card_returns_nonzero(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--simulate",
            "no_card",
            "--scan",
            "--no-console-log",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "NO CARD" in output


def test_cli_export_failure_returns_configuration_error(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--simulate",
            "mifare_classic_1k",
            "--scan",
            "--json",
            str(tmp_path),
            "--no-console-log",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Could not write report" in captured.err


def test_cli_list_readers_simulated(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--simulate",
            "mifare_classic_1k",
            "--list-readers",
            "--no-console-log",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Simulated Reader" in output


def test_cli_diagnose_simulated(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "--simulate",
            "mifare_classic_1k",
            "--diagnose",
            "--no-console-log",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Backend availability: AVAILABLE" in output
    assert "Simulated Reader" in output
