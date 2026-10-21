from __future__ import annotations

from doorcard.models import CardTechnology, DataAccess, DiagnosticCode
from doorcard.readers.mifare_pcsc import MifareClassicMemoryReader

KEY = bytes.fromhex("A0A1A2A3A4A5")


class FakeConnection:
    def __init__(self, *, auth: bool = True, unsupported: bool = False) -> None:
        self.calls: list[list[int]] = []
        self.read_blocks: list[int] = []
        self.last_key: bytes | None = None
        self.auth = auth
        self.unsupported = unsupported

    def transmit(self, apdu: list[int]):
        command = list(apdu)
        self.calls.append(command)
        if command[:5] == [0xFF, 0x82, 0x00, 0x00, 0x06]:
            self.last_key = bytes(command[5:11])
            if self.unsupported:
                return [], 0x6A, 0x81
            return [], 0x90, 0x00
        if command[:7] == [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00]:
            if self.unsupported:
                return [], 0x6A, 0x81
            if not self.auth:
                return [], 0x63, 0x00
            return [], 0x90, 0x00
        if command[:3] == [0xFF, 0xB0, 0x00]:
            block = command[3]
            self.read_blocks.append(block)
            return list(bytes((block + index) % 256 for index in range(16))), 0x90, 0x00
        raise AssertionError(f"Unexpected APDU: {command}")


def test_reads_1k_read_only_and_never_reads_trailers() -> None:
    connection = FakeConnection()
    reader = MifareClassicMemoryReader(connection, "Fake ACS Reader")
    memory, diagnostics = reader.read([KEY], CardTechnology.MIFARE_CLASSIC_1K)

    assert len(memory) == 16 * 4
    assert sum(1 for block in memory if block.access is DataAccess.READABLE) == 16 * 3
    assert sum(1 for block in memory if block.access is DataAccess.PROTECTED) == 16
    assert 3 not in connection.read_blocks
    assert 7 not in connection.read_blocks
    assert 63 not in connection.read_blocks
    assert all(block.data is not None for block in memory if block.access is DataAccess.READABLE)
    assert any(item.code is DiagnosticCode.MEMORY_READ_PARTIAL for item in diagnostics)

    forbidden = (0xD6, 0xA0, 0xC0, 0xC1)
    assert not any(command[0] in forbidden for command in connection.calls)
    assert all(command[0] in (0xFF,) for command in connection.calls)
    assert KEY.hex() not in str([item.to_dict() for item in diagnostics]).lower()


def test_reads_4k_sector_layout() -> None:
    connection = FakeConnection()
    reader = MifareClassicMemoryReader(connection, "Fake ACS Reader")
    memory, _ = reader.read([KEY], CardTechnology.MIFARE_CLASSIC_4K)

    assert len(memory) == 256
    assert any(block.sector == 32 and block.block == 128 for block in memory)
    assert any(block.sector == 39 and block.block == 255 for block in memory)
    assert 143 not in connection.read_blocks
    assert 255 not in connection.read_blocks
    assert 128 in connection.read_blocks


def test_authentication_failure_marks_sectors_protected() -> None:
    connection = FakeConnection(auth=False)
    reader = MifareClassicMemoryReader(connection, "Fake ACS Reader")
    memory, diagnostics = reader.read([KEY], CardTechnology.MIFARE_CLASSIC_1K)

    assert len(memory) == 64
    assert not any(block.access is DataAccess.READABLE for block in memory)
    assert sum(1 for block in memory if block.access is DataAccess.AUTH_REQUIRED) == 48
    assert any(item.code is DiagnosticCode.AUTH_REQUIRED for item in diagnostics)
    assert connection.read_blocks == []


def test_unsupported_reader_marks_memory_not_supported() -> None:
    connection = FakeConnection(unsupported=True)
    reader = MifareClassicMemoryReader(connection, "Fake Reader")
    memory, diagnostics = reader.read([KEY], CardTechnology.MIFARE_CLASSIC_1K)

    assert sum(1 for block in memory if block.access is DataAccess.NOT_SUPPORTED) == 48
    assert any(item.code is DiagnosticCode.MEMORY_READ_UNSUPPORTED for item in diagnostics)


def test_no_key_does_not_attempt_authentication() -> None:
    connection = FakeConnection()
    reader = MifareClassicMemoryReader(connection, "Fake ACS Reader")
    memory, diagnostics = reader.read([], CardTechnology.MIFARE_CLASSIC_1K)

    assert sum(1 for block in memory if block.access is DataAccess.AUTH_REQUIRED) == 48
    assert not any(command[:5] == [0xFF, 0x82, 0x00, 0x00, 0x06] for command in connection.calls)
    assert any(item.code is DiagnosticCode.AUTH_REQUIRED for item in diagnostics)
