"""A tiny cooperative-cancellation + reporting context.

Core pipeline functions take a `JobContext` and never import Qt. The GUI passes
one whose callbacks marshal back to the UI thread via signals; the CLI passes
one that prints.
"""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional


class Cancelled(Exception):
    """Raised inside the pipeline when the user asks to stop."""


@dataclass
class JobContext:
    log_fn: Optional[Callable[[str, str], None]] = None       # (message, level)
    progress_fn: Optional[Callable[[int, int, str], None]] = None  # (done, total, label)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    # ---- reporting ---------------------------------------------------
    def log(self, message: str, level: str = "info") -> None:
        if self.log_fn:
            self.log_fn(str(message), level)

    def info(self, msg): self.log(msg, "info")
    def ok(self, msg): self.log(msg, "success")
    def warn(self, msg): self.log(msg, "warning")
    def error(self, msg): self.log(msg, "error")

    def exception(self, prefix: str, exc: BaseException) -> None:
        self.error(f"{prefix}: {type(exc).__name__}: {exc}")
        self.log(traceback.format_exc(), "debug")

    def progress(self, done: int, total: int, label: str = "") -> None:
        if self.progress_fn:
            self.progress_fn(int(done), int(total), str(label))

    # ---- cancellation ------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled("Stopped by user.")


def console_context() -> JobContext:
    def _log(msg, level):
        if level == "debug":
            return
        prefix = {"error": "[ERROR]", "warning": "[WARN ]", "success": "[ OK  ]"}.get(level, "[info ]")
        print(f"{prefix} {msg}", flush=True)

    def _prog(done, total, label):
        if total:
            print(f"    {done}/{total}  {label}", end="\r", flush=True)

    return JobContext(log_fn=_log, progress_fn=_prog)
