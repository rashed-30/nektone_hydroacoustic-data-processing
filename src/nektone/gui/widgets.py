"""Small reusable widgets shared across the tabs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

LEVEL_COLOURS = {
    "info": "#d0d0d0",
    "success": "#7ddc7d",
    "warning": "#ffc861",
    "error": "#ff7b72",
    "debug": "#7a7a7a",
}


class PathPicker(QWidget):
    """Line edit + Browse button for a folder or a file."""

    changed = Signal(str)

    def __init__(self, mode: str = "dir", caption: str = "Select", file_filter: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.caption = caption
        self.file_filter = file_filter

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("(none selected)")
        self.edit.textChanged.connect(self.changed.emit)
        self.edit.setAcceptDrops(True)

        button = QPushButton("Browse…")
        button.clicked.connect(self._browse)
        button.setFixedWidth(90)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(button)
        self.setAcceptDrops(True)

    # -- drag & drop straight from Explorer ---------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.edit.setText(urls[0].toLocalFile())
            event.acceptProposedAction()

    def _browse(self):
        start = self.edit.text() or str(Path.home())
        if self.mode == "dir":
            path = QFileDialog.getExistingDirectory(self, self.caption, start)
        elif self.mode == "save":
            path, _ = QFileDialog.getSaveFileName(self, self.caption, start, self.file_filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.caption, start, self.file_filter)
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, text: str):
        self.edit.setText(text or "")


class LogConsole(QPlainTextEdit):
    """Colour-coded, capped, and mirrored to a session log file on disk."""

    MAX_BLOCKS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setStyleSheet(
            "QPlainTextEdit { background:#1e1e1e; color:#d0d0d0; "
            "font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:11px; }"
        )
        self._file = None

    def attach_file(self, path: Path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8", buffering=1)
            self._file.write(f"\n===== NekTone session {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        except OSError:
            self._file = None

    def append(self, message: str, level: str = "info"):
        stamp = datetime.now().strftime("%H:%M:%S")
        colour = LEVEL_COLOURS.get(level, "#d0d0d0")
        if self._file:
            try:
                self._file.write(f"{stamp} [{level}] {message}\n")
            except (OSError, ValueError):
                pass
        if level == "debug":
            return  # tracebacks go to the file only, to keep the pane readable
        safe = (message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        self.appendHtml(f'<span style="color:#6a6a6a">{stamp}</span> '
                        f'<span style="color:{colour}">{safe}</span>')
        self.moveCursor(QTextCursor.End)

    def close_file(self):
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


class DepthBandTable(QGroupBox):
    """Editor for arbitrary depth bands to exclude (ringdown lines, artefacts)."""

    def __init__(self, parent=None):
        super().__init__("Exclude depth bands", parent)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["From (m)", "To (m)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMaximumHeight(140)

        add = QPushButton("Add band")
        add.clicked.connect(lambda: self.add_band(0.0, 0.0))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Samples inside these depth ranges are set to NaN."))
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def add_band(self, lo: float, hi: float):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, val in ((0, lo), (1, hi)):
            item = QTableWidgetItem(f"{val:g}")
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, col, item)

    def _remove_selected(self):
        for idx in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(idx)

    def bands(self):
        out = []
        for row in range(self.table.rowCount()):
            try:
                lo = float(self.table.item(row, 0).text())
                hi = float(self.table.item(row, 1).text())
            except (AttributeError, ValueError):
                continue
            if lo != hi:
                out.append((min(lo, hi), max(lo, hi)))
        return out

    def set_bands(self, bands):
        self.table.setRowCount(0)
        for lo, hi in bands or []:
            self.add_band(float(lo), float(hi))


def spin(minimum, maximum, value, decimals=2, step=1.0, suffix=""):
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setMinimumWidth(110)
    return box


def check(text, checked=True):
    box = QCheckBox(text)
    box.setChecked(checked)
    return box
