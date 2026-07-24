"""Shared plumbing for the three tabs that run a background job."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from .worker import Worker


class JobTab(QWidget):
    """A tab with a Run button, a Stop button, a progress bar and a status line.

    Subclasses implement `build_job()` which returns a zero-argument-plus-ctx
    callable, and `validate()` which raises ValueError with a friendly message.
    """

    busy_changed = Signal(bool)
    log_message = Signal(str, str)

    run_label = "Run"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

        self.run_button = QPushButton(self.run_label)
        self.run_button.setMinimumHeight(34)
        self.run_button.clicked.connect(self.start)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setMinimumHeight(34)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("idle")

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)

        self._controls = QHBoxLayout()
        self._controls.addWidget(self.run_button, 2)
        self._controls.addWidget(self.stop_button, 1)

    # -- hooks ---------------------------------------------------------
    def validate(self) -> None:
        """Raise ValueError if the form is not runnable."""

    def build_job(self):
        raise NotImplementedError

    def on_success(self, result) -> None:
        pass

    # -- lifecycle -----------------------------------------------------
    def control_row(self) -> QHBoxLayout:
        return self._controls

    def footer(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._controls)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        return box

    def start(self):
        if self._worker is not None:
            return
        try:
            self.validate()
            job = self.build_job()
        except ValueError as exc:
            QMessageBox.warning(self, "Check your settings", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Could not start", f"{type(exc).__name__}: {exc}")
            return

        self._worker = Worker(job, self)
        self._worker.signals.log.connect(self.log_message.emit)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.stopped.connect(self._on_stopped)
        self._worker.finished.connect(self._cleanup)

        self._set_busy(True)
        self.status.setText("Working…")
        self.progress.setRange(0, 0)  # indeterminate until first update
        self.progress.setFormat("starting…")
        self._worker.start()

    def stop(self):
        if self._worker is not None:
            self.stop_button.setEnabled(False)
            self._worker.cancel()

    def _on_progress(self, done: int, total: int, label: str):
        if total <= 0:
            return
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        shown = (label[:70] + "…") if len(label) > 71 else label
        self.progress.setFormat(f"%v / %m   {shown}")

    def _on_finished(self, result):
        self.status.setText(self.describe(result))
        self.on_success(result)

    def describe(self, result) -> str:
        summary = getattr(result, "summary", None)
        return f"Done. {summary()}" if callable(summary) else "Done."

    def _on_failed(self, message: str, tb: str):
        self.log_message.emit(message, "error")
        self.log_message.emit(tb, "debug")
        self.status.setText(f"Failed: {message}")
        QMessageBox.critical(
            self, "Job failed",
            f"{message}\n\nThe full traceback is in the log file "
            "(Help ▸ Open log folder).",
        )

    def _on_stopped(self):
        self.status.setText("Stopped by user. Already-written files are intact.")
        self.log_message.emit("Job stopped.", "warning")

    def _cleanup(self):
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("idle")
        self._set_busy(False)
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _set_busy(self, busy: bool):
        self.run_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.busy_changed.emit(busy)

    @property
    def is_running(self) -> bool:
        return self._worker is not None
