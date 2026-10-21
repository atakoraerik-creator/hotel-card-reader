# Development Plan

## 1. Guiding constraints

- Read-only: the application never writes to a card.
- No key recovery, no encryption bypass, no credential cloning.
- No invented vendor commands. Vendor support is added only from a documented SDK.
- Hardware results are never reported as verified unless the hardware was actually tested.
- Simulated cards provide reproducible tests and a UI demo when no reader is attached.

## 2. Architecture

```text
DoorCardReader/
|-- doorcard/
|   |-- models.py             # dataclasses and enums shared by all layers
|   |-- identification.py     # ATR/UID parsing and card classification
|   |-- diagnostics.py        # error classification and remediation text
|   |-- logging_setup.py      # rotating logs, secret redaction
|   |-- export.py             # CSV/JSON report generation
|   |-- service.py            # scan orchestration
|   |-- readers/
|   |   |-- base.py           # ReaderBackend contract + vendor adapter contract
|   |   |-- pcsc.py           # pyscard PC/SC backend
|   |   |-- mifare_pcsc.py    # experimental read-only ACS MIFARE adapter
|   |   |-- simulated.py      # deterministic simulated cards
|   |   `-- vendor.py         # opt-in vendor SDK adapter loader
|   |-- ui/main_window.py     # PySide6 desktop interface
|   |-- app.py                # GUI entry point
|   |-- cli.py                # diagnostic/headless entry point
|   `-- web/                  # FastAPI management interface
|       |-- app.py            # routes, auth, CSRF, rendering
|       |-- models.py         # rooms, guests, cards, users, audit log
|       |-- services.py       # business logic and audit events
|       |-- encoder.py        # read-only encoder status bridge
|       |-- templates/        # Jinja2 pages
|       `-- static/           # CSS and progressive-enhancement JS
|-- docs/                     # assessment, plan, compatibility, diagnostics, deployment
|-- tools/inspect_system.ps1  # hardware/SDK inventory
|-- tests/                    # simulated-card, unit, and web integration tests
|-- requirements.txt
|-- requirements-web.txt
|-- Dockerfile
`-- README.md
```

## 3. Status summary

| Phase | Scope | Status |
|---|---|---|
| 0 | Hardware discovery and assessment | Complete |
| 1 | Core domain and simulated backend | Complete, 62 tests passing |
| 2 | PC/SC backend and optional MIFARE read | Complete in software; hardware-unverified |
| 3 | PySide6 user interface | Complete |
| 4 | Diagnostics, logging, and export | Complete |
| 5 | Web management interface | Complete in simulation; local and deployment docs included |
| 6 | Physical hardware validation | Blocked: no reader, Smart Card service stopped, Brassco SDK unknown |

## 4. Phases

### Phase 0 - Hardware discovery (complete)

- Inspect OS, PC/SC stack, device tree, installed software, and SDKs.
- Record the absence of a connected reader and the unverified Brassco status.
- Produce `docs/HARDWARE_ASSESSMENT.md`.

### Phase 1 - Core domain and simulated backend (complete)

- Define `ReaderInfo`, `CardInfo`, `MemoryBlock`, `Diagnostic`, `ScanResult`.
- Implement ATR/UID identification with confidence levels.
- Implement diagnostic codes, remediation text, and status-word mapping.
- Implement sanitized rotating logs and CSV/JSON export.
- Implement deterministic simulated cards covering supported, protected, and unsupported cases.
- Cover core behavior with unit tests.

### Phase 2 - PC/SC backend (complete in software, hardware-unverified)

- Enumerate readers with pyscard.
- Connect and read ATR; attempt standard `GET DATA` (`FF CA 00 00 00`) for UID.
- Classify the card and clearly mark unavailable/protected data.
- Map pyscard/PC-SC exceptions to actionable diagnostics.
- Optionally read MIFARE Classic data blocks with a user-supplied key, read-only, with
  trailer blocks always excluded.
- Mark reader-specific memory access as experimental and untested unless verified.
- Verify against fake transport tests; real-reader validation remains pending.

### Phase 3 - User interface (complete)

- PySide6 main window with Connect Reader, Scan Card, Stop, Clear Results, Export Report.
- Reader selection and refresh, connection/card status, card information, memory table,
  diagnostics pane.
- Background scanning thread so the UI remains responsive; Stop cancels the wait.
- Simulated-card picker for demos and training.
- Headless UI smoke test and simulated scan validation with a real Qt event loop.

### Phase 4 - Diagnostics and export (complete)

- Diagnostic mode in the CLI (`--diagnose`), reader listing, JSON output.
- Distinguish unsupported card, protocol/frequency mismatch, communication failure,
  reader/service unavailable, authentication required, and protected data.
- Ensure secret keys never enter logs or exports.
- Provide `tools/inspect_system.ps1` for a local hardware/SDK inventory.
- Document diagnostic codes and the encoder "Card Error" decision tree.

### Phase 5 - Web management interface (complete in simulation)

- Add a FastAPI/Jinja2/SQLite management interface for rooms, guests, card records, users, settings,
  activity, and read-only encoder status.
- Protect authenticated routes with server-side sessions, CSRF tokens, scrypt password hashes, login
  throttling, and administrator/receptionist roles.
- Keep card issuance explicitly simulated; expose no card-write, erase, key-loading, or cloning path.
- Provide a responsive hospitality UI with no Node build step.
- Cover authentication, CSRF, role guards, workflows, encoder simulation, settings, and logout with
  integration tests.
- Document local hosting, LAN setup, systemd/Caddy, Docker, HTTPS, and backups in
  `docs/WEB_DEPLOYMENT.md`.

### Phase 6 - Hardware validation (blocked on hardware)

- Connect a PC/SC reader and run reader detection and card reads.
- Test old vs new hotel cards and record ATR/UID/technology.
- Test the Brassco encoder only if a documented SDK is supplied.
- Update `docs/HARDWARE_COMPATIBILITY.md` with actual results; do not claim untested support.

Current blockers:

- No PC/SC reader or encoder is attached.
- The Windows Smart Card service is stopped; PC/SC context creation fails with `0x8010001D`.
- The Brassco BE-KKYD Pro model, USB interface, card support, and SDK are undocumented locally.

## 5. Acceptance criteria

- [x] Application launches without a reader and shows a clear "no reader" diagnostic.
- [x] Simulated scans produce correct card classification, memory status, and diagnostics.
- [x] CSV/JSON exports contain no secret material.
- [x] Stop cancels a scan within one polling interval.
- [x] Tests pass in a clean virtual environment (62 passed).
- [x] Web interface authenticates users, enforces roles/CSRF, and records simulated card workflows.
- [x] Local web startup and deployment guidance are documented.
- [ ] Physical card encoding is implemented and authorized (intentionally out of scope).
- [x] README and compatibility report match the implemented behavior.
- [ ] Real reader detection and card read verified on hardware.
- [ ] Brassco encoder behavior verified against a documented SDK.

