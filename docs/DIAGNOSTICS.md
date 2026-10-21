# Diagnostics Guide

## Running diagnostic mode

```powershell
.\.venv\Scripts\python.exe -m doorcard.cli --diagnose
.\.venv\Scripts\python.exe -m doorcard.cli --list-readers
.\.venv\Scripts\python.exe -m doorcard.cli --scan --timeout 15
```

`--diagnose` prints:

- application/Python/platform versions
- backend availability
- Windows Smart Card service state
- reader list and reader notes
- log file location
- remediation for failures

Add `--scan` to attempt a card read after the environment checks. Add `--verbose` to print every
memory block.

## How to interpret the main states

| State | Meaning | Typical cause |
|---|---|---|
| `No reader available` | PC/SC cannot list any reader | No reader attached, service stopped, driver issue, or another app has exclusive access |
| `No card detected` | Reader works, no card in field | Card not placed, wrong position, wrong frequency, dead card |
| `Card technology is not supported` | Card responded but this path cannot handle it | 125 kHz card, proprietary protocol, reader limitation |
| `Card could not be identified` | ATR/UID returned but family unknown | Reader-specific ATR, proprietary card, incomplete UID |
| `Authentication required` | Data protected by key/application | Normal for MIFARE sectors, DESFire apps, hotel credentials |
| `Memory reading is not supported` | Reader rejected documented read commands | Non-ACS reader/firmware or non-MIFARE card |
| `Vendor reported 'Card Error'` | Firmware-level rejection | Encoder/card incompatibility, frequency mismatch, unsupported generation |

## Diagnostic code reference

| Code | Severity | Meaning | First action |
|---|---|---|---|
| `no_reader` | error | No compatible reader | Connect a PC/SC reader; refresh |
| `reader_not_found` | error | Selected reader disappeared | Refresh/reconnect |
| `pcsc_unavailable` | error | PC/SC subsystem failed | Check winscard/pcscd and service |
| `pcsc_service_stopped` | error | Windows Smart Card service not running | Start `SCardSvr` in Services |
| `no_card` | error | No card in field | Place card flat/centered; try another card |
| `card_removed` | error | Card left field mid-read | Keep card still |
| `card_unsupported` | error | Card family/frequency unsupported | Verify frequency and reader capability |
| `card_not_identified` | warning | ATR/UID unknown | Check reader manual; try another reader |
| `frequency_mismatch_suspected` | error | Likely 125 kHz vs 13.56 MHz mismatch | Use correct-frequency hardware |
| `protocol_mismatch` | error | Reader/card protocol disagreement | Reconnect; check supported protocols |
| `communication_failure` | error | Reader/card stopped responding | Reconnect; close competing apps; try another port |
| `authentication_failed` | error | Key/access condition rejected | Use authorized key or accept protected status |
| `auth_required` | warning | Protected area requires authentication | Only public data can be shown |
| `access_denied` | error | Card refused operation | Data may be read-only/restricted |
| `data_protected` | error | Security configuration blocks access | Do not bypass; use authorized tooling |
| `data_unreadable` | error | Block/file read failed | Re-scan; check block map |
| `uid_unavailable` | warning | Reader lacks GET DATA/UID support | Check reader manual/SDK |
| `atr_unavailable` | warning | Reader does not expose ATR | Try a different reader |
| `memory_read_disabled` | info | Memory read not requested | Enable optional read if authorized |
| `memory_read_unsupported` | error | Reader/card does not accept read commands | Use supported reader/SDK |
| `memory_read_partial` | warning | Some sectors readable, others protected | Review per-block status |
| `invalid_key_format` | error | Key is not 12 hex digits | Enter a 6-byte key or leave blank |
| `vendor_adapter_not_configured` | error | No vendor SDK adapter | Set `DOORCARD_VENDOR_ADAPTER` only with documented SDK |
| `vendor_device_unverified` | warning | Device capabilities unverified | Record model/VID/PID; obtain SDK |
| `card_error_vendor` | error | Vendor firmware "Card Error" | Investigate hardware/card compatibility |
| `sdk_missing` | error | Adapter SDK could not load | Install correct SDK/architecture |
| `stopped` | info | User cancelled | None |
| `internal_error` | error | Unexpected exception | Check log; retry |

## Status word mapping

| SW1 SW2 | Interpretation |
|---|---|
| `63 00` | Authentication/verification failed |
| `69 82` | Security status not satisfied (access denied) |
| `69 85` | Conditions of use not satisfied (often authentication needed) |
| `6A 81` | Function not supported (often UID or memory command unsupported) |
| `6A 82` | File/block not found |
| `6A 86` | Incorrect P1/P2 (protocol/parameter mismatch) |
| `6D 00` | Instruction not supported |
| `6E 00` | Class not supported |
| `6F 00` | Unknown/technical error |

Other status words are reported as communication failures with the raw value.

## The "Card Error" decision tree

```
Card Error on encoder
├─ Do old cards still work? 
│  ├─ Yes → the encoder works for the old card technology
│  │        Compare old vs new frequency and card generation
│  │        If old is 125 kHz and new is MIFARE 13.56 MHz → incompatible hardware
│  │        If both are 13.56 MHz → check UID length, EV1/Plus/clone, initialization, firmware
│  └─ No  → encoder, cable, driver, or firmware problem
├─ Does a known PC/SC reader detect the new card?
│  ├─ No  → card may be 125 kHz, damaged, or not ISO/IEC 14443
│  └─ Yes → record ATR/UID/technology and compare with old card
└─ Does a known genuine NXP MIFARE Classic EV1 1K work on the encoder?
   ├─ Yes → new card stock is likely incompatible
   └─ No  → encoder configuration/firmware/hardware is suspect
```

## Logs

- Location: `logs/doorcard.log.jsonl`
- Rotation: 1 MB, 3 backups
- Format: JSON lines with UTC timestamp, level, logger, message, optional exception
- Structured events: `card_detected`, `no_card_detected`, `scan_result`, and `diagnostic`
- Each diagnostic log includes its code, severity, message, detail, and remediation steps
- Session keys are added to a redaction set only for the duration of a scan. A filter replaces them
  in messages and exception text. Reports never include keys.
- The UI button **Open Log Folder** opens the log directory.

## Safety reminder

Diagnostics explain why data is unavailable. They are not a route to bypass authentication. Only
read cards you own or are authorized to inspect, and do not attempt to clone credentials or defeat
access control.
