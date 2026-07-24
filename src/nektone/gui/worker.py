"""Background execution.

Every long-running call happens here, never on the GUI thread. This is the
single most important stability rule in the app: xarray/echopype operations
that block the event loop make Windows mark the window "Not Responding", and
users then force-quit mid-write and corrupt outputs.
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..core.jobs import JobContext, Cancelled


class WorkerSignals(QObject):
    log = Signal(str, str)            # message, level
    progress = Signal(int, int, str)  # done, total, label
    finished = Signal(object)         # result object
    failed = Signal(str, str)         # short message, traceback
    stopped = Signal()                # cancelled cleanly


class Worker(QThread):
    """Runs `fn(ctx)` off the GUI thread.

    The callable receives a JobContext whose log/progress callbacks emit Qt
    signals; Qt queues them across the thread boundary automatically, so the
    core code stays completely Qt-free.
    """

    def __init__(self, fn: Callable[[JobContext], object], parent=None):
        super().__init__(parent)
        self._fn = fn
        self.signals = WorkerSignals()
        self._cancel = threading.Event()
        self.ctx = JobContext(
            log_fn=lambda m, l: self.signals.log.emit(m, l),
            progress_fn=lambda d, t, s: self.signals.progress.emit(d, t, s),
            cancel_event=self._cancel,
        )

    def cancel(self) -> None:
        self._cancel.set()
        self.ctx.log("Stop requested - finishing current file...", "warning")

    def run(self) -> None:  # executed on the worker thread
        try:
            result = self._fn(self.ctx)
        except Cancelled:
            self.signals.stopped.emit()
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())
        else:
            if self._cancel.is_set():
                self.signals.stopped.emit()
            else:
                self.signals.finished.emit(result)
