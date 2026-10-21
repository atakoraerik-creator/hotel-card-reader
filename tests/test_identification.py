from __future__ import annotations

import pytest

from doorcard.identification import (
    aggregate_access,
    hex_to_bytes,
    identify_card,
    manufacturer_from_uid,
    memory_summary,
    parse_key_hex,
)
from doorcard.models import CardTechnology, DataAccess, MemoryBlock

CLASSIC_1K_ATR = bytes.fromhex("3B8F8001804F0CA000000306030001000000006A")
CLASSIC_4K_ATR = bytes.fromhex("3B8F8001804F0CA000000306030002000000006B")
ULTRALIGHT_ATR = bytes.fromhex("3B8F8001804F0CA0000003060300030000000068")


def test_identifies_mifare_classic_1k_from_atr() -> None:
    card = identify_card(CLASSIC_1K_ATR, bytes.fromhex("04A1B2C3"), protocol="T=1")
    assert card.technology is CardTechnology.MIFARE_CLASSIC_1K
    assert card.manufacturer.startswith("NXP")
    assert card.uid == "04A1B2C3"
    assert card.uid_display == "04:A1:B2:C3"
    assert card.memory_size is not None
    assert "1024" in card.memory_size
    assert card.confidence == "high"
    assert card.readable is True
    assert card.access_state is DataAccess.READABLE
    assert card.protocol == "T=1"


def test_identifies_classic_4k_and_ultralight() -> None:
    classic_4k = identify_card(CLASSIC_4K_ATR, bytes.fromhex("04B1C2D3"))
    ultralight = identify_card(ULTRALIGHT_ATR, bytes.fromhex("04C1D2E3"))
    assert classic_4k.technology is CardTechnology.MIFARE_CLASSIC_4K
    assert "4096" in (classic_4k.memory_size or "")
    assert ultralight.technology is CardTechnology.MIFARE_ULTRALIGHT


def test_atr_pattern_identifies_variant() -> None:
    atr = bytes.fromhex("3B8F8001804F0CA00000030603000100000000AA")
    card = identify_card(atr, None)
    assert card.technology is CardTechnology.MIFARE_CLASSIC_1K
    assert card.confidence == "high"


def test_unknown_atr_is_marked_with_warning() -> None:
    card = identify_card(bytes.fromhex("3B00112233"), bytes.fromhex("01020304"))
    assert card.technology is CardTechnology.UNKNOWN
    assert card.confidence == "low"
    assert any("does not match" in warning for warning in card.warnings)


def test_missing_atr_and_uid_are_reported() -> None:
    card = identify_card(None, None)
    assert card.technology is CardTechnology.UNKNOWN
    assert card.readable is False
    assert any("ATR" in warning for warning in card.warnings)
    assert any("UID" in warning for warning in card.warnings)


def test_uid_prefix_manufacturer() -> None:
    assert manufacturer_from_uid(bytes.fromhex("04A1B2C3")).startswith("NXP")
    assert manufacturer_from_uid(bytes.fromhex("99A1B2C3")) is None
    assert manufacturer_from_uid(None) is None


def test_parse_key_hex_accepts_spaces_and_rejects_bad_lengths() -> None:
    assert parse_key_hex("FF FF FF FF FF FF") == b"\xff" * 6
    assert parse_key_hex("") is None
    with pytest.raises(ValueError):
        parse_key_hex("FFFF")
    with pytest.raises(ValueError):
        parse_key_hex("ZZZZZZZZZZZZ")


def test_hex_to_bytes() -> None:
    assert hex_to_bytes("04:AA-BB") == bytes.fromhex("04AABB")
    with pytest.raises(ValueError):
        hex_to_bytes("ABC")


def test_memory_summary_and_aggregate() -> None:
    memory = [
        MemoryBlock(block=0, address=0, data=b"data", access=DataAccess.READABLE, sector=0),
        MemoryBlock(block=1, address=1, data=None, access=DataAccess.AUTH_REQUIRED, sector=0),
        MemoryBlock(block=2, address=2, data=None, access=DataAccess.PROTECTED, sector=0),
    ]
    summary = memory_summary(memory)
    assert summary[DataAccess.READABLE.value] == 1
    assert summary[DataAccess.AUTH_REQUIRED.value] == 1
    assert aggregate_access(memory) is DataAccess.READABLE
    assert aggregate_access([]) is DataAccess.NOT_ATTEMPTED
