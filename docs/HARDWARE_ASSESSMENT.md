# Hardware Compatibility Assessment

**Assessment date:** 2026-10-21  
**Machine:** Windows 10 Pro 10.0.19045, 64-bit, non-administrator session  
**Project:** Universal Electronic Door Card Reader

## 1. Executive summary

This machine currently has **no RFID/NFC reader or card encoder attached**. The Windows PC/SC
stack is present, but the Smart Card service is stopped (it is configured for demand start) and
there are no smart-card reader devices in the device tree.

There is also **no Brassco software, driver, SDK, or documentation installed locally**, and no
public documentation for a "Brassco BE-KKYD Pro" encoder could be located. Its interface
(PC/SC, CCID, USB HID, USB serial, or proprietary), frequency, and supported card list therefore
**cannot be verified**. The application must not claim support for that device until it has been
tested.

The existing Python installation was unusable (an incomplete Python 3.14 directory with no
`python.exe`). A working Python 3.13.7 was installed per-user into
`%LOCALAPPDATA%\Programs\Python\Python313`, and a project virtual environment was created at
`.venv` with PySide6, pyscard, and pytest.

## 2. What was inspected

| Check | Result |
|---|---|
| Operating system | Windows 10 Pro, version 10.0.19045, 64-bit |
| Administrator rights | No (per-user installation only) |
| `winscard.dll` | Present, version 10.0.19041.1 |
| Smart Card service (`SCardSvr`) | Present, `DEMAND_START`, currently `STOPPED` |
| PC/SC reader class devices | None (`Get-PnpDevice -Class SmartCardReader` returned no devices) |
| USB devices present | HP webcam (`VID_04F2`), Intel Bluetooth (`VID_8087`), Synaptics fingerprint sensor (`VID_06CB`) |
| Serial ports | Intel AMT SOL (COM3), Bluetooth serial (COM7/COM8) — no USB-serial encoder |
| Installed programs matching Brassco/card/reader/PCSC | None |
| Registry search for "Brassco" | 0 matches |
| Brassco/SDK files in Downloads/Desktop/Documents | None found |
| Public Brassco BE-KKYD Pro documentation | Not found by web search |
| Python (pre-existing) | Broken partial Python 3.14 install, no `python.exe` |
| Python (project) | 3.13.7 per-user, `.venv` working |
| PySide6 / pyscard / pytest | 6.12.0 / 2.3.1 / 9.1.1 installed in `.venv` |

> The lack of a device is not a software defect. Reader-specific tests cannot be honestly
> reported as passed until the hardware is connected.

## 3. Brassco BE-KKYD Pro assessment

### 3.1 What is known

- The model name was supplied by the user.
- No official manual, SDK, driver, or product page was found.
- No local driver or vendor application is installed.
- No device is currently connected, so its USB descriptors and interface class cannot be read.

### 3.2 What is not known

- Operating frequency (125 kHz vs 13.56 MHz vs dual-frequency)
- Whether it is PC/SC/CCID compliant or uses a vendor HID/serial protocol
- Supported card families and generations
- Whether it can read MIFARE Classic memory or only encode vendor-specific card layouts
- Firmware version and whether a firmware update is available
- Whether the vendor SDK permits third-party read-only access

**Conclusion:** the Brassco device is currently classified as **unverified / vendor-specific**.
A vendor adapter interface is included in the project, but no undocumented commands are invented
and no support claim is made.

### 3.3 Investigating the "old cards work, new MIFARE Classic 1K cards show Card Error" problem

A software application cannot make incompatible hardware compatible. The most useful first step is
to determine whether the encoder and the new cards are even in the same technology family.

Most likely causes, in order of likelihood:

1. **Frequency mismatch.** Many hotel encoders are 125 kHz writers for Temic/T5577-style cards.
   A 13.56 MHz MIFARE Classic 1K card will produce an immediate "Card Error" on such a writer.
   If the old working cards are 125 kHz, this is the leading explanation.
2. **Card generation / UID variant.** Some older encoders only handle 4-byte-UID MIFARE Classic
   S50 cards. New stock may be MIFARE Classic EV1 with a 7-byte UID, a MIFARE Plus card in
   Classic-compatible mode, or a clone IC with different timing. The encoder firmware may reject
   these even though they are "MIFARE Classic 1K" on the label.
3. **Unsupported card type in the vendor software.** The encoder software may have a card-type
   setting (e.g. T5577, S50, S70, CPU) that does not match the new stock.
4. **Cards are not initialized for that hotel system.** Some systems require blank cards to be
   initialized/format-tagged before issuing. A totally blank card can be reported as an error.
5. **Card defect or locked/protected sectors.** Less common for new cards, but possible with
   low-quality stock or cards that were pre-personalized.
6. **Driver, cable, or RF problem.** Wrong COM port, loose cable, card not centered, metal desk,
   or a failing encoder antenna.

Recommended investigation sequence:

1. Connect the encoder and run `tools\inspect_system.ps1` to record its VID/PID, driver, COM port,
   and interface class.
2. Use a known PC/SC 13.56 MHz reader (for example an ACS ACR122U or ACR1252U) and this
   application to read both an old working card and a new card. Compare:
   - ATR
   - UID length and value
   - detected technology
   - whether the card responds at 13.56 MHz at all
3. Check the encoder label/manual and vendor software for the supported frequency and card list.
4. Test a known genuine NXP MIFARE Classic EV1 1K card with the encoder. If it works, the new
   stock is likely incompatible; if it also fails, the encoder configuration/firmware is suspect.
5. Record the exact vendor error text and any vendor log output, then contact the vendor with the
   model, VID/PID, firmware version, card type, ATR, UID length, and ATQA/SAK if available.
6. Do not attempt to bypass authentication, clone credentials, or defeat hotel access controls.

## 4. Reader compatibility matrix

| Reader / interface | Enumeration | ATR / UID | MIFARE Classic memory | ISO 15693 | Notes |
|---|---|---|---|---|---|
| Generic PC/SC contactless reader | Yes, via pyscard | ATR yes; UID via `FF CA 00 00 00` if firmware supports it | Reader-dependent; not guaranteed | Reader-dependent | Baseline supported path |
| ACS ACR122U (PC/SC) | Yes | Yes | Experimental read-only adapter, unverified here | No | ISO 14443 A/B, MIFARE, DESFire APDUs |
| ACS ACR1252U (PC/SC) | Yes | Yes | Experimental read-only adapter, unverified here | Yes | Better choice if ISO 15693 is needed |
| HID OMNIKEY 5022/5427 | Yes | Yes | Reader/firmware-dependent | Some models | Not specifically tested |
| Brassco BE-KKYD Pro | Unverified | Unverified | Unverified | Unverified | No SDK/docs found; vendor adapter required |
| 125 kHz-only encoder | No (not PC/SC NFC) | No | No | No | Cannot read 13.56 MHz MIFARE |

## 5. Card compatibility matrix

| Card family | Identification | UID | Public memory read | Limitations |
|---|---|---|---|---|
| MIFARE Classic 1K | ATR-based, high confidence for known ATRs | Yes, when reader supports GET DATA | Read-only, only with a key you are authorized to use; experimental adapter | Trailer blocks are never read; no key recovery; sector keys required |
| MIFARE Classic 4K | ATR-based | Yes | Same as 1K | 4K sector layout handled by the experimental adapter |
| MIFARE Ultralight | ATR-based | Yes | Not implemented for generic PC/SC | Simulated data only; memory access is reader/SDK-specific |
| MIFARE DESFire | ATR/technology name when available | Yes | Not implemented | Application selection/authentication required |
| ISO/IEC 14443 Type A/B | ATR/protocol | Reader-dependent | No | No generic memory access |
| ISO/IEC 15693 | Reader-dependent | Reader-dependent | No | Requires an ISO 15693-capable reader such as ACR1252U |
| 125 kHz Temic/T5577 | Not supported by PC/SC 13.56 MHz readers | No | No | Needs a 125 kHz reader/writer, not an NFC PC/SC reader |

## 6. Required information before Brassco integration

To build a verified Brassco adapter, the following is needed:

- Exact product label and model number
- USB VID/PID and Windows device class/driver name
- Vendor application version and installation directory
- Vendor SDK (headers, DLLs, sample code) and its license terms
- Manual or command reference
- Supported frequency and card list
- A test card and permission to read it
- Confirmation that the SDK is intended for third-party read-only use

Until then, the app exposes a documented vendor-adapter extension point and reports
"vendor adapter not configured" rather than guessing.
