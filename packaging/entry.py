"""Frozen-application entry point.

PyInstaller executes its entry script as a **top-level module**, not as part of
a package. That makes `src/nektone/__main__.py` unusable as an entry point: its
`from .app import main` has no parent package to resolve against, and the frozen
app dies with

    ImportError: attempted relative import with no known parent package

`python -m nektone` works because `-m` establishes the package context; the
frozen launcher gets no such thing. So this file lives *outside* the package and
imports it absolutely.

`--selftest` imports every module the app needs and exits, without opening a
window. CI runs the frozen binary this way, which exercises the real packaged
import graph — the only reliable way to catch a missing hidden import before a
user does.
"""
from __future__ import annotations

import multiprocessing
import sys

from nektone.app import main

SELFTEST_MODULES = [
    # the application itself
    "nektone",
    "nektone.app",
    "nektone.cli",
    "nektone.core.config",
    "nektone.core.convert",
    "nektone.core.crashlog",
    "nektone.core.discovery",
    "nektone.core.echopype_patches",
    "nektone.core.jobs",
    "nektone.core.metrics",
    "nektone.core.process",
    "nektone.gui.base_tab",
    "nektone.gui.main_window",
    "nektone.gui.tab_convert",
    "nektone.gui.tab_process",
    "nektone.gui.tab_metrics",
    "nektone.gui.tab_viewer",
    "nektone.gui.widgets",
    "nektone.gui.worker",
    # the dependencies most likely to be missing from a frozen build
    "echopype",
    "xarray",
    "xarray.backends.netCDF4_",
    "netCDF4",
    "h5netcdf",
    "zarr",
    "dask.array",
    "scipy.signal",
    "pandas",
    "numpy",
    "matplotlib.backends.backend_qtagg",
    "PySide6.QtWidgets",
]


def selftest() -> int:
    """Import everything, report, and exit. No window is created.

    A windowed (console=False) build has no stdout on Windows, so the report is
    also written to nektone-selftest.log beside the working directory; CI reads
    that file. Without it, a self-test failure in a frozen GUI build would be
    completely silent.
    """
    import importlib
    from pathlib import Path

    lines = [
        f"NekTone self-test (frozen={getattr(sys, 'frozen', False)})",
        f"Python {sys.version.split()[0]}",
        "",
    ]

    failures = []
    for name in SELFTEST_MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            lines.append(f"  FAIL  {name}  ({type(exc).__name__}: {exc})")
        else:
            version = getattr(module, "__version__", "")
            lines.append(f"  ok    {name}{'  ' + version if version else ''}")

    if failures:
        lines += [
            "",
            f"{len(failures)} module(s) failed to import: {', '.join(failures)}",
            "Add the missing name(s) to `hiddenimports` in packaging/nektone.spec.",
        ]
    else:
        lines += ["", f"All {len(SELFTEST_MODULES)} modules imported successfully."]

    report = "\n".join(lines)
    try:
        print(report)
    except Exception:  # noqa: BLE001
        pass  # no console in a windowed build
    try:
        Path("nektone-selftest.log").write_text(report, encoding="utf-8")
    except OSError:
        pass

    return 1 if failures else 0


if __name__ == "__main__":
    # Must come before anything that could spawn a process, or a frozen build
    # will relaunch its own window in a loop.
    multiprocessing.freeze_support()

    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
