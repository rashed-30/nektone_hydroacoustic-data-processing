"""Headless runner - the same pipeline without Qt.

Useful for overnight batches, for reproducing a run from a saved settings file,
and for debugging: if `nektone-cli` works but the GUI does not, the problem is
in the interface, not the science.

    nektone-cli convert  DEPLOY_FOLDER
    nektone-cli process  CONVERTED_FOLDER --settings my_settings.json
    nektone-cli metrics  PRODUCTS_FOLDER
    nektone-cli all      DEPLOY_FOLDER --settings my_settings.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core.config import AppConfig
from .core.convert import run_conversion
from .core.jobs import console_context
from .core.metrics import run_metrics
from .core.process import run_processing


def _load(settings: str | None) -> AppConfig:
    if settings:
        return AppConfig.load(settings)
    return AppConfig()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nektone-cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["convert", "process", "metrics", "all", "patches", "doctor"])
    p.add_argument("folder", nargs="?", default=".", help="Input folder for the chosen stage.")
    p.add_argument("--settings", help="JSON settings file saved from the GUI.")
    p.add_argument("--output", help="Override the output folder.")
    p.add_argument("--xml", help="AZFP master XML (auto-detected if omitted).")
    p.add_argument("--range-bin", type=float, help="Vertical resolution in metres.")
    p.add_argument("--time-bin", help="Temporal resolution, e.g. 1h.")
    p.add_argument("--no-noise", action="store_true", help="Skip noise removal.")
    p.add_argument("--no-mask", action="store_true", help="Skip vertical masking.")
    return p


def _doctor() -> int:
    """Report the environment. Run this first when something crashes."""
    import platform

    from .core.echopype_patches import describe, installed_version

    print(f"Python {platform.python_version()} on {platform.system()} {platform.release()}")
    for name in ("echopype", "xarray", "numpy", "pandas", "scipy", "dask",
                 "netCDF4", "h5netcdf", "zarr", "matplotlib", "PySide6", "psutil"):
        try:
            mod = __import__(name)
            print(f"  {name:<12} {getattr(mod, '__version__', 'unknown')}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<12} NOT AVAILABLE ({type(exc).__name__})")
    print(f"\nechopype: {installed_version()}")
    print(describe())
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.stage in ("patches", "doctor"):
        return _doctor()

    cfg = _load(args.settings)
    ctx = console_context()
    folder = str(Path(args.folder).expanduser().resolve())

    if args.xml:
        cfg.convert.xml_path = args.xml
    if args.range_bin is not None:
        cfg.process.binning.range_bin_m = args.range_bin
    if args.time_bin:
        cfg.process.binning.ping_time_bin = args.time_bin
    if args.no_noise:
        cfg.process.noise.enabled = False
    if args.no_mask:
        cfg.process.mask.enabled = False

    try:
        if args.stage in ("convert", "all"):
            cfg.convert.input_dir = folder
            if args.output and args.stage == "convert":
                cfg.convert.output_dir = args.output
            result = run_conversion(cfg.convert, ctx)
            cfg.process.input_dir = str(result.output_dir)

        if args.stage == "process":
            cfg.process.input_dir = folder
        if args.stage in ("process", "all"):
            if args.output and args.stage != "all":
                cfg.process.output_dir = args.output
            result = run_processing(cfg.process, ctx)
            cfg.metrics.input_dir = str(result.output_dir)

        if args.stage == "metrics":
            cfg.metrics.input_dir = folder
        if args.stage in ("metrics", "all"):
            if args.output:
                cfg.metrics.output_csv = args.output
            run_metrics(cfg.metrics, ctx)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        ctx.exception("Fatal", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
