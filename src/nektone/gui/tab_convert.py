"""Tab 1 - raw instrument files to converted NetCDF."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout,
)

from ..core import convert as core_convert
from ..core.config import ConvertConfig
from ..core.discovery import find_raw_files, find_xml, format_bytes
from .base_tab import JobTab
from .widgets import PathPicker, check

RAW_EXTENSIONS = [".01A", ".azfp", ".raw"]
SONAR_MODELS = ["AZFP", "AZFP6", "EK60", "EK80"]


class ConvertTab(JobTab):
    run_label = "Convert raw files"

    def __init__(self, cfg: ConvertConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg

        self.input_dir = PathPicker("dir", "Select deployment folder")
        self.input_dir.changed.connect(self._refresh_preview)
        self.output_dir = PathPicker("dir", "Select output folder")
        self.xml_path = PathPicker("file", "Select AZFP master XML", "XML files (*.xml *.XML)")
        self.xml_path.changed.connect(self._refresh_preview)

        self.model = QComboBox()
        self.model.addItems(SONAR_MODELS)
        self.model.currentTextChanged.connect(self._refresh_preview)

        self.extension = QComboBox()
        self.extension.setEditable(True)
        self.extension.addItems(RAW_EXTENSIONS)

        self.recursive = check("Include subfolders (per-month folders inside the deployment)", True)
        self.recursive.stateChanged.connect(self._refresh_preview)
        self.skip_existing = check("Skip files already converted (safe to resume)", True)
        self.flatten = check("Write all .nc into one flat folder", True)
        self.extension.currentTextChanged.connect(self._refresh_preview)

        form = QFormLayout()
        form.addRow("Deployment folder", self.input_dir)
        form.addRow("Output folder", self.output_dir)
        form.addRow("Raw file type", self.extension)
        form.addRow("Instrument", self.model)
        form.addRow("Master XML", self.xml_path)

        options = QGroupBox("Options")
        opt_layout = QVBoxLayout(options)
        opt_layout.addWidget(self.recursive)
        opt_layout.addWidget(self.skip_existing)
        opt_layout.addWidget(self.flatten)

        self.preview = QLabel("Choose a deployment folder to begin.")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color:#555; padding:6px;")

        box = QGroupBox("Input")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Step 1 — Convert.</b> Point at one deployment folder. Files are "
            "found recursively, so per-month subfolders and flat folders both work.<br>"
            "Output defaults to <code>&lt;folder&gt;_converted</code> next to the input."
        ))
        layout.addWidget(box)
        layout.addWidget(options)
        layout.addWidget(self.preview)
        layout.addStretch(1)
        layout.addWidget(self.footer())

        self.load_from(cfg)

    # -- form <-> config ----------------------------------------------
    def load_from(self, cfg: ConvertConfig):
        self.cfg = cfg
        self.input_dir.set_value(cfg.input_dir)
        self.output_dir.set_value(cfg.output_dir)
        self.xml_path.set_value(cfg.xml_path)
        self.extension.setCurrentText(cfg.raw_extension)
        self.model.setCurrentText(cfg.sonar_model)
        self.recursive.setChecked(cfg.recursive)
        self.skip_existing.setChecked(cfg.skip_existing)
        self.flatten.setChecked(cfg.flatten_output)
        self._refresh_preview()

    def collect(self) -> ConvertConfig:
        self.cfg.input_dir = self.input_dir.value()
        self.cfg.output_dir = self.output_dir.value()
        self.cfg.xml_path = self.xml_path.value()
        self.cfg.raw_extension = self.extension.currentText().strip()
        self.cfg.sonar_model = self.model.currentText()
        self.cfg.recursive = self.recursive.isChecked()
        self.cfg.skip_existing = self.skip_existing.isChecked()
        self.cfg.flatten_output = self.flatten.isChecked()
        return self.cfg

    # -- preview -------------------------------------------------------
    def _refresh_preview(self):
        folder = self.input_dir.value()
        if not folder or not Path(folder).is_dir():
            self.preview.setText("Choose a deployment folder to begin.")
            return
        ext = self.extension.currentText().strip() or ".01A"
        files = find_raw_files(folder, ext, self.recursive.isChecked())
        if not files:
            self.preview.setText(
                f"<span style='color:#b03030'>No <code>{ext}</code> files found in this folder"
                f"{' or its subfolders' if self.recursive.isChecked() else ''}.</span>"
            )
            return
        total = sum(f.stat().st_size for f in files[:2000])
        subfolders = len({f.parent for f in files})
        xml = find_xml(folder, self.xml_path.value())
        xml_note = (f"master XML: <code>{xml.name}</code>" if xml
                    else "<span style='color:#b03030'>no XML found</span>")
        if not self.model.currentText().upper().startswith("AZFP"):
            xml_note = "XML not required for this instrument"
        self.preview.setText(
            f"<b>{len(files)}</b> file(s) across <b>{subfolders}</b> folder(s), "
            f"≈{format_bytes(total)} — {xml_note}<br>"
            f"Output → <code>{self.collect().resolved_output_dir()}</code>"
        )

    # -- job -----------------------------------------------------------
    def validate(self):
        cfg = self.collect()
        if not cfg.input_dir:
            raise ValueError("Select the deployment folder containing your raw files.")
        if not Path(cfg.input_dir).is_dir():
            raise ValueError(f"Folder does not exist:\n{cfg.input_dir}")
        if not find_raw_files(cfg.input_dir, cfg.raw_extension, cfg.recursive):
            raise ValueError(f"No '{cfg.raw_extension}' files found in that folder.")
        if cfg.sonar_model.upper().startswith("AZFP") and find_xml(cfg.input_dir, cfg.xml_path) is None:
            raise ValueError(
                "No AZFP master .XML file was found.\n\n"
                "Put the instrument XML in the deployment folder, or pick it manually."
            )

    def build_job(self):
        cfg = self.collect()
        return lambda ctx: core_convert.run_conversion(cfg, ctx)

    def on_success(self, result):
        self.output_dir.set_value(str(result.output_dir))
        self._refresh_preview()
