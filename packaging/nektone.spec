# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NekTone.

Run from the repository root:

    pyinstaller packaging/nektone.spec --noconfirm

PyInstaller is not a cross-compiler: build the Windows .exe on Windows.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
# NOT src/nektone/__main__.py: PyInstaller runs the entry script as a
# top-level module, so its relative imports have no parent package and the
# frozen app dies with "attempted relative import with no known parent
# package". packaging/entry.py imports the package absolutely instead.
ENTRY = ROOT / "packaging" / "entry.py"

# --- data files that must travel with the app --------------------------
datas = []
for pkg in ("echopype", "xarray", "zarr", "numcodecs", "dask", "distributed"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

# --- imports PyInstaller's static analysis cannot see ------------------
hiddenimports = []
for pkg in ("nektone", "echopype", "xarray", "zarr", "numcodecs"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

hiddenimports += [
    # NetCDF / HDF5 backends: selected by string at runtime, so never traced.
    "netCDF4", "netCDF4.utils", "h5netcdf", "h5py", "h5py.defs",
    "h5py.utils", "h5py._proxy", "cftime",
    "xarray.backends.netCDF4_", "xarray.backends.h5netcdf_",
    "xarray.backends.zarr", "xarray.backends.scipy_",
    # scientific stack
    "scipy.special.cython_special", "scipy._lib.messagestream",
    "scipy.spatial.transform._rotation_groups",
    "pandas._libs.tslibs.base", "numpy.core._dtype_ctypes",
    "dask.array", "dask.dataframe",
    # plotting
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_agg",
    # timezone database used by the solar-window metrics
    "tzdata", "zoneinfo",
]

excludes = [
    "PyQt5", "PyQt6", "PySide2", "tkinter", "test", "tests",
    "IPython", "jupyter", "notebook", "ipywidgets", "sphinx", "pytest",
    "matplotlib.backends.backend_webagg",
]

block_cipher = None

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = ROOT / "packaging" / "nektone.ico"
icon_arg = str(icon) if icon.exists() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NekTone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX corrupts some scientific DLLs - leave it off
    console=False,          # set True temporarily if the app won't start
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NekTone",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="NekTone.app",
        icon=icon_arg,
        bundle_identifier="org.nektone.app",
        info_plist={"NSHighResolutionCapable": True},
    )
