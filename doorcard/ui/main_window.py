from __future__ import annotations

import html
import logging
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import diagnostics as diag
from ..export import export_auto
from ..identification import memory_summary, parse_key_hex
from ..logging_setup import REDACTOR, get_logger, log_diagnostic, log_scan_result
from ..models import (
    ConnectionState,
    DataAccess,
    Diagnostic,
    DiagnosticCode,
    MemoryBlock,
    ReaderKind,
    ScanResult,
    Severity,
    utc_timestamp,
)
from ..readers.base import ReaderBackend, ReaderBackendError
from ..readers.simulated import SimulatedBackend
from ..service import build_backend

_COLORS = {
    Severity.INFO: "#1f6feb",
    Severity.WARNING: "#9a6700",
    Severity.ERROR: "#cf222e",
}

_ACCESS_COLORS = {
    DataAccess.READABLE: "#dafbe1",
    DataAccess.AUTH_REQUIRED: "#fff8c5",
    DataAccess.PROTECTED: "#f0f0f0",
    DataAccess.UNREADABLE: "#ffebe9",
    DataAccess.NOT_SUPPORTED: "#f0f0f0",
    DataAccess.UNAVAILABLE: "#ffebe9",
    DataAccess.NOT_ATTEMPTED: "#ffffff",
}


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        backend: ReaderBackend,
        reader_name: str | None,
        timeout_s: float,
        key: bytes | None,
        read_memory: bool,
        cancel: threading.Event,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._reader_name = reader_name
        self._timeout_s = timeout_s
        self._key = key
        self._read_memory = read_memory
        self._cancel = cancel

    def run(self) -> None:
        try:
            result = self._backend.scan(
                reader_name=self._reader_name,
                timeout_s=self._timeout_s,
                key=self._key,
                read_memory=self._read_memory,
                cancel=self._cancel,
            )
        except ReaderBackendError as exc:
            self.failed.emit(exc.diagnostic)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(diag.from_exception(exc, context="GUI scan"))
        else:
            self.completed.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Universal Electronic Door Card Reader")
        self.resize(1280, 940)
        self.setMinimumSize(1000, 720)

        self._logger = get_logger("doorcard.ui")
        self._backend: ReaderBackend = build_backend(ReaderKind.PCSC)
        self._backend_kind = ReaderKind.PCSC
        self._worker: ScanWorker | None = None
        self._cancel = threading.Event()
        self._active_key: bytes | None = None
        self._current_result: ScanResult | None = None
        self._last_fingerprint: tuple[str, str, str] | None = None
        self._last_auto_message: str | None = None
        self._connected = False

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(3000)
        self._auto_timer.timeout.connect(self._auto_scan_tick)

        self._build_ui()
        self._apply_styles()
        self._populate_simulated_cards()
        self._on_backend_changed()
        self._set_connection_state(ConnectionState.DISCONNECTED, "Not connected")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(10)

        title = QLabel(
            "<h1 style='margin:0'>Universal Electronic Door Card Reader</h1>"
            "<div style='color:#57606a;margin-top:2px'>Read-only RFID/NFC identification, "
            "memory inspection, diagnostics, and reporting.</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(title)

        root.addWidget(self._build_reader_group())
        root.addWidget(self._build_options_group())

        actions = QHBoxLayout()
        self._scan_btn = QPushButton("Scan Card")
        self._scan_btn.setObjectName("primaryButton")
        self._scan_btn.setToolTip("Read the card currently on the reader (F5)")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._clear_btn = QPushButton("Clear Results")
        self._export_btn = QPushButton("Export Report")
        self._export_btn.setEnabled(False)
        self._auto_check = QCheckBox("Auto-scan")
        self._auto_check.setToolTip("Poll the reader every 3 seconds while connected")
        actions.addWidget(self._scan_btn)
        actions.addWidget(self._stop_btn)
        actions.addWidget(self._clear_btn)
        actions.addWidget(self._export_btn)
        actions.addSpacing(12)
        actions.addWidget(self._auto_check)
        actions.addStretch(1)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(150)
        self._progress.setVisible(False)
        actions.addWidget(self._progress)
        root.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_card_group())
        splitter.addWidget(self._build_memory_group())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 760])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_diagnostics_group())

        disclaimer = QLabel(
            "Read-only tool. Never writes to cards, recovers keys, clones credentials, or defeats "
            "access control. Use only on cards you own or are explicitly authorized to inspect."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "color:#57606a; background:#f6f8fa; border:1px solid #d0d7de; "
            "border-radius:6px; padding:6px 10px;"
        )
        root.addWidget(disclaimer)

        self._scan_btn.clicked.connect(self._manual_scan)
        self._stop_btn.clicked.connect(self._stop_scan)
        self._clear_btn.clicked.connect(self._clear_results)
        self._export_btn.clicked.connect(self._export_report)
        self._auto_check.toggled.connect(self._toggle_auto)
        self._refresh_btn.clicked.connect(self._refresh_readers)
        self._connect_btn.clicked.connect(self._connect_reader)
        self._backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._reader_combo.currentIndexChanged.connect(self._on_reader_selected)
        self._sim_combo.currentIndexChanged.connect(self._on_sim_card_changed)
        self._key_show.toggled.connect(self._toggle_key_visibility)

    def _build_reader_group(self) -> QGroupBox:
        group = QGroupBox("Reader")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self._backend_combo = QComboBox()
        for kind in (ReaderKind.PCSC, ReaderKind.SIMULATED, ReaderKind.VENDOR):
            self._backend_combo.addItem(kind.label, kind.value)
        self._backend_combo.setMinimumWidth(190)

        self._reader_combo = QComboBox()
        self._reader_combo.setMinimumWidth(320)
        self._refresh_btn = QPushButton("Refresh Readers")
        self._connect_btn = QPushButton("Connect Reader")
        self._connection_status = QLabel("Not connected")
        self._connection_status.setObjectName("statusNeutral")

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 60)
        self._timeout_spin.setValue(10)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setToolTip("How long a manual scan waits for a card")

        grid.addWidget(QLabel("Backend:"), 0, 0)
        grid.addWidget(self._backend_combo, 0, 1)
        grid.addWidget(QLabel("Reader:"), 0, 2)
        grid.addWidget(self._reader_combo, 0, 3)
        grid.addWidget(self._refresh_btn, 0, 4)
        grid.addWidget(QLabel("Status:"), 1, 0)
        grid.addWidget(self._connection_status, 1, 1, 1, 2)
        grid.addWidget(QLabel("Wait timeout:"), 1, 3)
        grid.addWidget(self._timeout_spin, 1, 4, alignment=Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._connect_btn, 0, 5)

        self._sim_label = QLabel("Simulated card:")
        self._sim_combo = QComboBox()
        self._sim_combo.setMinimumWidth(360)
        self._sim_desc = QLabel("")
        self._sim_desc.setWordWrap(True)
        self._sim_desc.setStyleSheet("color:#57606a;")
        grid.addWidget(self._sim_label, 2, 0)
        grid.addWidget(self._sim_combo, 2, 1, 1, 4)
        grid.addWidget(self._sim_desc, 3, 1, 1, 5)

        self._reader_detail = QLabel("")
        self._reader_detail.setWordWrap(True)
        self._reader_detail.setStyleSheet("color:#57606a;")
        grid.addWidget(self._reader_detail, 4, 0, 1, 6)
        grid.setColumnStretch(3, 1)
        return group

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("Read options")
        layout = QHBoxLayout(group)
        layout.setSpacing(10)

        self._read_memory_check = QCheckBox(
            "Attempt read-only MIFARE Classic memory read (experimental)"
        )
        self._read_memory_check.setToolTip(
            "Uses documented ACS-style pseudo-APDUs. Never reads sector trailers or writes data."
        )
        self._read_memory_check.setChecked(False)

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("Optional session key (12 hex digits)")
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setMaximumWidth(260)
        self._key_edit.setToolTip(
            "MIFARE Classic 6-byte key. Kept in memory for the scan only; never logged or exported."
        )
        self._key_show = QCheckBox("Show")
        key_note = QLabel("Session-only; never logged or exported.")
        key_note.setStyleSheet("color:#57606a;")

        layout.addWidget(self._read_memory_check)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Key:"))
        layout.addWidget(self._key_edit)
        layout.addWidget(self._key_show)
        layout.addWidget(key_note)
        layout.addStretch(1)
        return group

    def _build_card_group(self) -> QGroupBox:
        group = QGroupBox("Card information")
        layout = QVBoxLayout(group)
        self._card_status = QLabel("No card scanned")
        self._card_status.setObjectName("cardStatusNeutral")
        self._card_status.setWordWrap(True)
        layout.addWidget(self._card_status)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self._card_fields: dict[str, QLabel] = {}
        fields = [
            ("technology", "Technology"),
            ("uid", "UID"),
            ("uid_length", "UID length"),
            ("atr", "ATR"),
            ("protocol", "Protocol"),
            ("manufacturer", "Manufacturer"),
            ("memory_size", "Memory size"),
            ("frequency", "Frequency"),
            ("confidence", "Confidence"),
            ("access", "Access"),
            ("reader", "Reader / backend"),
            ("warnings", "Warnings"),
        ]
        for key, label in fields:
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setMinimumWidth(220)
            self._card_fields[key] = value
            form.addRow(QLabel(label + ":"), value)
        layout.addLayout(form)
        layout.addStretch(1)
        return group

    def _build_memory_group(self) -> QGroupBox:
        group = QGroupBox("Memory / data blocks")
        layout = QVBoxLayout(group)
        self._memory_summary = QLabel("No memory data read.")
        self._memory_summary.setStyleSheet("color:#57606a;")
        layout.addWidget(self._memory_summary)

        self._memory_table = QTableWidget(0, 7)
        self._memory_table.setHorizontalHeaderLabels(
            ["Sector", "Block", "Address", "Data (hex)", "ASCII", "Access", "Note"]
        )
        self._memory_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._memory_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._memory_table.setAlternatingRowColors(True)
        self._memory_table.verticalHeader().setVisible(False)
        header = self._memory_table.horizontalHeader()
        for index in range(6):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._memory_table.setWordWrap(False)
        layout.addWidget(self._memory_table, 1)
        return group

    def _build_diagnostics_group(self) -> QGroupBox:
        group = QGroupBox("Diagnostics and events")
        layout = QVBoxLayout(group)
        self._diagnostics = QTextEdit()
        self._diagnostics.setReadOnly(True)
        self._diagnostics.setFont(QFont("Consolas", 9))
        self._diagnostics.setPlaceholderText(
            "Connect a reader and scan a card. Diagnostic messages, timestamps, and "
            "troubleshooting steps will appear here."
        )
        self._diagnostics.setMinimumHeight(150)
        layout.addWidget(self._diagnostics)

        row = QHBoxLayout()
        self._log_note = QLabel("")
        self._log_note.setStyleSheet("color:#57606a;")
        open_logs = QPushButton("Open Log Folder")
        open_logs.clicked.connect(self._open_log_folder)
        row.addWidget(self._log_note, 1)
        row.addWidget(open_logs)
        layout.addLayout(row)
        return group

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #d0d7de;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                color: #1f6feb;
            }
            QPushButton {
                padding: 6px 12px;
                border-radius: 6px;
                border: 1px solid #c9d1d9;
                background: #f6f8fa;
            }
            QPushButton:hover { background: #eef2f5; }
            QPushButton:disabled { color: #8c959f; background: #f6f8fa; }
            QPushButton#primaryButton {
                background: #1f6feb;
                color: white;
                border-color: #1f6feb;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover { background: #1158c7; }
            QLabel#statusOk { color: #1a7f37; font-weight: 600; }
            QLabel#statusWarn { color: #9a6700; font-weight: 600; }
            QLabel#statusError { color: #cf222e; font-weight: 600; }
            QLabel#statusNeutral { color: #57606a; font-weight: 600; }
            QLabel#cardStatusOk { color: #1a7f37; font-weight: 600; font-size: 11pt; }
            QLabel#cardStatusWarn { color: #9a6700; font-weight: 600; font-size: 11pt; }
            QLabel#cardStatusError { color: #cf222e; font-weight: 600; font-size: 11pt; }
            QLabel#cardStatusNeutral { color: #57606a; font-weight: 600; font-size: 11pt; }
            QTableWidget { gridline-color: #e1e4e8; selection-background-color: #ddf4ff; }
            QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #c9d1d9;
                border-radius: 5px;
                padding: 4px 6px;
                background: #ffffff;
            }
            QTextEdit {
                border: 1px solid #d0d7de;
                border-radius: 6px;
                background: #ffffff;
            }
            """
        )

    # ------------------------------------------------------------- backend
    def _populate_simulated_cards(self) -> None:
        self._sim_combo.clear()
        backend = SimulatedBackend()
        for sample in backend.available_cards():
            self._sim_combo.addItem(sample.label, sample.key)
            self._sim_combo.setItemData(self._sim_combo.count() - 1, sample.description, Qt.ItemDataRole.ToolTipRole)
        self._on_sim_card_changed()

    def _on_backend_changed(self) -> None:
        if self._worker is not None:
            return
        kind = ReaderKind(self._backend_combo.currentData())
        self._backend_kind = kind
        try:
            self._backend = build_backend(kind)
        except Exception as exc:
            self._append_log(f"Could not initialize backend: {exc}", Severity.ERROR)
            return
        simulated = kind is ReaderKind.SIMULATED
        for widget in (self._sim_label, self._sim_combo, self._sim_desc):
            widget.setVisible(simulated)
        self._read_memory_check.setVisible(kind is ReaderKind.PCSC)
        self._key_edit.setVisible(kind is ReaderKind.PCSC)
        self._key_show.setVisible(kind is ReaderKind.PCSC)
        self._connected = False
        self._set_connection_state(ConnectionState.DISCONNECTED, "Not connected")
        self._append_log(f"Backend selected: {self._backend.display_name}", Severity.INFO)
        availability = self._backend.availability()
        if not availability.available:
            for diagnostic in availability.diagnostics:
                self._append_diagnostic(diagnostic)
        self._refresh_readers()
        if simulated:
            self._on_sim_card_changed()

    def _refresh_readers(self) -> None:
        self._reader_combo.clear()
        self._reader_detail.setText("")
        self._connected = False
        self._set_connection_state(ConnectionState.DISCONNECTED, "Not connected")
        try:
            readers = self._backend.list_readers()
        except ReaderBackendError as exc:
            self._append_diagnostic(exc.diagnostic)
            self._reader_combo.addItem("No readers available")
            self._reader_combo.setEnabled(False)
            self._connect_btn.setEnabled(False)
            return
        except Exception as exc:
            self._append_diagnostic(diag.from_exception(exc, context="reader enumeration"))
            self._reader_combo.addItem("Reader enumeration failed")
            self._reader_combo.setEnabled(False)
            self._connect_btn.setEnabled(False)
            return

        if not readers:
            self._reader_combo.addItem("No readers found")
            self._reader_combo.setEnabled(False)
            self._connect_btn.setEnabled(False)
            self._append_diagnostic(diag.no_reader(self._backend.display_name))
            return

        self._reader_combo.setEnabled(True)
        self._connect_btn.setEnabled(True)
        for reader in readers:
            self._reader_combo.addItem(reader.name, reader)
        self._on_reader_selected()

    def _on_reader_selected(self) -> None:
        self._connected = False
        reader = self._reader_combo.currentData()
        if reader is None:
            self._reader_detail.setText("")
            self._set_connection_state(ConnectionState.DISCONNECTED, "Not connected")
            return
        parts = []
        if reader.vendor:
            parts.append(f"Vendor: {reader.vendor}")
        if reader.model:
            parts.append(f"Model: {reader.model}")
        if reader.interface:
            parts.append(f"Interface: {reader.interface}")
        parts.extend(reader.notes)
        self._reader_detail.setText(" | ".join(parts))

    def _connect_reader(self) -> None:
        reader = self._reader_combo.currentData()
        if reader is None:
            self._append_diagnostic(diag.no_reader(self._backend.display_name))
            return
        try:
            connected = self._backend.connect(reader.name)
        except ReaderBackendError as exc:
            self._append_diagnostic(exc.diagnostic)
            self._set_connection_state(ConnectionState.ERROR, "Connection failed")
            return
        except Exception as exc:
            self._append_diagnostic(diag.from_exception(exc, context="connect"))
            self._set_connection_state(ConnectionState.ERROR, "Connection failed")
            return
        self._connected = True
        self._connect_btn.setText("Reconnect Reader")
        self._set_connection_state(ConnectionState.CONNECTED, f"Connected: {connected.name}")
        self._append_log(f"Connected to {connected.name}", Severity.INFO)
        if self._auto_check.isChecked():
            self._auto_timer.start()

    def _on_sim_card_changed(self) -> None:
        backend = self._backend
        if not isinstance(backend, SimulatedBackend):
            return
        key = self._sim_combo.currentData()
        if key:
            backend.select_card(key)
            sample = next((item for item in backend.available_cards() if item.key == key), None)
            if sample:
                self._sim_desc.setText(sample.description)

    # --------------------------------------------------------------- scan
    def _manual_scan(self) -> None:
        self._start_scan(auto=False)

    def _start_scan(self, *, auto: bool) -> None:
        if self._worker is not None:
            return
        if not self._connected:
            self._connect_reader()
            if not self._connected:
                return

        key = None
        if self._backend_kind is ReaderKind.PCSC:
            try:
                key = parse_key_hex(self._key_edit.text())
            except ValueError as exc:
                self._append_diagnostic(
                    diag.diagnostic(
                        DiagnosticCode.INVALID_KEY_FORMAT,
                        message=str(exc),
                    )
                )
                return
            if key is not None:
                REDACTOR.add_secret(key)
                self._active_key = key

        reader = self._reader_combo.currentData()
        reader_name = reader.name if reader is not None else None
        timeout = max(0.5, float(self._timeout_spin.value()))
        if auto:
            timeout = min(timeout, 1.2)

        self._cancel.clear()
        self._worker = ScanWorker(
            self._backend,
            reader_name,
            timeout,
            key,
            self._read_memory_check.isChecked(),
            self._cancel,
        )
        self._worker.completed.connect(self._on_scan_completed)
        self._worker.failed.connect(self._on_scan_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._set_scanning(True)
        if not auto:
            self._card_status.setText("Scanning...")
            self._card_status.setObjectName("cardStatusWarn")
            self._card_status.style().unpolish(self._card_status)
            self._card_status.style().polish(self._card_status)
            self._append_log(f"Scan started (waiting up to {timeout:.1f} s)", Severity.INFO)
        self._worker.start()

    def _stop_scan(self) -> None:
        if self._auto_check.isChecked():
            self._auto_check.setChecked(False)
        self._cancel.set()
        if self._worker is not None:
            self._append_log("Stop requested; waiting for the scan to exit.", Severity.INFO)
        else:
            self._set_scanning(False)

    def _on_scan_completed(self, result: ScanResult) -> None:
        self._clear_active_key()
        self._current_result = result
        log_scan_result(self._logger, result)

        is_auto = self._auto_check.isChecked()
        if is_auto and not result.card_detected and result.diagnostics:
            message = result.diagnostics[0].message
            if message != self._last_auto_message:
                self._last_auto_message = message
                self._append_diagnostic(result.diagnostics[0])
            self._card_status.setText("Waiting for card...")
            self._set_card_status_style("cardStatusNeutral")
            self._set_scanning(False)
            return

        fingerprint = None
        if result.card:
            fingerprint = (
                result.card.uid or "",
                result.card.atr_hex,
                result.card.technology.value,
            )
        if is_auto and fingerprint is not None and fingerprint == self._last_fingerprint:
            self._set_scanning(False)
            return
        if fingerprint is not None:
            self._last_fingerprint = fingerprint
        self._last_auto_message = None

        self._display_result(result)
        if not is_auto:
            for diagnostic in result.diagnostics:
                self._append_diagnostic(diagnostic)
        else:
            for diagnostic in result.diagnostics:
                if diagnostic.severity is not Severity.INFO:
                    self._append_diagnostic(diagnostic)
        self._set_scanning(False)

    def _on_scan_failed(self, diagnostic: Diagnostic) -> None:
        self._clear_active_key()
        self._append_diagnostic(diagnostic)
        self._current_result = None
        self._export_btn.setEnabled(False)
        self._clear_card_fields()
        self._memory_table.setRowCount(0)
        self._memory_summary.setText("No memory data read.")
        self._card_status.setText("Scan failed")
        self._set_card_status_style("cardStatusError")
        self._set_scanning(False)

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_scanning(False)

    def _set_scanning(self, scanning: bool) -> None:
        self._scan_btn.setEnabled(not scanning and self._connected)
        self._stop_btn.setEnabled(scanning)
        self._backend_combo.setEnabled(not scanning)
        self._reader_combo.setEnabled(not scanning and self._reader_combo.count() > 0)
        self._refresh_btn.setEnabled(not scanning)
        self._connect_btn.setEnabled(not scanning and self._reader_combo.count() > 0)
        self._read_memory_check.setEnabled(not scanning)
        self._key_edit.setEnabled(not scanning)
        self._progress.setVisible(scanning)

    def _toggle_auto(self, enabled: bool) -> None:
        if enabled:
            if not self._connected:
                self._connect_reader()
            if self._connected:
                self._append_log("Auto-scan enabled (3 s interval).", Severity.INFO)
                self._auto_timer.start()
                QTimer.singleShot(50, self._auto_scan_tick)
            else:
                self._auto_check.setChecked(False)
        else:
            self._auto_timer.stop()
            self._append_log("Auto-scan disabled.", Severity.INFO)

    def _auto_scan_tick(self) -> None:
        if not self._auto_check.isChecked():
            self._auto_timer.stop()
            return
        if self._worker is not None or not self._connected:
            return
        self._start_scan(auto=True)

    # ------------------------------------------------------------- display
    def _display_result(self, result: ScanResult) -> None:
        card = result.card
        if card is None:
            self._card_status.setText("No card detected")
            self._set_card_status_style("cardStatusWarn")
            self._clear_card_fields()
            self._memory_table.setRowCount(0)
            self._memory_summary.setText("No memory data read.")
            self._export_btn.setEnabled(False)
            return

        self._export_btn.setEnabled(True)
        self._card_status.setText(f"Card detected — {card.technology.value}")
        if card.access_state in (DataAccess.AUTH_REQUIRED, DataAccess.PROTECTED, DataAccess.UNREADABLE):
            self._set_card_status_style("cardStatusWarn")
        else:
            self._set_card_status_style("cardStatusOk")

        values = {
            "technology": card.technology.value,
            "uid": card.uid_display if card.uid else "Unavailable",
            "uid_length": f"{len(card.uid_bytes)} bytes" if card.uid_bytes else "Unknown",
            "atr": card.atr_hex or "Unavailable",
            "protocol": card.protocol or "Unavailable",
            "manufacturer": card.manufacturer or "Not determined",
            "memory_size": card.memory_size or "Unknown",
            "frequency": card.frequency or "Unknown",
            "confidence": card.confidence,
            "access": card.access_state.value,
            "reader": f"{result.reader.name if result.reader else 'Unknown'} ({result.backend})",
            "warnings": "\n".join(card.warnings) if card.warnings else "None",
        }
        for key, value in values.items():
            self._card_fields[key].setText(value)

        self._fill_memory(card.memory)
        if card.memory:
            summary = memory_summary(card.memory)
            self._memory_summary.setText(
                "Summary: "
                + ", ".join(f"{access}: {count}" for access, count in sorted(summary.items()))
            )
        else:
            self._memory_summary.setText("No memory data read.")

        if result.reader and result.reader.notes:
            self._reader_detail.setText(" | ".join(result.reader.notes))

    def _fill_memory(self, memory: list[MemoryBlock]) -> None:
        self._memory_table.setRowCount(0)
        if not memory:
            return
        self._memory_table.setRowCount(len(memory))
        for row, block in enumerate(memory):
            values = [
                "" if block.sector is None else str(block.sector),
                str(block.block),
                str(block.address),
                block.hex_data or "—",
                block.ascii_data or "",
                block.access.value,
                block.note or "",
            ]
            background = _ACCESS_COLORS.get(block.access)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if background and block.access is not DataAccess.NOT_ATTEMPTED:
                    item.setBackground(QBrush(QColor(background)))
                item.setToolTip(value)
                self._memory_table.setItem(row, column, item)

    def _clear_card_fields(self) -> None:
        for value in self._card_fields.values():
            value.setText("—")

    def _set_card_status_style(self, object_name: str) -> None:
        self._card_status.setObjectName(object_name)
        self._card_status.style().unpolish(self._card_status)
        self._card_status.style().polish(self._card_status)

    def _set_connection_state(self, state: ConnectionState, text: str) -> None:
        self._connection_status.setText(text)
        name = {
            ConnectionState.CONNECTED: "statusOk",
            ConnectionState.CONNECTING: "statusWarn",
            ConnectionState.ERROR: "statusError",
            ConnectionState.DISCONNECTED: "statusNeutral",
        }[state]
        self._connection_status.setObjectName(name)
        self._connection_status.style().unpolish(self._connection_status)
        self._connection_status.style().polish(self._connection_status)
        self._scan_btn.setEnabled(state is ConnectionState.CONNECTED and self._worker is None)
        if state is not ConnectionState.CONNECTED:
            self._connect_btn.setText("Connect Reader")
        else:
            self._connect_btn.setText("Reconnect Reader")

    # -------------------------------------------------------------- actions
    def _clear_results(self) -> None:
        self._current_result = None
        self._last_fingerprint = None
        self._last_auto_message = None
        self._card_status.setText("No card scanned")
        self._set_card_status_style("cardStatusNeutral")
        self._clear_card_fields()
        self._memory_table.setRowCount(0)
        self._memory_summary.setText("No memory data read.")
        self._diagnostics.clear()
        self._export_btn.setEnabled(False)
        self._append_log("Results cleared.", Severity.INFO)

    def _export_report(self) -> None:
        if self._current_result is None:
            self._append_log("There is no scan result to export.", Severity.WARNING)
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export scan report",
            str(Path.home() / "doorcard-report.json"),
            "JSON report (*.json);;CSV report (*.csv)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".csv" if "CSV" in selected_filter else ".json"
        try:
            exported = export_auto(self._current_result, path)
        except Exception as exc:
            self._append_log(f"Export failed: {type(exc).__name__}: {exc}", Severity.ERROR)
            QMessageBox.warning(self, "Export failed", f"Could not write the report:\n{exc}")
            return
        self._append_log(f"Report exported to {exported}", Severity.INFO)
        QMessageBox.information(self, "Report exported", f"Report written to:\n{exported}")

    def set_log_path(self, path: str | Path) -> None:
        self._log_note.setText(f"Log file: {path}")

    def _open_log_folder(self) -> None:
        from ..logging_setup import default_log_dir

        path = default_log_dir()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _toggle_key_visibility(self, visible: bool) -> None:
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _clear_active_key(self) -> None:
        if self._active_key is not None:
            REDACTOR.discard_secret(self._active_key)
            self._active_key = None
        self._key_edit.clear()

    # ---------------------------------------------------------------- log
    def _append_diagnostic(self, diagnostic: Diagnostic, *, timestamp: str | None = None) -> None:
        log_diagnostic(self._logger, diagnostic, context="ui")
        stamp = timestamp or utc_timestamp()
        color = _COLORS[diagnostic.severity]
        lines = [
            (
                f"<span style='color:#57606a'>[{html.escape(stamp)}]</span> "
                f"<b style='color:{color}'>[{diagnostic.severity.value.upper()}] "
                f"{html.escape(diagnostic.title)}</b>"
            ),
            f"&nbsp;&nbsp;{html.escape(diagnostic.message)}",
        ]
        if diagnostic.detail:
            lines.append(
                f"&nbsp;&nbsp;<span style='color:#57606a'>Detail: "
                f"{html.escape(diagnostic.detail)}</span>"
            )
        for item in diagnostic.remediation:
            lines.append(f"&nbsp;&nbsp;• {html.escape(item)}")
        self._append_html("<br>".join(lines))

    def _append_log(self, text: str, severity: Severity = Severity.INFO) -> None:
        level = {
            Severity.INFO: logging.INFO,
            Severity.WARNING: logging.WARNING,
            Severity.ERROR: logging.ERROR,
        }[severity]
        self._logger.log(level, text)
        color = _COLORS[severity]
        self._append_html(
            f"<span style='color:#57606a'>[{html.escape(utc_timestamp())}]</span> "
            f"<span style='color:{color}'>{html.escape(text)}</span>"
        )

    def _append_html(self, text: str) -> None:
        self._diagnostics.append(text)
        scrollbar = self._diagnostics.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event) -> None:
        self._auto_timer.stop()
        self._cancel.set()
        if self._worker is not None:
            self._worker.wait(2500)
        self._clear_active_key()
        try:
            self._backend.disconnect()
        except Exception:
            pass
        event.accept()
