from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import __version__
from .logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    log_path = setup_logging(console=False)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Universal Electronic Door Card Reader")
    app.setApplicationDisplayName("Universal Electronic Door Card Reader")
    app.setApplicationVersion(__version__)

    from .ui.main_window import MainWindow

    window = MainWindow()
    window.set_log_path(log_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
