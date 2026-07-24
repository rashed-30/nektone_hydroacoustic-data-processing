"""The main window: four tabs over a shared log pane."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..core.config import AppConfig
from .tab_convert import ConvertTab
from .tab_metrics import MetricsTab
from .tab_process import ProcessTab
from .tab_viewer import ViewerTab
from .widgets import LogConsole

ORG = "NekTone"
APP = "NekTone"


def user_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "NekTone"
    path.mkdir(parents=True, exist_ok=True)
    return path


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NekTone — AZFP processing pipeline  v{__version__}")
        self.resize(1180, 860)

        self.settings_path = user_data_dir() / "settings.json"
        self.config = self._load_config()

        self.log = LogConsole()
        self.log.attach_file(user_data_dir() / "logs" / "nektone.log")

        self.convert_tab = ConvertTab(self.config.convert)
        self.process_tab = ProcessTab(self.config.process)
        self.metrics_tab = MetricsTab(self.config.metrics)
        self.viewer_tab = ViewerTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.convert_tab, "1 · Convert")
        self.tabs.addTab(self.process_tab, "2 · Process && bin")
        self.tabs.addTab(self.metrics_tab, "3 · Metrics")
        self.tabs.addTab(self.viewer_tab, "Echogram viewer")

        for tab in (self.convert_tab, self.process_tab, self.metrics_tab, self.viewer_tab):
            tab.log_message.connect(self.log.append)
            tab.busy_changed.connect(self._on_busy)

        self.convert_tab.run_button.clicked.connect(lambda: self.log.append("--- Conversion started ---"))
        self.process_tab.run_button.clicked.connect(lambda: self.log.append("--- Processing started ---"))
        self.metrics_tab.run_button.clicked.connect(lambda: self.log.append("--- Metrics started ---"))

        # Chain the stages together so the user isn't re-typing paths.
        self.convert_tab.busy_changed.connect(self._maybe_chain_convert)
        self.process_tab.busy_changed.connect(self._maybe_chain_process)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(6, 0, 6, 6)
        log_layout.addWidget(QLabel("Log"))
        log_layout.addWidget(self.log)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(log_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 200])
        self.setCentralWidget(splitter)

        self._build_menu()
        self.statusBar().showMessage("Ready")
        self._restore_geometry()
        self.log.append(f"NekTone {__version__} started. Settings: {self.settings_path}", "info")

    # -- menus ---------------------------------------------------------
    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        save = QAction("Save settings as…", self)
        save.triggered.connect(self._save_settings_as)
        file_menu.addAction(save)

        load = QAction("Load settings…", self)
        load.triggered.connect(self._load_settings_from)
        file_menu.addAction(load)

        reset = QAction("Reset to defaults", self)
        reset.triggered.connect(self._reset_settings)
        file_menu.addAction(reset)

        file_menu.addSeparator()
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        logs = QAction("Open log folder", self)
        logs.triggered.connect(lambda: self._open_path(user_data_dir() / "logs"))
        help_menu.addAction(logs)

        diag = QAction("Diagnostics…", self)
        diag.triggered.connect(self._diagnostics)
        help_menu.addAction(diag)

        about = QAction("About NekTone", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _about(self):
        try:
            import echopype
            ep_version = echopype.__version__
        except Exception:  # noqa: BLE001
            ep_version = "not installed"
        QMessageBox.information(
            self, "About NekTone",
            f"<b>NekTone {__version__}</b><br>"
            "A batch GUI for the echopype AZFP processing pipeline.<br><br>"
            f"echopype {ep_version}<br>Python {platform.python_version()}<br><br>"
            "Documentation: https://echopype.readthedocs.io/",
        )

    def _diagnostics(self):
        """Everything needed to explain a crash, in one copyable block."""
        from ..core.echopype_patches import describe, installed_version

        lines = [
            f"NekTone {__version__}",
            f"Python {platform.python_version()} ({platform.machine()})",
            f"{platform.system()} {platform.release()}",
            f"Frozen build: {getattr(sys, 'frozen', False)}",
            f"Data folder: {user_data_dir()}",
            "",
        ]
        for name in ("echopype", "xarray", "numpy", "pandas", "scipy",
                     "dask", "netCDF4", "h5netcdf", "zarr", "matplotlib", "PySide6"):
            try:
                mod = __import__(name)
                lines.append(f"{name:<12} {getattr(mod, '__version__', 'unknown')}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{name:<12} NOT AVAILABLE ({type(exc).__name__})")

        try:
            import psutil
            vm = psutil.virtual_memory()
            lines += ["", f"RAM: {vm.total / 1e9:.1f} GB total, "
                          f"{vm.available / 1e9:.1f} GB available",
                      f"This process: {psutil.Process().memory_info().rss / 1e6:.0f} MB"]
        except Exception:  # noqa: BLE001
            lines += ["", "psutil not installed - memory reporting disabled"]

        lines += ["", f"echopype installed: {installed_version()}", describe()]

        text = "\n".join(lines)
        box = QMessageBox(self)
        box.setWindowTitle("Diagnostics")
        box.setText("Paste this into a bug report.")
        box.setDetailedText(text)
        box.setStandardButtons(QMessageBox.Ok)
        copy = box.addButton("Copy", QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is copy:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.log.append("Diagnostics copied to clipboard.", "success")

    @staticmethod
    def _open_path(path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:  # noqa: BLE001
            pass

    # -- stage chaining ------------------------------------------------
    def _maybe_chain_convert(self, busy: bool):
        if busy:
            return
        out = self.convert_tab.output_dir.value()
        if out and not self.process_tab.input_dir.value():
            self.process_tab.input_dir.set_value(out)
            self.log.append(f"Process tab input set to {out}", "info")

    def _maybe_chain_process(self, busy: bool):
        if busy:
            return
        out = self.process_tab.output_dir.value()
        if out and not self.metrics_tab.input_dir.value():
            self.metrics_tab.input_dir.set_value(out)

    # -- busy lock -----------------------------------------------------
    def _on_busy(self, busy: bool):
        """Only one job at a time: netCDF/HDF5 access from two threads is a
        classic source of hard crashes."""
        current = self.tabs.currentIndex()
        for i in range(self.tabs.count()):
            if i != current:
                self.tabs.setTabEnabled(i, not busy)
        self.statusBar().showMessage("Working…" if busy else "Ready")

    # -- settings ------------------------------------------------------
    def _load_config(self) -> AppConfig:
        if self.settings_path.exists():
            try:
                return AppConfig.load(self.settings_path)
            except Exception:  # noqa: BLE001
                pass
        return AppConfig()

    def _collect_config(self) -> AppConfig:
        self.convert_tab.collect()
        self.process_tab.collect()
        self.metrics_tab.collect()
        return self.config

    def _save_settings_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save settings", str(Path.home() / "nektone_settings.json"),
            "JSON (*.json)")
        if path:
            try:
                self._collect_config().save(path)
                self.log.append(f"Settings saved to {path}", "success")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save failed", str(exc))

    def _load_settings_from(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load settings", str(Path.home()), "JSON (*.json)")
        if not path:
            return
        try:
            cfg = AppConfig.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self._apply_config(cfg)
        self.log.append(f"Settings loaded from {path}", "success")

    def _reset_settings(self):
        if QMessageBox.question(self, "Reset", "Restore all default settings?") == QMessageBox.Yes:
            self._apply_config(AppConfig())
            self.log.append("Settings reset to defaults.", "info")

    def _apply_config(self, cfg: AppConfig):
        self.config = cfg
        self.convert_tab.load_from(cfg.convert)
        self.process_tab.load_from(cfg.process)
        self.metrics_tab.load_from(cfg.metrics)

    # -- window state --------------------------------------------------
    def _restore_geometry(self):
        s = QSettings(ORG, APP)
        geom = s.value("geometry")
        if geom:
            self.restoreGeometry(geom)

    def closeEvent(self, event):
        running = any(
            getattr(t, "is_running", False)
            for t in (self.convert_tab, self.process_tab, self.metrics_tab, self.viewer_tab)
        )
        if running:
            answer = QMessageBox.question(
                self, "Job in progress",
                "A job is still running. Stop it and quit?\n\n"
                "Files already written are safe; the current one will be discarded.",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for tab in (self.convert_tab, self.process_tab, self.metrics_tab):
                if getattr(tab, "is_running", False):
                    tab.stop()
            for tab in (self.convert_tab, self.process_tab, self.metrics_tab):
                worker = getattr(tab, "_worker", None)
                if worker is not None:
                    worker.wait(15000)

        try:
            self._collect_config().save(self.settings_path)
        except Exception:  # noqa: BLE001
            pass
        QSettings(ORG, APP).setValue("geometry", self.saveGeometry())
        self.viewer_tab.shutdown()
        self.log.close_file()
        event.accept()
