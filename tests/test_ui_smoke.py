from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_window_can_be_created_and_closed() -> None:
    from PySide6.QtWidgets import QApplication

    from doorcard.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert "Universal Electronic Door Card Reader" in window.windowTitle()
    assert window._backend_combo.count() == 3
    window.close()
    app.processEvents()


def test_ui_diagnostic_is_forwarded_to_logger(monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from doorcard import diagnostics as diag
    from doorcard.ui import main_window as ui

    forwarded = []

    def capture(logger, diagnostic, *, context=None):
        forwarded.append((logger.name, diagnostic.code, context))

    monkeypatch.setattr(ui, "log_diagnostic", capture)

    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    forwarded.clear()

    item = diag.card_error("unit-test")
    window._append_diagnostic(item)

    assert forwarded == [("doorcard.ui", item.code, "ui")]
    window.close()
    app.processEvents()


def test_simulated_scan_populates_ui() -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from doorcard.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._backend_combo.setCurrentIndex(1)
    window._connect_reader()
    assert window._connected

    loop = QEventLoop()
    window._start_scan(auto=False)
    worker = window._worker
    assert worker is not None
    worker.finished.connect(loop.quit)
    if worker.isFinished():
        loop.quit()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    app.processEvents()

    assert window._current_result is not None
    assert window._current_result.card is not None
    assert window._current_result.card.technology.value == "MIFARE Classic 1K"
    assert window._memory_table.rowCount() == 64
    window.close()
    app.processEvents()
