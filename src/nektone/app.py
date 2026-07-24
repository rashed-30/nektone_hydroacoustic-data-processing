"""GUI entry point."""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # Required so a frozen (PyInstaller) build does not respawn the GUI when a
    # dependency uses multiprocessing internally.
    multiprocessing.freeze_support()

    # Crash capture first: a native crash during window construction is the
    # single hardest failure to diagnose, and it must be armed before Qt loads.
    from .core import crashlog
    from .gui.main_window import user_data_dir
    crash_path = crashlog.install(user_data_dir() / "logs")

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("NekTone")
    app.setOrganizationName("NekTone")
    app.setStyle("Fusion")

    from .gui.main_window import MainWindow

    window = MainWindow()
    window.log.append(f"Crash log: {crash_path}", "info")
    window.show()
    try:
        return app.exec()
    finally:
        crashlog.close()


if __name__ == "__main__":
    sys.exit(main())
