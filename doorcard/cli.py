from __future__ import annotations

import argparse
import logging
import platform
import subprocess
import sys
from pathlib import Path

from . import __version__
from .diagnostics import no_reader
from .export import export_csv, export_json
from .identification import memory_summary, parse_key_hex
from .logging_setup import REDACTOR, get_logger, log_diagnostic, log_scan_result, setup_logging
from .models import ReaderKind, ScanResult
from .readers.base import ReaderBackendError
from .readers.simulated import _CARDS, SimulatedBackend
from .service import build_backend, result_summary

_LOGGER = get_logger("doorcard.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doorcard",
        description=(
            "Read-only RFID/NFC card identification and diagnostics. "
            "Use only on cards you own or are authorized to inspect."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--backend",
        choices=[kind.value for kind in (ReaderKind.PCSC, ReaderKind.SIMULATED, ReaderKind.VENDOR)],
        default=ReaderKind.PCSC.value,
        help="Reader backend (default: pcsc)",
    )
    parser.add_argument("--reader", help="Exact PC/SC or vendor reader name")
    parser.add_argument(
        "--simulate",
        choices=sorted(_CARDS),
        help="Use the simulated backend with this sample card",
    )
    parser.add_argument("--list-readers", action="store_true", help="List available readers")
    parser.add_argument("--diagnose", action="store_true", help="Run environment/reader diagnostics")
    parser.add_argument("--scan", action="store_true", help="Scan a card (default action)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Card wait timeout in seconds")
    parser.add_argument(
        "--key",
        help=(
            "Session-only MIFARE Classic key (12 hex digits). "
            "Never written to logs or reports."
        ),
    )
    parser.add_argument(
        "--read-memory",
        action="store_true",
        help="Attempt read-only MIFARE Classic memory read (experimental, ACS-style readers)",
    )
    parser.add_argument("--json", metavar="PATH", help="Export the scan result as JSON")
    parser.add_argument("--csv", metavar="PATH", help="Export the scan result as CSV")
    parser.add_argument("--log-dir", metavar="PATH", help="Directory for rotating JSONL logs")
    parser.add_argument("--no-console-log", action="store_true", help="Do not log to the console")
    parser.add_argument("--verbose", action="store_true", help="Print all memory blocks and details")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log_path = setup_logging(
        args.log_dir,
        level=logging.DEBUG if args.verbose else logging.INFO,
        console=not args.no_console_log,
    )
    logger = logging.getLogger("doorcard.cli")

    backend_kind = ReaderKind.SIMULATED if args.simulate else ReaderKind(args.backend)
    try:
        backend = build_backend(backend_kind)
    except Exception as exc:
        _LOGGER.exception("backend initialization failed: %s", backend_kind.value)
        print(f"Could not initialize backend: {exc}", file=sys.stderr)
        return 2

    if args.simulate and isinstance(backend, SimulatedBackend):
        backend.select_card(args.simulate)

    if args.diagnose:
        return _diagnose(backend, args, log_path)

    if args.list_readers:
        return _list_readers(backend)

    if not args.scan:
        args.scan = True

    if args.read_memory and not args.key:
        print(
            "Note: no key supplied; protected MIFARE sectors will be reported as "
            "authentication-required.",
            file=sys.stderr,
        )

    key = None
    if args.key:
        try:
            key = parse_key_hex(args.key)
        except ValueError as exc:
            print(f"Invalid key: {exc}", file=sys.stderr)
            return 2
        if key is not None:
            REDACTOR.add_secret(key)

    reader_name = args.reader
    if not reader_name and not args.simulate:
        try:
            readers = backend.list_readers()
        except ReaderBackendError as exc:
            _print_diagnostic(exc.diagnostic)
            return 2
        if not readers:
            _print_diagnostic(no_reader(backend.display_name))
            return 2
        reader_name = readers[0].name
    if not args.simulate:
        try:
            backend.connect(reader_name or "")
        except ReaderBackendError as exc:
            _print_diagnostic(exc.diagnostic)
            return 2

    try:
        result = backend.scan(
            reader_name=reader_name,
            timeout_s=max(0.0, args.timeout),
            key=key,
            read_memory=args.read_memory,
        )
    except ReaderBackendError as exc:
        _print_diagnostic(exc.diagnostic)
        return 2
    except Exception as exc:
        _LOGGER.exception("unexpected scan error")
        print(f"Unexpected scan error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        backend.disconnect()

    log_scan_result(logger, result)
    _print_result(result, verbose=args.verbose)

    try:
        if args.json:
            path = export_json(result, args.json)
            print(f"\nJSON report written to: {path}")
        if args.csv:
            path = export_csv(result, args.csv)
            print(f"CSV report written to: {path}")
    except Exception as exc:
        _LOGGER.exception("report export failed")
        print(f"Could not write report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if not result.card_detected:
        return 1
    return 0 if not result.has_errors else 1


def _list_readers(backend) -> int:
    try:
        readers = backend.list_readers()
    except ReaderBackendError as exc:
        _print_diagnostic(exc.diagnostic)
        return 2
    if not readers:
        _print_diagnostic(no_reader(backend.display_name))
        return 2
    print(f"Readers via {backend.display_name}:")
    for index, reader in enumerate(readers, start=1):
        print(f"  {index}. {reader.name}")
        if reader.vendor:
            print(f"     vendor:    {reader.vendor}")
        if reader.model:
            print(f"     model:     {reader.model}")
        if reader.interface:
            print(f"     interface: {reader.interface}")
        for note in reader.notes:
            print(f"     note:      {note}")
    return 0


def _diagnose(backend, args, log_path: Path) -> int:
    print(f"Universal Electronic Door Card Reader {__version__}")
    print(f"Python:   {sys.version.split()[0]} ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    print(f"Backend:  {backend.display_name}")
    print(f"Log file: {log_path}")

    availability = backend.availability()
    print(f"\nBackend availability: {'AVAILABLE' if availability.available else 'UNAVAILABLE'}")
    print(f"  {availability.message}")
    for diagnostic in availability.diagnostics:
        _print_diagnostic(diagnostic, indent="  ")

    if platform.system() == "Windows" and backend.kind is ReaderKind.PCSC:
        print("\nWindows Smart Card service (SCardSvr):")
        try:
            completed = subprocess.run(
                ["sc.exe", "query", "SCardSvr"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            state = "unknown"
            for line in completed.stdout.splitlines():
                if "STATE" in line:
                    state = line.strip()
                    break
            print(f"  {state}")
        except Exception as exc:
            _LOGGER.warning("could not query Smart Card service: %s", exc)
            print(f"  Could not query service: {exc}")

    print("\nReaders:")
    try:
        readers = backend.list_readers()
    except ReaderBackendError as exc:
        _print_diagnostic(exc.diagnostic, indent="  ")
        return 0
    if not readers:
        _print_diagnostic(no_reader(backend.display_name), indent="  ")
    else:
        for index, reader in enumerate(readers, start=1):
            print(f"  {index}. {reader.name}")
            if reader.vendor:
                print(f"     vendor: {reader.vendor}")
            if reader.interface:
                print(f"     interface: {reader.interface}")
            for note in reader.notes:
                print(f"     note: {note}")

    if args.scan and readers:
        try:
            backend.connect(args.reader or readers[0].name)
            result = backend.scan(
                reader_name=args.reader or readers[0].name,
                timeout_s=max(0.0, args.timeout),
            )
            print()
            _print_result(result, verbose=args.verbose)
        except ReaderBackendError as exc:
            _print_diagnostic(exc.diagnostic)
        finally:
            backend.disconnect()
    return 0


def _print_result(result: ScanResult, *, verbose: bool = False) -> None:
    print("\n=== Scan result ===")
    if result.reader:
        print(f"Reader:  {result.reader.name}")
    print(f"Backend: {result.backend}{' (simulated)' if result.simulated else ''}")
    print(f"Status:  {'CARD DETECTED' if result.card_detected else 'NO CARD'}")
    print(f"Time:    {result.timestamp.isoformat()} ({result.duration_ms} ms)")

    card = result.card
    if card:
        print("\nCard information:")
        print(f"  Technology:  {card.technology.value}")
        print(f"  UID:         {card.uid_display if card.uid else 'Unavailable'}")
        if card.uid:
            print(f"  UID hex:     {card.uid}")
            print(f"  UID length:  {len(card.uid_bytes or b'')} bytes")
        print(f"  ATR:         {card.atr_hex or 'Unavailable'}")
        print(f"  Protocol:    {card.protocol or 'Unavailable'}")
        print(f"  Manufacturer:{(' ' + card.manufacturer) if card.manufacturer else ' Unavailable'}")
        print(f"  Memory size: {card.memory_size or 'Unavailable'}")
        print(f"  Frequency:   {card.frequency or 'Unavailable'}")
        print(f"  Confidence:  {card.confidence}")
        print(f"  Access:      {card.access_state.value}")
        if card.warnings:
            print("  Warnings:")
            for warning in card.warnings:
                print(f"    - {warning}")
        if card.details:
            print("  Details:")
            for key, value in card.details.items():
                print(f"    {key}: {value}")
        if card.memory:
            summary = memory_summary(card.memory)
            print("\nMemory summary:")
            for access, count in sorted(summary.items()):
                print(f"  {access}: {count} block(s)")
            blocks = card.memory if verbose else card.memory[:40]
            print("\nMemory blocks:")
            print("  Sector Block  Data (hex)                         ASCII            Access")
            for block in blocks:
                sector = "-" if block.sector is None else str(block.sector)
                data = block.hex_data or "(not read)"
                ascii_text = block.ascii_data or ""
                print(
                    f"  {sector:>6} {block.block:>5}  {data:<32} {ascii_text:<16} {block.access.value}"
                )
            if not verbose and len(card.memory) > len(blocks):
                print(f"  ... {len(card.memory) - len(blocks)} more block(s); use --verbose to show all")

    if result.diagnostics:
        print("\nDiagnostics:")
        for diagnostic in result.diagnostics:
            _print_diagnostic(diagnostic, indent="  ")

    print(f"\nSummary: {result_summary(result)}")


def _print_diagnostic(diagnostic, indent: str = "") -> None:
    log_diagnostic(_LOGGER, diagnostic, context="cli")
    print(f"{indent}[{diagnostic.severity.value.upper()}] {diagnostic.title}")
    print(f"{indent}  {diagnostic.message}")
    if diagnostic.detail:
        print(f"{indent}  Detail: {diagnostic.detail}")
    for item in diagnostic.remediation:
        print(f"{indent}  - {item}")


if __name__ == "__main__":
    raise SystemExit(main())
