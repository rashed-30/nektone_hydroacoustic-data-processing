"""Tab 2 - calibrate, mask, denoise, bin into monthly products."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGridLayout, QGroupBox, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..core import process as core_process
from ..core.config import ProcessConfig
from ..core.discovery import find_nc_files, group_by_month
from .base_tab import JobTab
from .widgets import DepthBandTable, PathPicker, check, spin

TIME_BINS = ["10min", "15min", "30min", "1h", "2h", "3h", "6h", "12h", "1D"]


class ProcessTab(JobTab):
    run_label = "Process and bin"

    def __init__(self, cfg: ProcessConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        # --- input / output -------------------------------------------
        self.input_dir = PathPicker("dir", "Select folder of converted .nc files")
        self.input_dir.changed.connect(self._refresh_preview)
        self.output_dir = PathPicker("dir", "Select output folder")
        self.skip_existing = check("Skip months whose output already exists", True)

        io_form = QFormLayout()
        io_form.addRow("Converted .nc folder", self.input_dir)
        io_form.addRow("Output folder", self.output_dir)
        io_form.addRow("", self.skip_existing)
        io_box = QGroupBox("Input / output")
        io_box.setLayout(io_form)

        # --- geometry + environment -----------------------------------
        self.mooring_depth = spin(0, 20000, 160.0, 1, 1.0, " m")
        self.mooring_depth.valueChanged.connect(self._sync_depth_hint)
        self.orientation = QComboBox()
        self.orientation.addItems(["upward", "downward"])
        self.orientation.currentTextChanged.connect(self._sync_depth_hint)

        self.use_env = check("Supply environmental parameters (recommended)", True)
        self.temperature = spin(-5, 40, 4.0, 2, 0.1, " °C")
        self.salinity = spin(0, 45, 32.0, 2, 0.1, " PSU")
        self.pressure = spin(0, 20000, 0.0, 1, 1.0, " dbar")
        self.auto_pressure = check("Derive pressure from mooring depth", True)
        self.auto_pressure.toggled.connect(lambda on: self.pressure.setEnabled(not on))
        self.pressure.setEnabled(False)
        self.use_env.toggled.connect(self._toggle_env)

        geom = QFormLayout()
        geom.addRow("Instrument depth", self.mooring_depth)
        geom.addRow("Looking", self.orientation)
        self.depth_hint = QLabel()
        self.depth_hint.setStyleSheet("color:#555;")
        geom.addRow("", self.depth_hint)
        geom_box = QGroupBox("Mooring geometry")
        geom_box.setLayout(geom)

        env = QFormLayout()
        env.addRow("", self.use_env)
        env.addRow("Temperature", self.temperature)
        env.addRow("Salinity", self.salinity)
        env.addRow("", self.auto_pressure)
        env.addRow("Pressure", self.pressure)
        env_box = QGroupBox("Calibration environment")
        env_box.setLayout(env)

        # --- masking (checkable = the whole step is optional) ---------
        self.mask_box = QGroupBox("Vertical masking")
        self.mask_box.setCheckable(True)
        self.mask_box.setChecked(True)
        self.keep_min = spin(-20000, 20000, 0.0, 1, 1.0, " m")
        self.keep_max = spin(-20000, 20000, 157.0, 1, 1.0, " m")
        self.use_keep_min = check("Cut above (surface side)", True)
        self.use_keep_max = check("Cut below (bottom / near-instrument side)", True)
        self.use_keep_min.toggled.connect(self.keep_min.setEnabled)
        self.use_keep_max.toggled.connect(self.keep_max.setEnabled)
        self.bands = DepthBandTable()

        mask_grid = QGridLayout()
        mask_grid.addWidget(self.use_keep_min, 0, 0)
        mask_grid.addWidget(self.keep_min, 0, 1)
        mask_grid.addWidget(self.use_keep_max, 1, 0)
        mask_grid.addWidget(self.keep_max, 1, 1)
        mask_grid.setColumnStretch(2, 1)
        mask_layout = QVBoxLayout(self.mask_box)
        mask_layout.addWidget(QLabel(
            "Only samples between these depths are kept. Add bands below to punch "
            "out interior artefacts such as a ringdown line."
        ))
        mask_layout.addLayout(mask_grid)
        mask_layout.addWidget(self.bands)

        # --- noise removal --------------------------------------------
        self.noise_box = QGroupBox("Noise removal")
        self.noise_box.setCheckable(True)
        self.noise_box.setChecked(True)

        self.impulse = check("Impulse noise", True)
        self.impulse_thr = spin(0, 60, 10.0, 1, 0.5, " dB")
        self.impulse_bin = spin(0.1, 200, 3.0, 1, 0.5, " m")

        self.transient = check("Transient noise", True)
        self.transient_thr = spin(0, 60, 12.0, 1, 0.5, " dB")
        self.transient_bin = spin(0.1, 200, 5.0, 1, 0.5, " m")
        self.transient_pings = spin(1, 500, 20, 0, 1, " pings")

        self.background = check("Background noise", True)
        self.background_snr = spin(0, 60, 5.0, 1, 0.5, " dB")
        self.background_rs = spin(1, 500, 5, 0, 1, " samples")
        self.background_pings = spin(1, 500, 3, 0, 1, " pings")

        grid = QGridLayout()
        grid.addWidget(self.impulse, 0, 0)
        grid.addWidget(QLabel("threshold"), 0, 1); grid.addWidget(self.impulse_thr, 0, 2)
        grid.addWidget(QLabel("depth bin"), 0, 3); grid.addWidget(self.impulse_bin, 0, 4)

        grid.addWidget(self.transient, 1, 0)
        grid.addWidget(QLabel("threshold"), 1, 1); grid.addWidget(self.transient_thr, 1, 2)
        grid.addWidget(QLabel("depth bin"), 1, 3); grid.addWidget(self.transient_bin, 1, 4)
        grid.addWidget(QLabel("side pings"), 1, 5); grid.addWidget(self.transient_pings, 1, 6)

        grid.addWidget(self.background, 2, 0)
        grid.addWidget(QLabel("SNR"), 2, 1); grid.addWidget(self.background_snr, 2, 2)
        grid.addWidget(QLabel("range samples"), 2, 3); grid.addWidget(self.background_rs, 2, 4)
        grid.addWidget(QLabel("ping window"), 2, 5); grid.addWidget(self.background_pings, 2, 6)
        grid.setColumnStretch(7, 1)
        QVBoxLayout(self.noise_box).addLayout(grid)

        for box, deps in (
            (self.impulse, (self.impulse_thr, self.impulse_bin)),
            (self.transient, (self.transient_thr, self.transient_bin, self.transient_pings)),
            (self.background, (self.background_snr, self.background_rs, self.background_pings)),
        ):
            box.toggled.connect(lambda on, d=deps: [w.setEnabled(on) for w in d])

        # --- binning ---------------------------------------------------
        self.range_bin = spin(0.05, 500, 2.0, 2, 0.5, " m")
        self.range_bin.valueChanged.connect(self._refresh_preview)
        self.time_bin = QComboBox()
        self.time_bin.setEditable(True)
        self.time_bin.addItems(TIME_BINS)
        self.time_bin.setCurrentText("1h")
        self.by_month = check("One output file per calendar month (auto-detected)", True)
        self.by_month.stateChanged.connect(self._refresh_preview)

        bin_form = QFormLayout()
        bin_form.addRow("Vertical resolution", self.range_bin)
        bin_form.addRow("Temporal resolution", self.time_bin)
        bin_form.addRow("", self.by_month)
        bin_box = QGroupBox("Binning")
        bin_box.setLayout(bin_form)

        # --- memory -----------------------------------------------------
        self.scheduler = QComboBox()
        self.scheduler.addItems(["synchronous", "threads"])
        self.gc_every = spin(0, 200, 5, 0, 1, " files")
        self.mem_warn = spin(0, 128000, 0, 0, 256, " MB")

        mem_form = QFormLayout()
        mem_form.addRow("Dask scheduler", self.scheduler)
        mem_form.addRow("Collect garbage every", self.gc_every)
        mem_form.addRow("Warn above", self.mem_warn)
        mem_box = QGroupBox("Memory")
        mem_box.setLayout(mem_form)
        mem_hint = QLabel(
            "<span style='color:#666'>Synchronous holds roughly one chunk at a "
            "time — slower, but the lowest and most predictable memory use. "
            "Set the warning to 0 to disable it.</span>")
        mem_hint.setWordWrap(True)
        mem_form.addRow("", mem_hint)

        self.preview = QLabel("Choose a folder of converted .nc files.")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color:#555; padding:6px;")

        # --- assemble (scrollable: the form is tall) -------------------
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(QLabel(
            "<b>Step 2 — Process.</b> Calibrate, mask, denoise and bin. Months are "
            "detected from the filenames; each month becomes one "
            "<code>YYYYMM_&lt;res&gt;.nc</code> product."
        ))
        inner_layout.addWidget(io_box)
        row = QGridLayout()
        row.addWidget(geom_box, 0, 0)
        row.addWidget(env_box, 0, 1)
        inner_layout.addLayout(row)
        inner_layout.addWidget(self.mask_box)
        inner_layout.addWidget(self.noise_box)
        inner_layout.addWidget(bin_box)
        inner_layout.addWidget(mem_box)
        inner_layout.addWidget(self.preview)
        inner_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.footer())

        self.load_from(cfg)

    # -- helpers -------------------------------------------------------
    def _toggle_env(self, on):
        for w in (self.temperature, self.salinity, self.auto_pressure):
            w.setEnabled(on)
        self.pressure.setEnabled(on and not self.auto_pressure.isChecked())

    def _sync_depth_hint(self):
        d = self.mooring_depth.value()
        if self.orientation.currentText() == "upward":
            self.depth_hint.setText(f"depth = {d:g} − echo_range  (0 m = surface)")
        else:
            self.depth_hint.setText(f"depth = {d:g} + echo_range  (increasing downward)")

    def _refresh_preview(self):
        folder = self.input_dir.value()
        if not folder or not Path(folder).is_dir():
            self.preview.setText("Choose a folder of converted .nc files.")
            return
        files = find_nc_files(folder, recursive=True)
        if not files:
            self.preview.setText("<span style='color:#b03030'>No .nc files in this folder.</span>")
            return
        if self.by_month.isChecked():
            groups = group_by_month(files, use_data_fallback=False)
            names = ", ".join(f"{k} ({len(v)})" for k, v in list(groups.items())[:14])
            more = "…" if len(groups) > 14 else ""
            self.preview.setText(
                f"<b>{len(files)}</b> file(s) → <b>{len(groups)}</b> monthly product(s): "
                f"{names}{more}<br>Output → <code>{self.collect().resolved_output_dir()}</code>"
            )
        else:
            self.preview.setText(
                f"<b>{len(files)}</b> file(s) → one combined product.<br>"
                f"Output → <code>{self.collect().resolved_output_dir()}</code>"
            )

    # -- form <-> config ----------------------------------------------
    def load_from(self, cfg: ProcessConfig):
        self.cfg = cfg
        self.input_dir.set_value(cfg.input_dir)
        self.output_dir.set_value(cfg.output_dir)
        self.skip_existing.setChecked(cfg.skip_existing)

        self.mooring_depth.setValue(cfg.geometry.mooring_depth)
        self.orientation.setCurrentText(cfg.geometry.orientation)

        self.use_env.setChecked(cfg.env.use_env_params)
        self.temperature.setValue(cfg.env.temperature)
        self.salinity.setValue(cfg.env.salinity)
        self.auto_pressure.setChecked(cfg.env.pressure is None)
        if cfg.env.pressure is not None:
            self.pressure.setValue(cfg.env.pressure)

        self.mask_box.setChecked(cfg.mask.enabled)
        self.use_keep_min.setChecked(cfg.mask.keep_min is not None)
        self.use_keep_max.setChecked(cfg.mask.keep_max is not None)
        if cfg.mask.keep_min is not None:
            self.keep_min.setValue(cfg.mask.keep_min)
        if cfg.mask.keep_max is not None:
            self.keep_max.setValue(cfg.mask.keep_max)
        self.bands.set_bands(cfg.mask.exclude_bands)

        n = cfg.noise
        self.noise_box.setChecked(n.enabled)
        self.impulse.setChecked(n.impulse)
        self.impulse_thr.setValue(n.impulse_threshold_db)
        self.impulse_bin.setValue(n.impulse_depth_bin_m)
        self.transient.setChecked(n.transient)
        self.transient_thr.setValue(n.transient_threshold_db)
        self.transient_bin.setValue(n.transient_depth_bin_m)
        self.transient_pings.setValue(n.transient_side_pings)
        self.background.setChecked(n.background)
        self.background_snr.setValue(n.background_snr_db)
        self.background_rs.setValue(n.background_range_sample_num)
        self.background_pings.setValue(n.background_ping_num)

        self.range_bin.setValue(cfg.binning.range_bin_m)
        self.time_bin.setCurrentText(cfg.binning.ping_time_bin)
        self.by_month.setChecked(cfg.binning.group_by_month)

        self.scheduler.setCurrentText(cfg.dask_scheduler)
        self.gc_every.setValue(cfg.gc_every)
        self.mem_warn.setValue(cfg.memory_warn_mb)

        self._toggle_env(cfg.env.use_env_params)
        self._sync_depth_hint()
        self._refresh_preview()

    def collect(self) -> ProcessConfig:
        c = self.cfg
        c.input_dir = self.input_dir.value()
        c.output_dir = self.output_dir.value()
        c.skip_existing = self.skip_existing.isChecked()

        c.geometry.mooring_depth = self.mooring_depth.value()
        c.geometry.orientation = self.orientation.currentText()

        c.env.use_env_params = self.use_env.isChecked()
        c.env.temperature = self.temperature.value()
        c.env.salinity = self.salinity.value()
        c.env.pressure = None if self.auto_pressure.isChecked() else self.pressure.value()

        c.mask.enabled = self.mask_box.isChecked()
        c.mask.keep_min = self.keep_min.value() if self.use_keep_min.isChecked() else None
        c.mask.keep_max = self.keep_max.value() if self.use_keep_max.isChecked() else None
        c.mask.exclude_bands = self.bands.bands()

        n = c.noise
        n.enabled = self.noise_box.isChecked()
        n.impulse = self.impulse.isChecked()
        n.impulse_threshold_db = self.impulse_thr.value()
        n.impulse_depth_bin_m = self.impulse_bin.value()
        n.transient = self.transient.isChecked()
        n.transient_threshold_db = self.transient_thr.value()
        n.transient_depth_bin_m = self.transient_bin.value()
        n.transient_side_pings = int(self.transient_pings.value())
        n.background = self.background.isChecked()
        n.background_snr_db = self.background_snr.value()
        n.background_range_sample_num = int(self.background_rs.value())
        n.background_ping_num = int(self.background_pings.value())

        c.binning.range_bin_m = self.range_bin.value()
        c.binning.ping_time_bin = self.time_bin.currentText().strip()
        c.binning.group_by_month = self.by_month.isChecked()

        c.dask_scheduler = self.scheduler.currentText()
        c.gc_every = int(self.gc_every.value())
        c.memory_warn_mb = self.mem_warn.value()
        return c

    # -- job -----------------------------------------------------------
    def validate(self):
        cfg = self.collect()
        if not cfg.input_dir:
            raise ValueError("Select the folder containing your converted .nc files.")
        if not Path(cfg.input_dir).is_dir():
            raise ValueError(f"Folder does not exist:\n{cfg.input_dir}")
        if not find_nc_files(cfg.input_dir, recursive=True):
            raise ValueError("No .nc files found in that folder.")
        if cfg.mask.enabled and cfg.mask.keep_min is not None and cfg.mask.keep_max is not None:
            if cfg.mask.keep_min >= cfg.mask.keep_max:
                raise ValueError("Masking: the upper cut must be shallower than the lower cut.")
        if not cfg.binning.ping_time_bin:
            raise ValueError("Enter a temporal resolution, e.g. 1h.")

    def build_job(self):
        cfg = self.collect()
        return lambda ctx: core_process.run_processing(cfg, ctx)

    def on_success(self, result):
        self.output_dir.set_value(str(result.output_dir))
        self._refresh_preview()
