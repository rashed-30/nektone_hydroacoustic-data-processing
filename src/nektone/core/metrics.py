"""Stage 3 - baseline metrics from binned monthly products.

Three metrics per channel, per month (optionally split into solar day/night
windows in local time, as described in the concept note):

  * Occupied Area (%)  - share of the water column above the biological
    threshold. Reported twice: against *valid* cells (masked samples excluded)
    and against *all* cells (the original notebook's denominator). Use the
    valid-cell version unless you need to reproduce earlier numbers.
  * Mean Sa (dB)       - depth-integrated linear backscatter, then log.
  * Centre of Mass (m) - backscatter-weighted mean depth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import MetricsConfig
from .discovery import find_nc_files
from .jobs import JobContext, Cancelled

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class MetricsResult:
    csv_path: Optional[Path]
    rows: int = 0
    failures: List[str] = None
    cancelled: bool = False

    def __post_init__(self):
        if self.failures is None:
            self.failures = []


def _month_from_name(stem: str):
    digits = "".join(c for c in stem if c.isdigit())
    if len(digits) >= 6:
        try:
            return int(digits[:4]), int(digits[4:6])
        except ValueError:
            pass
    return None, None


def _local_times(ping_time, timezone: str):
    import pandas as pd
    t = pd.DatetimeIndex(pd.to_datetime(ping_time))
    if t.tz is None:
        t = t.tz_localize("UTC")
    if timezone:
        t = t.tz_convert(timezone)
    return t


def _window_mask(hours, start: int, end: int):
    """Inclusive-start, exclusive-end hour window; wraps past midnight."""
    if start <= end:
        return (hours >= start) & (hours < end)
    return (hours >= start) | (hours < end)


def _metrics_for(sv_db, bin_thickness_m: float, threshold_db: float) -> dict:
    import numpy as np

    total_cells = int(sv_db.size)
    valid = sv_db.notnull()
    valid_cells = int(valid.sum().item())
    if valid_cells == 0:
        return {
            "Occupied Area (% valid)": float("nan"),
            "Occupied Area (% all cells)": 0.0,
            "Mean Sa (dB)": -100.0,
            "Centre of Mass (m)": float("nan"),
            "Valid cells": 0,
            "Total cells": total_cells,
        }

    occupied = int((sv_db > threshold_db).sum().item())
    sv_linear = 10 ** (sv_db / 10.0)

    # Depth-integrated backscatter per ping, then averaged over time.
    col_sum = sv_linear.sum(dim="depth", skipna=True) * float(bin_thickness_m)
    mean_linear = float(col_sum.mean(dim="ping_time", skipna=True).item())
    sa_db = 10.0 * np.log10(mean_linear) if mean_linear > 0 else -100.0

    denom = sv_linear.sum(dim="depth", skipna=True)
    weighted = (sv_linear * sv_db["depth"]).sum(dim="depth", skipna=True)
    com_per_ping = weighted.where(denom > 0) / denom.where(denom > 0)
    com = float(com_per_ping.mean(dim="ping_time", skipna=True).item())

    return {
        "Occupied Area (% valid)": 100.0 * occupied / valid_cells,
        "Occupied Area (% all cells)": 100.0 * occupied / total_cells,
        "Mean Sa (dB)": float(sa_db),
        "Centre of Mass (m)": com,
        "Valid cells": valid_cells,
        "Total cells": total_cells,
    }


def run_metrics(cfg: MetricsConfig, ctx: JobContext) -> MetricsResult:
    import numpy as np
    import pandas as pd
    import xarray as xr

    in_dir = Path(cfg.input_dir)
    if not in_dir.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {in_dir}")

    files = find_nc_files(in_dir, recursive=False)
    if not files:
        raise FileNotFoundError(f"No .nc files found in {in_dir}")

    ctx.info(f"Computing metrics over {len(files)} monthly product(s).")
    rows = []
    failures = []
    cancelled = False

    for i, f in enumerate(files, start=1):
        try:
            ctx.raise_if_cancelled()
        except Cancelled:
            cancelled = True
            ctx.warn("Metrics stopped by user.")
            break

        ctx.progress(i - 1, len(files), f.name)
        try:
            with xr.open_dataset(f) as ds:
                ds = ds.load()
                if "Sv" not in ds:
                    raise KeyError("no 'Sv' variable")
                if "depth" not in ds.coords and "depth" not in ds.dims:
                    raise KeyError("no 'depth' coordinate - is this a binned product?")

                year, month = _month_from_name(f.stem)
                depths = np.asarray(ds["depth"].values, dtype=float)
                thickness = float(np.abs(np.diff(depths)).mean()) if depths.size > 1 else 1.0

                periods = [("All", None)]
                if cfg.split_day_night:
                    local = _local_times(ds["ping_time"].values, cfg.timezone)
                    hours = np.asarray(local.hour)
                    periods += [
                        ("Day", _window_mask(hours, cfg.day_start_hour, cfg.day_end_hour)),
                        ("Night", _window_mask(hours, cfg.night_start_hour, cfg.night_end_hour)),
                    ]

                channels = [c for c in ds["channel"].values] if "channel" in ds.dims else [None]

                for channel in channels:
                    sv_all = ds["Sv"] if channel is None else ds["Sv"].sel(channel=channel)
                    for label, mask in periods:
                        sv = sv_all if mask is None else sv_all.isel(ping_time=np.where(mask)[0])
                        if sv.sizes.get("ping_time", 0) == 0:
                            continue
                        m = _metrics_for(sv, thickness, cfg.bio_threshold_db)
                        rows.append({
                            "File": f.name,
                            "Year": year,
                            "Month": month,
                            "Month Name": MONTH_NAMES[month - 1] if month else "",
                            "Channel": str(channel) if channel is not None else "all",
                            "Period": label,
                            "Bin thickness (m)": thickness,
                            **m,
                        })
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{f.name}: {exc}")
            ctx.error(f"{f.name} -> {type(exc).__name__}: {exc}")

    ctx.progress(len(files), len(files), "done")

    if not rows:
        ctx.warn("No metrics produced.")
        return MetricsResult(csv_path=None, rows=0, failures=failures, cancelled=cancelled)

    df = pd.DataFrame(rows).sort_values(["Year", "Month", "Channel", "Period"], na_position="last")
    out_csv = Path(cfg.output_csv) if cfg.output_csv else in_dir / "nektone_metrics.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    ctx.ok(f"Wrote {len(df)} row(s) to {out_csv}")
    return MetricsResult(csv_path=out_csv, rows=len(df), failures=failures, cancelled=cancelled)
