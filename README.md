# Universal Electronic Door Card Reader

A read-only desktop application for identifying electronic hotel/RFID door cards with a
PC/SC-compatible reader. It reads public identification data, attempts authorized MIFARE Classic
memory reads where the hardware and a supplied key permit, explains what cannot be read, and
exports a report.

> **Current verification status**
>
> - 62 automated tests pass, using simulated cards, a fake MIFARE transport, and FastAPI test
>   clients. The web interface is simulated for card issuance; no physical card is written.
> - **No physical reader was attached while this project was built.** Real-hardware tests must be
>   performed by the user and are not claimed here.
> - The **Brassco BE-KKYD Pro is unverified**. No vendor SDK, driver, manual, or public command
>   reference was found locally or online. The app does not guess vendor commands.
> - PC/SC is present on the development machine, but the Windows Smart Card service was stopped and
>   no readers were connected.

## Safety and scope

Use this software only on cards you own or are explicitly authorized to inspect.

The application is **read-only**:

- It never writes to a card.
- It never recovers, brute-forces, or extracts authentication keys.
- It never reads sector trailer blocks (where MIFARE keys and access bits live).
- It never clones credentials or attempts to defeat hotel access control.
- It never stores a key in logs, reports, or configuration. A key entered in the UI is held in
  memory only for that scan.

Some card data is protected by design. A UID is not the same as the hotel credential, and many
hotel systems use proprietary or encrypted data that this application cannot and should not decode.

## Features

- Automatic reader enumeration through PC/SC (pyscard).
- Card detection with configurable wait timeout and optional auto-scan.
- ATR/UID reading, card-family identification, confidence level, and protocol display.
- Clear status for readable, authentication-required, protected, unreadable, and unsupported data.
- Read-only MIFARE Classic 1K/4K memory adapter using documented ACS-style pseudo-APDUs
  (experimental, hardware-unverified).
- Hexadecimal and ASCII memory view.
- Diagnostic codes with specific remediation steps.
- Rotating JSONL logs with secret redaction.
- CSV and JSON report export.
- Deterministic simulated reader/cards for training, demos, and tests.
- Vendor-SDK adapter extension point (no undocumented commands included).
- Optional FastAPI web interface for rooms, guests, simulated key-card records, audit history, team
  access, hotel settings, and read-only encoder status.
- Server-rendered responsive UI with authenticated sessions, CSRF protection, role-based access, and
  scrypt password hashing. No Node.js build is required.

## Supported cards and limitations

| Card family | Identification | UID | Public memory read | Limitation |
|---|---|---|---|---|
| MIFARE Classic 1K | Yes, ATR-based | Yes, if reader supports GET DATA | Experimental, read-only, needs an authorized key | Sector keys required; trailers never read |
| MIFARE Classic 4K | Yes, ATR-based | Yes | Experimental, read-only | Same as 1K; 40-sector layout handled |
| MIFARE Ultralight | Yes, ATR-based | Yes | Not implemented for PC/SC | Simulated page dump only |
| MIFARE DESFire | ATR/common profile | Yes | Not implemented | Applications require authentication |
| ISO/IEC 14443 Type A/B | Reader/ATR-dependent | Reader-dependent | No generic access | Card family may remain unidentified |
| ISO/IEC 15693 | Reader-dependent | Reader-dependent | Not implemented | Needs an ISO 15693-capable reader (e.g. ACR1252U) |
| 125 kHz Temic/T5577 | Not supported by 13.56 MHz PC/SC readers | No | No | Different frequency and hardware required |

**Not supported by this version:** reading hotel lock credential payloads, DESFire application
files, Ultralight pages through generic PC/SC, encrypted/proprietary card systems, and any form of
writing.

## Hardware

Recommended PC/SC readers:

- **ACS ACR122U** — ISO/IEC 14443 A/B, MIFARE, DESFire APDUs; no ISO 15693.
- **ACS ACR1252U** — adds ISO/IEC 15693 and NFC features.
- Other CCID/PC/SC contactless readers may work for ATR/UID; memory commands are reader-dependent.

The Brassco BE-KKYD Pro must be treated as **vendor-specific and unverified** until its interface
and SDK are documented and tested. See [docs/HARDWARE_ASSESSMENT.md](docs/HARDWARE_ASSESSMENT.md)
and [docs/HARDWARE_COMPATIBILITY.md](docs/HARDWARE_COMPATIBILITY.md). For troubleshooting, see
[docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md).

## Installation

Tested with Python 3.13 on Windows 10. Python 3.11+ is required.

The machine used for development had a broken Windows Store Python alias and an incomplete Python
3.14 directory. A working Python 3.13.7 was installed per-user. If `python` opens the Store or
hangs, use the full path to a real interpreter.

```powershell
# from the project directory
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For the web interface:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
```

For development/tests (desktop and web):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

On Linux/macOS, install the PC/SC runtime (`pcscd`, `libpcsclite`) with your package manager. On
Windows, `winscard.dll` is part of the OS. A CCID reader normally needs no separate driver; some
vendor readers require their own driver.

## Run the desktop application

```powershell
.\.venv\Scripts\python.exe -m doorcard
```

Basic workflow:

1. Connect the reader, then click **Connect Reader** (or **Refresh Readers** first).
2. Click **Scan Card** and place the card on the reader.
3. Review card information, memory blocks, and diagnostics.
4. Click **Export Report** to save CSV or JSON.
5. **Stop** cancels a wait/scan; **Clear Results** resets the display.

No hardware? Choose **Simulated reader (demo)** in the Backend box, select a sample card, connect,
and scan. This exercises the same UI and report paths without claiming hardware support.

## Run the web interface locally

The web app is an additional interface, not a replacement for the desktop reader. Card issuance is
a database simulation; it does not write a physical credential.

```powershell
Copy-Item .env.example .env
# Put a generated value in .env as DOORCARD_WEB_SECRET
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -m doorcard.web
```

Open `http://127.0.0.1:8000`.

Local demo accounts:

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@horizon.test` | `Admin!23456` |
| Receptionist | `reception@horizon.test` | `Reception!23456` |

Set `DOORCARD_SEED_DEMO=false` and change or remove demo users before non-local use. The SQLite
database is created at `data/doorcard-web.db`. See [docs/WEB_DEPLOYMENT.md](docs/WEB_DEPLOYMENT.md)
for LAN, systemd, Caddy, Docker, HTTPS, and backup guidance.

The web bridge supports simulated, PC/SC, and documented vendor adapters for **read-only status and
detection**. It has no card-write, erase, key-loading, or cloning endpoint.

### Optional MIFARE memory read

Enable **Attempt read-only MIFARE Classic memory read** and optionally enter a 6-byte key
(12 hex digits) that you are authorized to use. The command sequence is documented for ACS-style
readers and is **experimental**. It loads the key into the reader, authenticates, and reads data
blocks only. It never reads sector trailers and never writes. If the reader does not implement these
commands, the app reports "Memory reading is not supported" and still shows the UID/ATR.

## Diagnostic CLI

```powershell
# Environment, service, and reader diagnostics
.\.venv\Scripts\python.exe -m doorcard.cli --diagnose

# List readers
.\.venv\Scripts\python.exe -m doorcard.cli --list-readers

# Scan with the first reader
.\.venv\Scripts\python.exe -m doorcard.cli --scan --timeout 15

# Scan a specific reader
.\.venv\Scripts\python.exe -m doorcard.cli --scan --reader "ACS ACR122 0" --timeout 15

# Simulated scan and report
.\.venv\Scripts\python.exe -m doorcard.cli --simulate mifare_classic_1k --scan --json report.json

# Simulated scan with CSV
.\.venv\Scripts\python.exe -m doorcard.cli --simulate mifare_desfire --scan --csv report.csv
```

Scan exit codes: `0` card detected without errors, `1` no card/errors, `2` configuration or reader
failure. `--diagnose` returns `0` when the diagnostic run completes, even if it reports a problem.

## The "Card Error" problem with old vs. new cards

A software application cannot overcome incompatible reader/encoder hardware. If old hotel cards work
but new MIFARE Classic 1K cards immediately show "Card Error":

1. **Check frequency first.** Many hotel encoders are 125 kHz writers for Temic/T5577 cards. A
   13.56 MHz MIFARE Classic card will fail instantly on such a writer. Old cards working is
   consistent with a 125 kHz system.
2. **Read both cards with a known 13.56 MHz PC/SC reader** using this app. Compare ATR, UID length,
   and detected technology. If the new card is not detected at all, it may not be a 13.56 MHz
   ISO/IEC 14443 card or the reader may be incompatible.
3. **Check card generation and UID length.** Some encoders only support 4-byte-UID MIFARE Classic
   S50. New stock may be MIFARE Classic EV1 with a 7-byte UID, MIFARE Plus in Classic-compatible
   mode, or a clone IC with different timing.
4. **Check the vendor software's card-type setting** (e.g. T5577 vs S50 vs S70 vs CPU) and whether
   blank cards must be initialized for that hotel system first.
5. **Test a known genuine NXP MIFARE Classic EV1 1K card.** If it works, the new stock is likely
   incompatible. If it also fails, the encoder configuration, firmware, cable, or RF path is suspect.
6. **Contact the vendor** with the exact model, USB VID/PID, driver, firmware, vendor software
   version, card type, ATR, UID length, and the exact error text.

Do not attempt to bypass authentication or clone credentials. See
[docs/HARDWARE_ASSESSMENT.md](docs/HARDWARE_ASSESSMENT.md) for the full investigation.

## Logs and privacy

Logs are written to `logs/doorcard.log.jsonl` (rotating, 1 MB × 3). Each line is JSON with a UTC
timestamp, level, logger, and message. Structured events include `card_detected`,
`no_card_detected`, `scan_result`, and `diagnostic` records with code, message, detail, and
remediation. A redaction filter removes known session keys from messages and exception text.
Reports never contain keys. Use **Open Log Folder** in the UI.

## Vendor SDK adapter

If you obtain a documented SDK and permission for third-party read-only access, set:

```powershell
$env:DOORCARD_VENDOR_ADAPTER = "my_vendor_adapter:create_adapter"
.\.venv\Scripts\python.exe -m doorcard
```

The factory must return an object implementing `doorcard.readers.base.VendorAdapter`. The app does
not include any vendor commands; the adapter owns them. Without a documented SDK, the app reports
"Vendor adapter not configured" rather than guessing.

## Project layout

```
doorcard/
  models.py             Shared dataclasses/enums
  identification.py     ATR/UID parsing and card classification
  diagnostics.py        Diagnostic codes and remediation
  logging_setup.py      Rotating logs and secret redaction
  export.py             CSV/JSON reports
  service.py            Backend factory
  readers/
    base.py             Backend and vendor adapter contracts
    pcsc.py             PC/SC backend (pyscard)
    mifare_pcsc.py      Read-only MIFARE Classic adapter
    simulated.py        Deterministic simulated cards
    vendor.py           Opt-in vendor adapter loader
  ui/main_window.py     PySide6 desktop UI
  cli.py                Diagnostic/headless CLI
  web/
    app.py              FastAPI routes, authentication, CSRF, rendering
    models.py           Users, rooms, guests, card records, audit log, settings
    services.py         Hotel operations and audit helpers
    encoder.py          Read-only encoder status bridge
    templates/          Jinja2 page templates
    static/             Responsive CSS and progressive-enhancement JS
tests/                  Simulated-card, unit, and web integration tests
docs/                   Assessment, plan, compatibility, diagnostics, deployment
tools/inspect_system.ps1
Dockerfile
docker-compose.yml
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite covers identification, diagnostics, secret redaction, CSV/JSON export, simulated cards,
read-only MIFARE APDU behavior (with a fake transport), CLI paths, a headless UI smoke test, and web
authentication, CSRF, role guards, room/guest/card workflows, encoder simulation, settings, and
logout.

## Known gaps / next steps

- Verify PC/SC detection and UID reads with a physical ACR122U or ACR1252U.
- Verify the experimental MIFARE memory adapter against a real reader and known card.
- Add ISO 15693 and Ultralight memory support only after verifying the reader API.
- Add a DESFire application/file reader only if a documented, authorized workflow is available.
- Integrate Brassco only after obtaining its SDK/manual and confirming read-only third-party access.
- Add physical card encoding only after a documented, authorized vendor API and hardware test plan
  are available. It is deliberately not part of this version.

