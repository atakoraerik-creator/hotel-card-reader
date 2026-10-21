from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .identification import memory_summary
from .models import MemoryBlock, ScanResult


def _payload(result: ScanResult) -> dict[str, Any]:
    data = result.to_dict()
    data["application"] = "Universal Electronic Door Card Reader"
    data["application_version"] = __version__
    data["exported_at"] = datetime.now(UTC).isoformat(timespec="milliseconds")
    data["security"] = (
        "Read-only report. No secret keys, passwords, or access credentials are stored or exported."
    )
    return data


def export_json(result: ScanResult, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_payload(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def _summary_row(result: ScanResult) -> dict[str, Any]:
    card = result.card
    diagnostics = "; ".join(f"{item.code.value}: {item.title}" for item in result.diagnostics)
    warnings = "; ".join(card.warnings) if card else ""
    summary = memory_summary(card.memory) if card else {}
    return {
        "timestamp": result.timestamp.isoformat(),
        "backend": result.backend,
        "simulated": result.simulated,
        "reader": result.reader.name if result.reader else "",
        "card_detected": result.card_detected,
        "technology": card.technology.value if card else "",
        "uid": card.uid or "" if card else "",
        "uid_display": card.uid_display if card else "",
        "atr": card.atr_hex if card else "",
        "protocol": (card.protocol or "") if card else "",
        "manufacturer": (card.manufacturer or "") if card else "",
        "memory_size": (card.memory_size or "") if card else "",
        "frequency": (card.frequency or "") if card else "",
        "confidence": card.confidence if card else "",
        "readable": card.readable if card else "",
        "access_state": card.access_state.value if card else "",
        "memory_summary": "; ".join(f"{key}={value}" for key, value in sorted(summary.items())),
        "warnings": warnings,
        "diagnostic_codes": "; ".join(item.code.value for item in result.diagnostics),
        "diagnostics": diagnostics,
        "duration_ms": result.duration_ms,
    }


def _row_for_block(result: ScanResult, summary: dict[str, Any], block: MemoryBlock) -> dict[str, Any]:
    row = dict(summary)
    row.update(
        {
            "sector": "" if block.sector is None else block.sector,
            "block": block.block,
            "address": block.address,
            "data_hex": block.hex_data,
            "data_ascii": block.ascii_data,
            "block_access": block.access.value,
            "block_note": block.note or "",
        }
    )
    return row


def export_csv(result: ScanResult, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    summary = _summary_row(result)
    columns = list(summary) + [
        "sector",
        "block",
        "address",
        "data_hex",
        "data_ascii",
        "block_access",
        "block_note",
    ]

    rows: list[dict[str, Any]] = []
    if result.card and result.card.memory:
        for block in result.card.memory:
            rows.append(_row_for_block(result, summary, block))
    else:
        rows.append(dict(summary))

    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def export_auto(result: ScanResult, path: str | Path) -> Path:
    destination = Path(path)
    if destination.suffix.lower() == ".csv":
        return export_csv(result, destination)
    if destination.suffix.lower() != ".json":
        destination = destination.with_suffix(".json")
    return export_json(result, destination)
