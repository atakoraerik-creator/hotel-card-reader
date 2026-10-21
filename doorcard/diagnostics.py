from __future__ import annotations

from .logging_setup import REDACTOR
from .models import Diagnostic, DiagnosticCode, Severity

_CATALOG: dict[DiagnosticCode, tuple[str, str, tuple[str, ...]]] = {
    DiagnosticCode.SCAN_OK: (
        "Scan succeeded",
        "The reader returned card information.",
        (),
    ),
    DiagnosticCode.NO_READER: (
        "No reader available",
        "No compatible reader was found. The app cannot read a card without a connected reader.",
        (
            "Connect a PC/SC-compatible contactless reader (for example an ACS ACR122U or ACR1252U).",
            "Close other smart-card applications that may have exclusive access to the reader.",
            "Open Windows Services and confirm that 'Smart Card' (SCardSvr) can start.",
            "Use 'Refresh Readers' after connecting the device.",
        ),
    ),
    DiagnosticCode.READER_NOT_FOUND: (
        "Selected reader not found",
        "The selected reader is no longer present or its name changed.",
        (
            "Reconnect the reader and use 'Refresh Readers'.",
            "Avoid unplugging the reader while a scan is running.",
        ),
    ),
    DiagnosticCode.PCSC_UNAVAILABLE: (
        "PC/SC is unavailable",
        "The PC/SC smart-card subsystem could not be initialized.",
        (
            "Confirm that winscard.dll and the Smart Card service are present.",
            "Restart Windows if the Smart Card service cannot start.",
            "On non-Windows systems, install pcscd and the PC/SC runtime.",
        ),
    ),
    DiagnosticCode.PCSC_SERVICE_STOPPED: (
        "Smart Card service is not running",
        "Windows could not start or reach the Smart Card service.",
        (
            "Open Services (services.msc) and start 'Smart Card' (SCardSvr).",
            "Set the service startup type to Manual (demand start) if it was disabled.",
            "Reconnect the reader after the service starts.",
        ),
    ),
    DiagnosticCode.NO_CARD: (
        "No card detected",
        "The reader is connected, but no card is currently in the RF field.",
        (
            "Place the card flat and centered on the reader.",
            "Remove the card and place it again; some readers need a short delay.",
            "Remove metal objects, phones, and other cards from the reader area.",
            "Try another card to determine whether the reader itself is working.",
        ),
    ),
    DiagnosticCode.CARD_REMOVED: (
        "Card was removed",
        "The card left the field before the read completed.",
        (
            "Keep the card on the reader for the entire scan.",
            "Try a slower, steady placement.",
        ),
    ),
    DiagnosticCode.CARD_UNSUPPORTED: (
        "Card technology is not supported",
        "The card is not supported by this reader or by the current application path.",
        (
            "Check the card's frequency and technology (for example 125 kHz vs 13.56 MHz).",
            "Use a reader that explicitly supports the card's frequency and protocol.",
            "PC/SC 13.56 MHz readers cannot read 125 kHz Temic/T5577 hotel cards.",
        ),
    ),
    DiagnosticCode.CARD_NOT_IDENTIFIED: (
        "Card could not be identified",
        "The card responded, but its family could not be determined from the available information.",
        (
            "The ATR may be reader-specific or the card may use a proprietary protocol.",
            "Check the reader manual for supported card types.",
            "Try a reader with a documented SDK for this card family.",
        ),
    ),
    DiagnosticCode.FREQUENCY_MISMATCH_SUSPECTED: (
        "Possible frequency mismatch",
        "The card may operate on a frequency this reader does not support.",
        (
            "Confirm whether the card is 125 kHz or 13.56 MHz.",
            "A 13.56 MHz NFC reader cannot read 125 kHz hotel cards, even if they look identical.",
            "Use a reader/writer designed for the card's frequency.",
        ),
    ),
    DiagnosticCode.PROTOCOL_MISMATCH: (
        "Protocol mismatch",
        "The reader and card could not agree on a communication protocol.",
        (
            "Try reconnecting the reader.",
            "Confirm that the reader supports the card's protocol (ISO/IEC 14443 A/B or 15693).",
            "Update the reader firmware if the vendor provides an update.",
        ),
    ),
    DiagnosticCode.COMMUNICATION_FAILURE: (
        "Communication failure",
        "The reader or card stopped responding during the operation.",
        (
            "Reconnect the reader and try again.",
            "Keep the card still and centered.",
            "Close other applications that may be using the reader.",
            "Try another USB port or cable if the problem persists.",
        ),
    ),
    DiagnosticCode.AUTHENTICATION_FAILED: (
        "Authentication failed",
        "The card rejected the supplied key or access condition.",
        (
            "This data is protected. Reading it requires the correct key, which this app does not recover.",
            "Do not attempt to bypass the protection; only read cards you own or are authorized to inspect.",
            "If you have an authorized key, enter it in the session-only key field.",
        ),
    ),
    DiagnosticCode.AUTH_REQUIRED: (
        "Authentication required",
        "The card or memory area is protected and requires a key or application authentication.",
        (
            "Only the UID and other public identification data can be shown.",
            "Protected memory cannot be read without an authorized key.",
            "The app never attempts to recover, brute-force, or extract keys.",
        ),
    ),
    DiagnosticCode.ACCESS_DENIED: (
        "Access denied",
        "The card refused the requested operation under its current access conditions.",
        (
            "The data may be read-only, protected, or restricted to a different application.",
            "Use the vendor's authorized application if you are entitled to access it.",
        ),
    ),
    DiagnosticCode.DATA_PROTECTED: (
        "Data is protected",
        "The requested data is protected by the card's security configuration.",
        (
            "Protected keys, access bits, and application data are intentionally not displayed.",
            "Only public identification data is shown.",
        ),
    ),
    DiagnosticCode.DATA_UNREADABLE: (
        "Data is unreadable",
        "The card returned an error for the requested block or file.",
        (
            "The block may be unreadable, reserved, or outside the card's memory map.",
            "Try a full scan again; some errors are transient.",
        ),
    ),
    DiagnosticCode.UID_UNAVAILABLE: (
        "UID unavailable",
        "The reader did not return a UID through the standard PC/SC GET DATA command.",
        (
            "This is common: UID access is reader- and firmware-dependent.",
            "Check the reader manual for a UID command or vendor SDK.",
            "Card identification may still be possible from the ATR.",
        ),
    ),
    DiagnosticCode.ATR_UNAVAILABLE: (
        "ATR unavailable",
        "The reader did not return an Answer To Reset (ATR) for the card.",
        (
            "The reader may not expose contactless ATRs.",
            "Try a different PC/SC reader if card identification is important.",
        ),
    ),
    DiagnosticCode.MEMORY_READ_DISABLED: (
        "Memory reading is disabled",
        "Identification succeeded, but memory reading was not requested.",
        (
            "Enable 'Attempt read-only memory read' if you own the card and have an authorized key.",
            "Memory reading is optional and never writes to the card.",
        ),
    ),
    DiagnosticCode.MEMORY_READ_UNSUPPORTED: (
        "Memory reading is not supported for this reader/card",
        "The installed reader did not accept the documented read-only memory commands.",
        (
            "Use a reader with a documented PC/SC MIFARE command set (for example an ACS reader).",
            "For DESFire, Ultralight, or ISO/IEC 15693, use the vendor SDK or a card-specific tool.",
            "The UID and card identification are still valid.",
        ),
    ),
    DiagnosticCode.MEMORY_READ_PARTIAL: (
        "Partial memory read",
        "Some sectors were readable, but others require authentication or could not be read.",
        (
            "Only the readable blocks are displayed.",
            "Protected sectors remain marked as authentication-required.",
            "The app never reads sector trailers or displays key material.",
        ),
    ),
    DiagnosticCode.INVALID_KEY_FORMAT: (
        "Invalid key format",
        "The session key is not a valid 6-byte MIFARE Classic key.",
        (
            "Enter exactly 12 hexadecimal digits (6 bytes), for example FFFFFFFFFFFF.",
            "Keys are kept in memory for the current scan only and are never written to logs or reports.",
        ),
    ),
    DiagnosticCode.VENDOR_ADAPTER_NOT_CONFIGURED: (
        "Vendor adapter not configured",
        "No verified vendor SDK adapter is installed for this device.",
        (
            "Set DOORCARD_VENDOR_ADAPTER to a documented adapter module if you have the vendor SDK.",
            "Without an SDK, only PC/SC readers can be enumerated.",
            "Do not guess undocumented device commands.",
        ),
    ),
    DiagnosticCode.VENDOR_DEVICE_UNVERIFIED: (
        "Vendor device is unverified",
        "This device has not been verified against a documented interface in this installation.",
        (
            "Record the model, USB VID/PID, driver, and firmware version.",
            "Obtain the vendor SDK and confirm that read-only third-party access is permitted.",
            "Test the device with a known card before relying on the result.",
        ),
    ),
    DiagnosticCode.CARD_ERROR_VENDOR: (
        "Vendor reported 'Card Error'",
        "The encoder/reader firmware reported a card error. This is a hardware/firmware compatibility signal, not a software bug in this app.",
        (
            "Confirm the encoder supports the card's frequency and card family.",
            "Old 125 kHz cards and new 13.56 MHz MIFARE Classic cards require different hardware.",
            "Check whether the card is MIFARE Classic EV1, MIFARE Plus, or a clone with a different UID length.",
            "Test a known genuine card and compare it with the failing card on a PC/SC reader.",
            "Update the vendor software/firmware if an update exists, or contact the vendor with the exact model and error text.",
            "Software cannot overcome incompatible reader hardware.",
        ),
    ),
    DiagnosticCode.SDK_MISSING: (
        "Vendor SDK missing",
        "The configured vendor adapter could not load its SDK.",
        (
            "Install the vendor SDK in the expected location and check its architecture (32/64-bit).",
            "Confirm the adapter module path in DOORCARD_VENDOR_ADAPTER.",
        ),
    ),
    DiagnosticCode.STOPPED: (
        "Scan stopped",
        "The scan was cancelled by the user.",
        (),
    ),
    DiagnosticCode.INTERNAL_ERROR: (
        "Unexpected error",
        "An unexpected error occurred while scanning.",
        (
            "Try the scan again.",
            "Run diagnostic mode and check the log file for details.",
            "Report the error with the log file if the problem persists.",
        ),
    ),
}


def diagnostic(
    code: DiagnosticCode,
    *,
    detail: str | None = None,
    severity: Severity | None = None,
    message: str | None = None,
    remediation: tuple[str, ...] | None = None,
) -> Diagnostic:
    title, default_message, default_remediation = _CATALOG[code]
    return Diagnostic(
        code=code,
        severity=severity or _default_severity(code),
        title=title,
        message=REDACTOR.redact(message or default_message),
        remediation=remediation if remediation is not None else default_remediation,
        detail=REDACTOR.redact(detail) if detail else None,
    )


def _default_severity(code: DiagnosticCode) -> Severity:
    if code in (
        DiagnosticCode.SCAN_OK,
        DiagnosticCode.MEMORY_READ_DISABLED,
        DiagnosticCode.STOPPED,
    ):
        return Severity.INFO
    if code in (
        DiagnosticCode.AUTH_REQUIRED,
        DiagnosticCode.MEMORY_READ_PARTIAL,
        DiagnosticCode.UID_UNAVAILABLE,
        DiagnosticCode.ATR_UNAVAILABLE,
        DiagnosticCode.VENDOR_DEVICE_UNVERIFIED,
        DiagnosticCode.CARD_NOT_IDENTIFIED,
    ):
        return Severity.WARNING
    return Severity.ERROR


def from_status_word(sw1: int, sw2: int, context: str = "operation") -> Diagnostic:
    sw = (sw1 << 8) | sw2
    mapping = {
        0x6300: DiagnosticCode.AUTHENTICATION_FAILED,
        0x6982: DiagnosticCode.ACCESS_DENIED,
        0x6985: DiagnosticCode.AUTH_REQUIRED,
        0x6A80: DiagnosticCode.DATA_UNREADABLE,
        0x6A81: DiagnosticCode.MEMORY_READ_UNSUPPORTED,
        0x6A82: DiagnosticCode.DATA_UNREADABLE,
        0x6A83: DiagnosticCode.DATA_UNREADABLE,
        0x6A86: DiagnosticCode.PROTOCOL_MISMATCH,
        0x6A88: DiagnosticCode.DATA_UNREADABLE,
        0x6700: DiagnosticCode.PROTOCOL_MISMATCH,
        0x6881: DiagnosticCode.MEMORY_READ_UNSUPPORTED,
        0x6D00: DiagnosticCode.MEMORY_READ_UNSUPPORTED,
        0x6E00: DiagnosticCode.MEMORY_READ_UNSUPPORTED,
        0x6F00: DiagnosticCode.INTERNAL_ERROR,
    }
    code = mapping.get(sw, DiagnosticCode.COMMUNICATION_FAILURE)
    detail = f"{context}: status word {sw1:02X}{sw2:02X}"
    if context.lower().startswith("uid") and code is DiagnosticCode.MEMORY_READ_UNSUPPORTED:
        code = DiagnosticCode.UID_UNAVAILABLE
    return diagnostic(code, detail=detail)


def from_exception(exc: BaseException, context: str = "scan") -> Diagnostic:
    name = type(exc).__name__.lower()
    text = str(exc)
    lowered = text.lower()
    detail = f"{context}: {type(exc).__name__}: {text}" if text else f"{context}: {type(exc).__name__}"

    if "card error" in lowered or "unrecognized card" in lowered:
        return card_error(detail)
    if (
        "unsupported card" in lowered
        or "card not supported" in lowered
        or "0x8010001c" in lowered
        or "0x8010000d" in lowered
    ):
        return diagnostic(DiagnosticCode.CARD_UNSUPPORTED, detail=detail)
    if "nocard" in name or "no card" in lowered or "no smart card" in lowered:
        return diagnostic(DiagnosticCode.NO_CARD, detail=detail)
    if "removed" in lowered or "0x80100069" in lowered or "0x80100068" in lowered:
        return diagnostic(DiagnosticCode.CARD_REMOVED, detail=detail)
    if "0x8010002e" in lowered or "no readers" in lowered or "no reader" in lowered:
        return diagnostic(DiagnosticCode.NO_READER, detail=detail)
    if "0x8010001d" in lowered or "no service" in lowered or "service" in lowered and "smart card" in lowered:
        return diagnostic(DiagnosticCode.PCSC_SERVICE_STOPPED, detail=detail)
    if "0x8010000f" in lowered or "protocol" in lowered and "mismatch" in lowered:
        return diagnostic(DiagnosticCode.PROTOCOL_MISMATCH, detail=detail)
    if "0x8010000c" in lowered:
        return diagnostic(DiagnosticCode.NO_CARD, detail=detail)
    if "establishcontext" in name or "listreaders" in name or "0x8010001d" in lowered:
        return diagnostic(DiagnosticCode.PCSC_UNAVAILABLE, detail=detail)
    if (
        "cardconnection" in name
        or "0x80100066" in lowered
        or "0x80100067" in lowered
        or "0x8010000b" in lowered
        or "0x8010002f" in lowered
        or "not answering" in lowered
        or "transmit" in lowered
        or "communication" in lowered
    ):
        return diagnostic(DiagnosticCode.COMMUNICATION_FAILURE, detail=detail)
    if isinstance(exc, ValueError) and "key" in lowered:
        return diagnostic(DiagnosticCode.INVALID_KEY_FORMAT, detail=detail)
    if (
        "permission" in lowered
        or "access is denied" in lowered
        or "0x80100027" in lowered
    ):
        return diagnostic(DiagnosticCode.ACCESS_DENIED, detail=detail)
    return diagnostic(DiagnosticCode.INTERNAL_ERROR, detail=detail)


def no_reader(backend_label: str) -> Diagnostic:
    message = (
        f"No {backend_label} was found. Connect a compatible reader, then refresh the reader list."
    )
    return diagnostic(DiagnosticCode.NO_READER, message=message, detail=f"Backend: {backend_label}")


def card_error(detail: str | None = None) -> Diagnostic:
    return diagnostic(DiagnosticCode.CARD_ERROR_VENDOR, detail=detail)


def vendor_unverified(reader_name: str) -> Diagnostic:
    return diagnostic(
        DiagnosticCode.VENDOR_DEVICE_UNVERIFIED,
        detail=f"Device: {reader_name}",
    )


def memory_read_unsupported(reader_name: str, detail: str | None = None) -> Diagnostic:
    return diagnostic(
        DiagnosticCode.MEMORY_READ_UNSUPPORTED,
        detail=detail or f"Reader: {reader_name}",
    )


def partial_memory(readable: int, protected: int) -> Diagnostic:
    return diagnostic(
        DiagnosticCode.MEMORY_READ_PARTIAL,
        detail=f"{readable} block(s) readable, {protected} block(s) protected or unreadable",
    )
