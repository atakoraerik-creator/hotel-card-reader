# Hardware Compatibility Report

**Report date:** 2026-10-21  
**Application version:** 0.1.0  
**Verification level:** software-tested with simulations; **no physical reader/encoder was present**

## 1. Environment observed

| Item | Observation |
|---|---|
| OS | Windows 10 Pro 10.0.19045, 64-bit |
| User rights | Standard user (no administrator session) |
| PC/SC library | `winscard.dll` 10.0.19041.1 present |
| Smart Card service | `SCardSvr`, demand start, **stopped** |
| PC/SC readers | None attached |
| USB devices | HP webcam (`04F2:B66A`), Intel Bluetooth (`8087:0029`), Synaptics fingerprint (`06CB:00B7`) |
| Serial ports | Intel AMT SOL (COM3), Bluetooth serial (COM7/COM8) |
| Brassco software/driver/SDK | Not installed; no registry entries; no files found |
| Public Brassco BE-KKYD Pro docs | Not found |

The application correctly reports the stopped service and missing readers instead of fabricating a
successful hardware result.

## 2. Reader compatibility

| Reader/interface | Enumeration | ATR | UID via `FF CA 00 00 00` | MIFARE Classic memory | ISO 15693 | Status |
|---|---|---|---|---|---|---|
| Generic PC/SC contactless | pyscard | Yes | Reader/firmware-dependent | Not guaranteed | Reader-dependent | Supported baseline; hardware-unverified |
| ACS ACR122U | pyscard | Yes | Usually yes | Experimental ACS pseudo-APDU adapter | No | Hardware-unverified |
| ACS ACR1252U | pyscard | Yes | Usually yes | Experimental ACS pseudo-APDU adapter | Yes (reader capability) | Hardware-unverified |
| HID OMNIKEY 5022/5427 | pyscard | Yes | Reader-dependent | Not specifically implemented | Some models | Not tested |
| Brassco BE-KKYD Pro | Unknown | Unknown | Unknown | Unknown | Unknown | **Unverified; vendor adapter required** |
| 125 kHz-only encoder | No | No | No | No | No | Out of scope for PC/SC |

### What "PC/SC compatible" guarantees

PC/SC standardizes reader access, not card-family commands. A reader may:

- return an ATR but not a UID;
- support ISO/IEC 14443 but reject MIFARE authentication commands;
- expose proprietary pseudo-APDUs for MIFARE memory;
- support ISO/IEC 15693 only on specific models/firmware.

The application therefore labels memory access as experimental and reports the actual status word
instead of assuming success.

## 3. Card compatibility

| Card | Identification method | UID | Memory behavior in this app |
|---|---|---|---|
| MIFARE Classic 1K | Known ATR patterns | GET DATA, if supported | Read-only data blocks with authorized key; trailer excluded |
| MIFARE Classic 4K | Known ATR patterns | GET DATA, if supported | Same; 40-sector addressing |
| MIFARE Ultralight | Known ATR patterns | GET DATA, if supported | Not implemented for PC/SC; simulated demo only |
| MIFARE DESFire | Common ATR / ATR text | GET DATA, if supported | Application data not implemented; reports authentication required |
| ISO/IEC 14443 A/B | ATR/protocol | Reader-dependent | No generic memory access |
| ISO/IEC 15693 | Reader-specific | Reader-dependent | Not implemented |
| 125 kHz Temic/T5577 | Not detected by NFC readers | No | Not supported; distinct hardware required |

## 4. Brassco BE-KKYD Pro findings

### Confirmed

- No local installation, driver, service, or SDK.
- No USB device currently attached.
- No public manual or SDK found by search.

### Unconfirmed / must be verified by vendor or test

- Frequency (125 kHz, 13.56 MHz, or dual)
- Interface class (PC/SC/CCID, HID, USB serial, proprietary)
- Supported card families and generations
- Whether it supports third-party read-only commands
- Firmware version and update path
- Whether "Card Error" is a frequency, generation, initialization, or firmware rejection

### Why the new-card "Card Error" is likely hardware-related

If old cards work and new MIFARE Classic 1K cards fail immediately:

1. The encoder may be a **125 kHz** writer and the new cards are **13.56 MHz** MIFARE.
2. The encoder firmware may not support the new cards' **generation or UID length**.
3. The vendor software may require a specific **card-type selection/initialization** for blank stock.
4. The cards may be **MIFARE Plus/DESFire/CPU** cards mislabeled as Classic-compatible.
5. The encoder may have a **faulty antenna/driver** that only affects certain card loads.

Only a documented vendor SDK or a controlled hardware test can distinguish these. This application
does not attempt to bypass any of them.

### Information required for integration

- Product label/photo and exact model string
- USB VID/PID and driver name
- Vendor app version and installation directory
- SDK files, headers, samples, and license terms
- Manual/command reference
- Supported frequency/card list
- A test card and authorization to read it

## 5. Recommended validation procedure

1. Attach a known PC/SC reader (prefer ACR122U or ACR1252U).
2. Run `tools\inspect_system.ps1` and save the report.
3. Run `python -m doorcard.cli --diagnose`.
4. Scan an old working card and a new failing card. Record:
   - ATR
   - UID and UID length
   - detected technology/confidence
   - reader name
5. If the new card is detected as MIFARE Classic 1K, test the encoder with a known genuine NXP
   MIFARE Classic EV1 1K card.
6. Test the encoder with its own vendor software and capture the exact error text.
7. Update this report with actual results. Do not mark a row verified without a test record.

## 6. Test record template

| Test | Date | Reader/encoder | Card | Result | Notes |
|---|---|---|---|---|---|
| Reader enumeration | | | | | |
| Old card UID/ATR | | | | | |
| New card UID/ATR | | | | | |
| MIFARE memory read | | | | | |
| Encoder old card | | | | | |
| Encoder new card | | | | | |
| Known genuine card | | | | | |

## 7. Conclusion

The software layer is complete and tested against simulated responses. Real-hardware compatibility
remains **unverified**. The Brassco device cannot be supported responsibly until its interface and
SDK are known. The "Card Error" symptom should be investigated as a hardware/frequency/card-generation
issue first; no software change can make an incompatible encoder support a card family it does not
support.
