from __future__ import annotations

import re
from dataclasses import dataclass

from .models import CardInfo, CardTechnology, DataAccess, MemoryBlock


@dataclass(frozen=True)
class AtrProfile:
    technology: CardTechnology
    manufacturer: str | None = None
    memory_size: str | None = None
    confidence: str = "medium"
    note: str | None = None


_KNOWN_ATRS: dict[str, AtrProfile] = {
    "3B8F8001804F0CA000000306030001000000006A": AtrProfile(
        CardTechnology.MIFARE_CLASSIC_1K,
        manufacturer="NXP Semiconductors",
        memory_size="1024 bytes (16 sectors x 4 blocks)",
        confidence="high",
        note="Known MIFARE Classic 1K PC/SC ATR",
    ),
    "3B8F8001804F0CA000000306030002000000006B": AtrProfile(
        CardTechnology.MIFARE_CLASSIC_4K,
        manufacturer="NXP Semiconductors",
        memory_size="4096 bytes (40 sectors)",
        confidence="high",
        note="Known MIFARE Classic 4K PC/SC ATR",
    ),
    "3B8F8001804F0CA0000003060300030000000068": AtrProfile(
        CardTechnology.MIFARE_ULTRALIGHT,
        manufacturer="NXP Semiconductors",
        memory_size="64 bytes (16 pages) for Ultralight; Ultralight C has 192 bytes",
        confidence="high",
        note="Known MIFARE Ultralight PC/SC ATR",
    ),
    "3B8180018080": AtrProfile(
        CardTechnology.MIFARE_ULTRALIGHT,
        manufacturer="NXP Semiconductors",
        memory_size="64 bytes (16 pages) for Ultralight; Ultralight C has 192 bytes",
        confidence="medium",
        note="Common PC/SC ATR for MIFARE Ultralight",
    ),
    "3B86800106757781028000": AtrProfile(
        CardTechnology.MIFARE_DESFIRE,
        manufacturer="NXP Semiconductors",
        memory_size="DESFire capacity varies by variant (2K/4K/8K)",
        confidence="medium",
        note="Common PC/SC ATR for MIFARE DESFire",
    ),
}

_CLASSIC_PREFIX = "3B8F8001804F0CA00000030603"
_GENERIC_ISO14443A_PREFIX = "3B8F8001804F0CA000000306"

_MANUFACTURERS = {
    0x04: "NXP Semiconductors (derived from UID prefix; not guaranteed)",
}


def normalize_hex(value: str) -> str:
    return re.sub(r"[\s:\-]", "", value).upper()


def hex_to_bytes(value: str) -> bytes:
    normalized = normalize_hex(value)
    if len(normalized) % 2:
        raise ValueError("Hex string must contain an even number of digits")
    return bytes.fromhex(normalized)


def _profile_from_atr(atr_hex: str) -> tuple[AtrProfile | None, str]:
    if not atr_hex:
        return None, "empty"

    exact = _KNOWN_ATRS.get(atr_hex)
    if exact:
        return exact, "exact"

    if atr_hex.startswith(_CLASSIC_PREFIX) and len(atr_hex) >= 30:
        card_byte = atr_hex[28:30]
        if card_byte == "01":
            return AtrProfile(
                CardTechnology.MIFARE_CLASSIC_1K,
                manufacturer="NXP Semiconductors",
                memory_size="1024 bytes (16 sectors x 4 blocks)",
                confidence="high",
                note="MIFARE Classic 1K identified from PC/SC ATR pattern",
            ), "pattern"
        if card_byte == "02":
            return AtrProfile(
                CardTechnology.MIFARE_CLASSIC_4K,
                manufacturer="NXP Semiconductors",
                memory_size="4096 bytes (40 sectors)",
                confidence="high",
                note="MIFARE Classic 4K identified from PC/SC ATR pattern",
            ), "pattern"
        if card_byte == "03":
            return AtrProfile(
                CardTechnology.MIFARE_ULTRALIGHT,
                manufacturer="NXP Semiconductors",
                memory_size="64 bytes (16 pages) for Ultralight; Ultralight C has 192 bytes",
                confidence="high",
                note="MIFARE Ultralight identified from PC/SC ATR pattern",
            ), "pattern"

    text = _printable_runs(atr_hex)
    upper = text.upper()
    if "DESFIRE" in upper:
        return AtrProfile(
            CardTechnology.MIFARE_DESFIRE,
            manufacturer="NXP Semiconductors",
            memory_size="DESFire capacity varies by variant (2K/4K/8K)",
            confidence="medium",
            note="Card family named in the ATR historical bytes",
        ), "text"
    if "ULTRALIGHT" in upper:
        return AtrProfile(
            CardTechnology.MIFARE_ULTRALIGHT,
            manufacturer="NXP Semiconductors",
            memory_size="64/192 bytes depending on variant",
            confidence="medium",
            note="Card family named in the ATR historical bytes",
        ), "text"
    if "CLASSIC" in upper or "MIFARE" in upper:
        return AtrProfile(
            CardTechnology.ISO14443A,
            manufacturer="NXP Semiconductors (likely)",
            confidence="low",
            note="MIFARE named in the ATR, but exact variant is ambiguous",
        ), "text"

    if atr_hex.startswith(_GENERIC_ISO14443A_PREFIX):
        return AtrProfile(
            CardTechnology.ISO14443A,
            confidence="low",
            note="Generic ISO/IEC 14443-A PC/SC ATR; exact card family not identified",
        ), "generic"

    return None, "unknown"


def _printable_runs(atr_hex: str) -> str:
    try:
        raw = bytes.fromhex(atr_hex)
    except ValueError:
        return ""
    runs: list[str] = []
    current: list[str] = []
    for byte in raw:
        if 32 <= byte < 127:
            current.append(chr(byte))
        else:
            if len(current) >= 4:
                runs.append("".join(current))
            current = []
    if len(current) >= 4:
        runs.append("".join(current))
    return " ".join(runs)


def manufacturer_from_uid(uid: bytes | None) -> str | None:
    if not uid:
        return None
    return _MANUFACTURERS.get(uid[0])


def identify_card(
    atr: bytes | None,
    uid: bytes | None,
    protocol: str | None = None,
    reader_name: str | None = None,
) -> CardInfo:
    atr_hex = atr.hex().upper() if atr else ""
    profile, match_kind = _profile_from_atr(atr_hex)

    details: dict[str, str] = {}
    warnings: list[str] = []
    if atr_hex:
        details["ATR"] = atr.hex(" ").upper()
        details["ATR match"] = match_kind
    else:
        warnings.append("The reader did not return an ATR for this card.")
    if protocol:
        details["PC/SC protocol"] = protocol
    if reader_name:
        details["Reader"] = reader_name
    if uid:
        details["UID length"] = f"{len(uid)} bytes"
    else:
        warnings.append(
            "The UID could not be read. Some readers do not implement the standard GET DATA command."
        )

    technology = profile.technology if profile else CardTechnology.UNKNOWN
    confidence = profile.confidence if profile else "low"
    manufacturer = (profile.manufacturer if profile else None) or manufacturer_from_uid(uid)
    memory_size = profile.memory_size if profile else None
    frequency = _frequency_for(technology)

    if profile and profile.note:
        details["Identification"] = profile.note
    if not profile:
        warnings.append(
            "The ATR does not match a known card profile. The card may still be an ISO/IEC 14443 "
            "card, but its family cannot be identified without reader-specific information."
        )

    if uid and len(uid) not in (4, 7, 8, 10):
        warnings.append(f"Unusual UID length ({len(uid)} bytes); treat the identifier with caution.")

    return CardInfo(
        technology=technology,
        uid=uid.hex().upper() if uid else None,
        uid_bytes=uid,
        atr=atr,
        protocol=protocol,
        manufacturer=manufacturer,
        memory_size=memory_size,
        frequency=frequency,
        confidence=confidence,
        readable=bool(uid or atr),
        access_state=DataAccess.READABLE if uid else DataAccess.NOT_ATTEMPTED,
        details=details,
        warnings=warnings,
    )


def _frequency_for(technology: CardTechnology) -> str:
    if technology is CardTechnology.ISO15693:
        return "13.56 MHz (ISO/IEC 15693)"
    if technology in (
        CardTechnology.MIFARE_CLASSIC_1K,
        CardTechnology.MIFARE_CLASSIC_4K,
        CardTechnology.MIFARE_ULTRALIGHT,
        CardTechnology.MIFARE_DESFIRE,
        CardTechnology.ISO14443A,
        CardTechnology.ISO14443B,
        CardTechnology.UNKNOWN,
    ):
        return "13.56 MHz (ISO/IEC 14443), presumed"
    return "Unknown"


def parse_key_hex(text: str) -> bytes | None:
    normalized = normalize_hex(text)
    if not normalized:
        return None
    if len(normalized) != 12:
        raise ValueError(
            "A MIFARE Classic key must be exactly 6 bytes (12 hexadecimal digits), "
            "for example FFFFFFFFFFFF."
        )
    try:
        return bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("The key contains non-hexadecimal characters.") from exc


def memory_summary(memory: list[MemoryBlock]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for block in memory:
        summary[block.access.value] = summary.get(block.access.value, 0) + 1
    return summary


def aggregate_access(memory: list[MemoryBlock]) -> DataAccess:
    if not memory:
        return DataAccess.NOT_ATTEMPTED
    statuses = {block.access for block in memory}
    if DataAccess.READABLE in statuses:
        return DataAccess.READABLE
    if DataAccess.AUTH_REQUIRED in statuses:
        return DataAccess.AUTH_REQUIRED
    if DataAccess.UNREADABLE in statuses:
        return DataAccess.UNREADABLE
    if DataAccess.PROTECTED in statuses:
        return DataAccess.PROTECTED
    if DataAccess.NOT_SUPPORTED in statuses:
        return DataAccess.NOT_SUPPORTED
    return DataAccess.NOT_ATTEMPTED
