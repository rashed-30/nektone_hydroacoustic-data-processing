"""Tab 3 - open any .nc product and draw the echogram."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import (  # noqa: E402
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure  # noqa: E402

from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from .widgets import PathPicker, spin  # noqa: E402
from .worker import Worker  # noqa: E402

COLORMAPS = ["viridis", "jet", "turbo", "magma", "inferno", "cividis", "ocean", "Spectral_r"]
MAX_CELLS = 4_000_000  # decimate beyond this so a huge file can't lock the UI


class ViewerTab(QWidget):
    log_message = Signal(str, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ds = None
        self._worker = None

        self.file_picker = PathPicker("open", "Open a NetCDF echogram", "NetCDF files (*.nc)")
        self.file_picker.changed.connect(self._on_file_changed)

        self.channel = QComboBox()
        self.channel.setMinimumWidth(220)
        self.cmap = QComboBox()
        self.cmap.addItems(COLORMAPS)
        self.vmin = spin(-200, 0, -90, 1, 1, " dB")
        self.vmax = spin(-200, 0, -40, 1, 1, " dB")

        self.load_button = QPushButton("Load file")
        self.load_button.clicked.connect(self._load)
        self.plot_button = QPushButton("Plot echogram")
        self.plot_button.clicked.connect(self._plot)
        self.plot_button.setEnabled(False)
        self.save_button = QPushButton("Save image…")
        self.save_button.clicked.connect(self._save)
        self.save_button.setEnabled(False)

        controls = QHBoxLayout()
        for widget in (
            QLabel("Channel"), self.channel,
            QLabel("Colour map"), self.cmap,
            QLabel("Min"), self.vmin,
            QLabel("Max"), self.vmax,
        ):
            controls.addWidget(widget)
        controls.addStretch(1)
        controls.addWidget(self.plot_button)
        controls.addWidget(self.save_button)

        self.info = QLabel("Open a .nc file to begin.")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#555; padding:4px;")

        top = QGroupBox("Echogram")
        top_layout = QVBoxLayout(top)
        picker_row = QHBoxLayout()
        picker_row.addWidget(self.file_picker, 1)
        picker_row.addWidget(self.load_button)
        top_layout.addLayout(picker_row)
        top_layout.addLayout(controls)
        top_layout.addWidget(self.info)

        self.figure = Figure(figsize=(11, 5.5), layout="constrained")
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout = QVBoxLayout(self)
        layout.addWidget(top)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

    # -- loading -------------------------------------------------------
    def _on_file_changed(self, _text):
        self.plot_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def _load(self):
        path = self.file_picker.value()
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "No file", "Choose a .nc file first.")
            return
        if self._worker is not None:
            return
        self._close_dataset()

        def job(ctx):
            import xarray as xr
            ctx.info(f"Opening {Path(path).name}…")
            ds = xr.open_dataset(path)
            if "Sv" not in ds:
                ds.close()
                raise KeyError("This file has no 'Sv' variable. Is it a binned product?")
            return ds.load()

        self._worker = Worker(job, self)
        self._worker.signals.log.connect(self.log_message.emit)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.finished.connect(self._on_loaded)
        self._worker.finished.connect(self._cleanup_worker)
        self.load_button.setEnabled(False)
        self.busy_changed.emit(True)
        self.info.setText("Loading…")
        self._worker.start()

    def _on_loaded(self, ds):
        self._ds = ds
        channels = [str(c) for c in ds["channel"].values] if "channel" in ds.dims else ["(single)"]
        self.channel.clear()
        self.channel.addItems(channels)
        self.plot_button.setEnabled(True)
        try:
            t0, t1 = ds["ping_time"].values.min(), ds["ping_time"].values.max()
            y = "depth" if "depth" in ds.coords or "depth" in ds.dims else "echo_range"
            d0, d1 = float(ds[y].min()), float(ds[y].max())
            note = ""
            for key in ("nektone_binning", "nektone_masking", "nektone_noise_removal"):
                if key in ds.attrs:
                    note += f"<br><span style='color:#777'>{key.replace('nektone_', '')}: {ds.attrs[key]}</span>"
            self.info.setText(
                f"{len(channels)} channel(s) · {ds.sizes.get('ping_time', 0)} time steps · "
                f"{t0} → {t1} · {y} {d0:.1f}–{d1:.1f} m{note}"
            )
        except Exception:  # noqa: BLE001
            self.info.setText("Loaded.")
        self.log_message.emit("File loaded.", "success")
        self._plot()

    def _on_failed(self, message, tb):
        self.log_message.emit(message, "error")
        self.log_message.emit(tb, "debug")
        self.info.setText(f"Failed: {message}")
        QMessageBox.critical(self, "Could not open file", message)

    def _cleanup_worker(self):
        self.load_button.setEnabled(True)
        self.busy_changed.emit(False)
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    # -- plotting ------------------------------------------------------
    def _plot(self):
        if self._ds is None:
            return
        try:
            ds = self._ds
            sv = ds["Sv"]
            if "channel" in sv.dims and self.channel.currentText() != "(single)":
                sv = sv.sel(channel=self.channel.currentText())
            y = "depth" if "depth" in sv.coords or "depth" in sv.dims else "echo_range"
            if y not in sv.coords and y not in sv.dims:
                raise KeyError("No depth or echo_range axis in this file.")

            # Guard against opening a raw, unbinned file by accident.
            if sv.size > MAX_CELLS:
                step = int(sv.size / MAX_CELLS) + 1
                sv = sv.isel(ping_time=slice(None, None, step))
                self.log_message.emit(
                    f"Large file - showing every {step}th ping for display only.", "warning")

            self.figure.clear()
            ax = self.figure.add_subplot(111)
            mesh = sv.transpose(y, "ping_time").plot(
                ax=ax, x="ping_time", y=y,
                cmap=self.cmap.currentText(),
                vmin=self.vmin.value(), vmax=self.vmax.value(),
                add_colorbar=True, cbar_kwargs={"label": "Sv (dB re 1 m⁻¹)"},
            )
            if y == "depth":
                ax.invert_yaxis()
                ax.set_ylabel("Depth (m)")
            else:
                ax.invert_yaxis()
                ax.set_ylabel("Range (m)")
            ax.set_xlabel("Time")
            ax.set_title(f"{Path(self.file_picker.value()).name} — {self.channel.currentText()}")
            self.figure.autofmt_xdate()
            self.canvas.draw_idle()
            self.save_button.setEnabled(True)
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"Plot failed: {type(exc).__name__}: {exc}", "error")
            QMessageBox.critical(self, "Plot failed", f"{type(exc).__name__}: {exc}")

    def _save(self):
        default = str(Path(self.file_picker.value()).with_suffix(".png"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save echogram", default, "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if path:
            try:
                self.figure.savefig(path, dpi=200)
                self.log_message.emit(f"Saved {path}", "success")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save failed", str(exc))

    # -- teardown ------------------------------------------------------
    def _close_dataset(self):
        if self._ds is not None:
            try:
                self._ds.close()
            except Exception:
                pass
            self._ds = None

    def shutdown(self):
        self._close_dataset()

    @property
    def is_running(self) -> bool:
        return self._worker is not None
