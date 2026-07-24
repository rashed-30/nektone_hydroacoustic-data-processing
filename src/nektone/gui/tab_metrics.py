"""Tab 4 - baseline metrics from the binned monthly products."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGridLayout, QGroupBox, QLabel, QVBoxLayout,
)

from ..core import metrics as core_metrics
from ..core.config import MetricsConfig
from .base_tab import JobTab
from .widgets import PathPicker, spin

TIMEZONES = [
    "America/St_Johns", "America/Halifax", "America/Toronto", "UTC",
    "Asia/Dhaka", "Europe/Dublin", "Europe/London",
]


class MetricsTab(JobTab):
    run_label = "Compute metrics"

    def __init__(self, cfg: MetricsConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        self.input_dir = PathPicker("dir", "Select folder of binned products")
        self.output_csv = PathPicker("save", "Save metrics CSV", "CSV files (*.csv)")
        self.threshold = spin(-200, 0, -80.0, 1, 1.0, " dB")

        form = QFormLayout()
        form.addRow("Binned products folder", self.input_dir)
        form.addRow("Output CSV", self.output_csv)
        form.addRow("Biological threshold", self.threshold)
        io_box = QGroupBox("Input / output")
        io_box.setLayout(form)

        self.solar_box = QGroupBox("Solar-window standardisation")
        self.solar_box.setCheckable(True)
        self.solar_box.setChecked(True)
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.timezone.addItems(TIMEZONES)
        self.day_start = spin(0, 23, 10, 0, 1, ":00")
        self.day_end = spin(0, 23, 14, 0, 1, ":00")
        self.night_start = spin(0, 23, 22, 0, 1, ":00")
        self.night_end = spin(0, 23, 2, 0, 1, ":00")

        grid = QGridLayout()
        grid.addWidget(QLabel("Local time zone"), 0, 0)
        grid.addWidget(self.timezone, 0, 1, 1, 3)
        grid.addWidget(QLabel("Day window"), 1, 0)
        grid.addWidget(self.day_start, 1, 1)
        grid.addWidget(QLabel("to"), 1, 2)
        grid.addWidget(self.day_end, 1, 3)
        grid.addWidget(QLabel("Night window"), 2, 0)
        grid.addWidget(self.night_start, 2, 1)
        grid.addWidget(QLabel("to"), 2, 2)
        grid.addWidget(self.night_end, 2, 3)
        grid.setColumnStretch(4, 1)
        solar_layout = QVBoxLayout(self.solar_box)
        solar_layout.addWidget(QLabel(
            "Timestamps are converted from UTC to local time (daylight saving handled), "
            "then metrics are reported separately for the day and night windows as well "
            "as for the whole month."
        ))
        solar_layout.addLayout(grid)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Step 3 — Metrics.</b> Occupied Area, Mean S<sub>a</sub> and Centre of "
            "Mass per channel, per month, written to one tidy CSV."
        ))
        layout.addWidget(io_box)
        layout.addWidget(self.solar_box)
        layout.addWidget(QLabel(
            "<span style='color:#666'>Occupied Area is reported against valid "
            "(non-masked) cells <i>and</i> against all cells, so results from the "
            "original notebook remain reproducible.</span>"
        ))
        layout.addStretch(1)
        layout.addWidget(self.footer())

        self.load_from(cfg)

    def load_from(self, cfg: MetricsConfig):
        self.cfg = cfg
        self.input_dir.set_value(cfg.input_dir)
        self.output_csv.set_value(cfg.output_csv)
        self.threshold.setValue(cfg.bio_threshold_db)
        self.solar_box.setChecked(cfg.split_day_night)
        self.timezone.setCurrentText(cfg.timezone)
        self.day_start.setValue(cfg.day_start_hour)
        self.day_end.setValue(cfg.day_end_hour)
        self.night_start.setValue(cfg.night_start_hour)
        self.night_end.setValue(cfg.night_end_hour)

    def collect(self) -> MetricsConfig:
        c = self.cfg
        c.input_dir = self.input_dir.value()
        c.output_csv = self.output_csv.value()
        c.bio_threshold_db = self.threshold.value()
        c.split_day_night = self.solar_box.isChecked()
        c.timezone = self.timezone.currentText().strip()
        c.day_start_hour = int(self.day_start.value())
        c.day_end_hour = int(self.day_end.value())
        c.night_start_hour = int(self.night_start.value())
        c.night_end_hour = int(self.night_end.value())
        return c

    def validate(self):
        cfg = self.collect()
        if not cfg.input_dir:
            raise ValueError("Select the folder containing your binned monthly products.")
        if not Path(cfg.input_dir).is_dir():
            raise ValueError(f"Folder does not exist:\n{cfg.input_dir}")
        if cfg.split_day_night and not cfg.timezone:
            raise ValueError("Enter a time zone, e.g. America/St_Johns.")

    def build_job(self):
        cfg = self.collect()
        return lambda ctx: core_metrics.run_metrics(cfg, ctx)

    def describe(self, result) -> str:
        if result.csv_path is None:
            return "No metrics produced."
        return f"Done. {result.rows} row(s) → {result.csv_path}"
