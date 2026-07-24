"""Crash capture.

"The application closed unexpectedly" has two very different causes, and they
need different tools:

* A **Python exception** that escapes the event loop. `sys.excepthook` and
  `threading.excepthook` catch these and write a traceback.
* A **native crash** — a segfault inside HDF5, netCDF4, Qt or a BLAS library.
  Python never sees these; the process simply vanishes. Only `faulthandler`,
  which installs an OS-level signal handler, leaves a trace.

The second kind is what usually kills a frozen scientific app, and it is exactly
the kind that produces no error message at all. Both are wired up before the
QApplication is created, so even a crash during window construction is recorded.
"""
from __future__ import annotations

import datetime as _dt
import faulthandler
import sys
import threading
import traceback
from pathlib import Path

_crash_file = None


def install(log_dir: Path) -> Path:
    """Enable all crash capture. Returns the crash log path."""
    global _crash_file

    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "crash.log"

    try:
        _crash_file = open(path, "a", encoding="utf-8", buffering=1)
        _crash_file.write(
            f"\n===== session {_dt.datetime.now():%Y-%m-%d %H:%M:%S} "
            f"| python {sys.version.split()[0]} | frozen={getattr(sys, 'frozen', False)} =====\n"
        )
        # Native crashes (segfault, abort, bus error) land here.
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        _crash_file = None

    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook
    return path


def _write(text: str) -> None:
    if _crash_file is not None:
        try:
            _crash_file.write(text)
        except (OSError, ValueError):
            pass
    sys.stderr.write(text)


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    text = (f"\n--- unhandled exception {_dt.datetime.now():%H:%M:%S} ---\n"
            + "".join(traceback.format_exception(exc_type, exc, tb)))
    _write(text)
    _show_dialog(f"{exc_type.__name__}: {exc}")


def _thread_excepthook(args) -> None:
    text = (f"\n--- unhandled exception in thread {args.thread.name} "
            f"{_dt.datetime.now():%H:%M:%S} ---\n"
            + "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))
    _write(text)


def _show_dialog(message: str) -> None:
    """Best-effort popup so the window does not just disappear silently."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("NekTone — unexpected error")
        box.setText("Something went wrong, but NekTone is still running.")
        box.setInformativeText(
            f"{message}\n\nThe full details are in crash.log "
            "(Help ▸ Open log folder). Any files already written are intact."
        )
        box.exec()
    except Exception:  # noqa: BLE001
        pass


def close() -> None:
    global _crash_file
    if _crash_file is not None:
        try:
            faulthandler.disable()
            _crash_file.close()
        except Exception:  # noqa: BLE001
            pass
        _crash_file = None
