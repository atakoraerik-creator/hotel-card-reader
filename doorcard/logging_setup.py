from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .models import Diagnostic, ScanResult, Severity

REDACTED = "[REDACTED]"


class SecretRedactor:
    """Redacts known secrets from log text.

    The application never intentionally logs keys, but this guard prevents a key
    from leaking through an exception message or a diagnostic detail.
    """

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def add_secret(self, value: str | bytes) -> None:
        variants = _secret_variants(value)
        with self._lock:
            self._secrets.update(variants)

    def discard_secret(self, value: str | bytes) -> None:
        variants = _secret_variants(value)
        with self._lock:
            self._secrets.difference_update(variants)

    def redact(self, text: str) -> str:
        if not text:
            return text
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = re.sub(re.escape(secret), REDACTED, text, flags=re.IGNORECASE)
        return text


def _secret_variants(value: str | bytes) -> set[str]:
    variants: set[str] = set()
    if isinstance(value, bytes):
        raw = value
        if len(raw) >= 4:
            hex_value = raw.hex()
            variants.update(
                {
                    hex_value,
                    hex_value.upper(),
                    " ".join(f"{byte:02X}" for byte in raw),
                    " ".join(f"{byte:02x}" for byte in raw),
                }
            )
            try:
                text = raw.decode("ascii")
            except UnicodeDecodeError:
                text = ""
            if len(text) >= 4:
                variants.add(text)
    else:
        text = value.strip()
        if len(text) >= 4:
            variants.add(text)
            compact = re.sub(r"[\s:\-]", "", text)
            if compact and len(compact) % 2 == 0:
                variants.add(compact)
                variants.add(compact.upper())
                variants.add(compact.lower())
                try:
                    raw = bytes.fromhex(compact)
                except ValueError:
                    raw = b""
                if raw:
                    variants.add(" ".join(f"{byte:02X}" for byte in raw))
                    variants.add(" ".join(f"{byte:02x}" for byte in raw))
    variants.discard("")
    variants.discard(REDACTED)
    return variants


REDACTOR = SecretRedactor()


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = REDACTOR.redact(message)
        record.args = ()
        return True


class JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": REDACTOR.redact(record.getMessage()),
        }
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            payload["exception"] = REDACTOR.redact(exception_text)
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        message = REDACTOR.redact(record.getMessage())
        line = f"{timestamp} {record.levelname:<8} {record.name}: {message}"
        if record.exc_info:
            line += "\n" + REDACTOR.redact(self.formatException(record.exc_info))
        return line


def default_log_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "logs"


def setup_logging(
    log_dir: str | Path | None = None,
    *,
    level: int = logging.INFO,
    console: bool = True,
) -> Path:
    directory = Path(log_dir) if log_dir else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "doorcard.log.jsonl"

    root = logging.getLogger("doorcard")
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    redacting_filter = RedactingFilter()

    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(JsonlFormatter())
    file_handler.addFilter(redacting_filter)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(PlainFormatter())
        console_handler.addFilter(redacting_filter)
        root.addHandler(console_handler)

    return log_path


def get_logger(name: str = "doorcard") -> logging.Logger:
    if name == "doorcard" or name.startswith("doorcard."):
        return logging.getLogger(name)
    return logging.getLogger(f"doorcard.{name}")


def _log_at_severity(logger: logging.Logger, severity: Severity, message: str) -> None:
    level = {
        Severity.INFO: logging.INFO,
        Severity.WARNING: logging.WARNING,
        Severity.ERROR: logging.ERROR,
    }[severity]
    logger.log(level, message)


def log_diagnostic(
    logger: logging.Logger,
    diagnostic: Diagnostic,
    *,
    context: str | None = None,
) -> None:
    """Write one structured diagnostic record, including its remediation."""
    payload = {"event": "diagnostic", "context": context, **diagnostic.to_dict()}
    _log_at_severity(
        logger,
        diagnostic.severity,
        "diagnostic " + json.dumps(payload, ensure_ascii=False),
    )


def log_scan_result(logger: logging.Logger, result: ScanResult) -> None:
    card = result.card
    reader = result.reader.name if result.reader else None
    if card is not None:
        logger.info(
            "card detected "
            + json.dumps(
                {
                    "event": "card_detected",
                    "backend": result.backend,
                    "simulated": result.simulated,
                    "reader": reader,
                    "technology": card.technology.value,
                    "uid": card.uid,
                    "confidence": card.confidence,
                    "access_state": card.access_state.value,
                    "duration_ms": result.duration_ms,
                },
                ensure_ascii=False,
            )
        )
    else:
        logger.info(
            "no card detected "
            + json.dumps(
                {
                    "event": "no_card_detected",
                    "backend": result.backend,
                    "simulated": result.simulated,
                    "reader": reader,
                    "duration_ms": result.duration_ms,
                },
                ensure_ascii=False,
            )
        )

    summary = {
        "event": "scan_result",
        "backend": result.backend,
        "simulated": result.simulated,
        "reader": reader,
        "card_detected": result.card_detected,
        "technology": card.technology.value if card else None,
        "uid": card.uid if card else None,
        "access_state": card.access_state.value if card else None,
        "diagnostics": [item.code.value for item in result.diagnostics],
        "duration_ms": result.duration_ms,
    }
    message = "scan result " + json.dumps(summary, ensure_ascii=False)
    if result.has_errors:
        logger.error(message)
    elif any(item.severity is Severity.WARNING for item in result.diagnostics):
        logger.warning(message)
    else:
        logger.info(message)
