"""Core tests. None of these import echopype, so they run anywhere."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nektone.core.config import AppConfig, ProcessConfig  # noqa: E402
from nektone.core.discovery import group_by_month, month_key_from_name  # noqa: E402
from nektone.core.metrics import _metrics_for, _window_mask  # noqa: E402
from nektone.core.process import _normalise_time_bin, apply_masks  # noqa: E402


# --- discovery ---------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("23040100.nc", "202304"),
    ("17111812.nc", "201711"),
    ("19123123.nc", "201912"),
    ("garbage.nc", None),
    ("23990100.nc", None),          # month 99 is not a month
])
def test_month_key_from_name(name, expected):
    assert month_key_from_name(name) == expected


def test_group_by_month_orders_and_buckets():
    files = ["23050101.nc", "23040100.nc", "23040101.nc"]
    groups = group_by_month(files, use_data_fallback=False)
    assert list(groups) == ["202304", "202305"]
    assert [p.name for p in groups["202304"]] == ["23040100.nc", "23040101.nc"]


# --- config ------------------------------------------------------------

def test_config_round_trip(tmp_path):
    cfg = AppConfig()
    cfg.process.mask.exclude_bands = [(97.0, 102.0), (10.0, 12.0)]
    cfg.process.noise.enabled = False
    cfg.process.binning.range_bin_m = 5.0
    cfg.metrics.timezone = "Asia/Dhaka"

    path = tmp_path / "settings.json"
    cfg.save(path)
    back = AppConfig.load(path)

    assert back.process.mask.exclude_bands == [(97.0, 102.0), (10.0, 12.0)]
    assert back.process.noise.enabled is False
    assert back.process.binning.range_bin_m == 5.0
    assert back.metrics.timezone == "Asia/Dhaka"


def test_depth_geometry_both_orientations():
    cfg = ProcessConfig()
    cfg.geometry.mooring_depth = 160.0
    cfg.geometry.orientation = "upward"
    assert cfg.geometry.depth_from_range(np.array([0.0, 60.0])).tolist() == [160.0, 100.0]
    cfg.geometry.orientation = "downward"
    assert cfg.geometry.depth_from_range(np.array([0.0, 60.0])).tolist() == [160.0, 220.0]


def test_normalise_time_bin():
    assert _normalise_time_bin("1H") == "1h"
    assert _normalise_time_bin("30T") == "30min"
    assert _normalise_time_bin("1h") == "1h"
    assert _normalise_time_bin("1D") == "1D"


# --- masking -----------------------------------------------------------

def _toy_dataset():
    depth = np.arange(0.0, 160.0, 2.0)
    time = pd.date_range("2023-05-01", periods=6, freq="h")
    sv = xr.DataArray(
        np.full((len(time), len(depth)), -70.0),
        coords={"ping_time": time, "depth": depth},
        dims=("ping_time", "depth"),
    )
    return xr.Dataset({"Sv": sv}, coords={"depth": depth})


def test_apply_masks_keep_window_and_bands():
    ds = _toy_dataset()
    cfg = ProcessConfig()
    cfg.mask.keep_min = 10.0
    cfg.mask.keep_max = 150.0
    cfg.mask.exclude_bands = [(97.0, 102.0)]

    out = apply_masks(ds.copy(deep=True), cfg)
    depth = out["depth"]
    kept = out["Sv"].notnull().isel(ping_time=0)

    assert not bool(kept.sel(depth=8.0))       # above keep_min
    assert bool(kept.sel(depth=12.0))
    assert not bool(kept.sel(depth=152.0))     # below keep_max
    assert not bool(kept.sel(depth=98.0))      # inside excluded band
    assert bool(kept.sel(depth=104.0))
    assert depth.size == 80


def test_apply_masks_disabled_is_a_no_op():
    ds = _toy_dataset()
    cfg = ProcessConfig()
    cfg.mask.enabled = False
    cfg.mask.keep_min = 50.0
    out = apply_masks(ds.copy(deep=True), cfg)
    assert bool(out["Sv"].notnull().all())


# --- metrics -----------------------------------------------------------

def test_metrics_all_nan_column_does_not_crash():
    ds = _toy_dataset()
    ds["Sv"] = ds["Sv"] * np.nan
    m = _metrics_for(ds["Sv"], 2.0, -80.0)
    assert m["Valid cells"] == 0
    assert m["Mean Sa (dB)"] == -100.0


def test_metrics_occupied_area_uses_valid_cells():
    ds = _toy_dataset()
    # Mask out the top half entirely, leave the rest above threshold.
    ds["Sv"] = ds["Sv"].where(ds["depth"] >= 80.0)
    m = _metrics_for(ds["Sv"], 2.0, -80.0)
    assert m["Occupied Area (% valid)"] == pytest.approx(100.0)
    assert m["Occupied Area (% all cells)"] == pytest.approx(50.0)


def test_metrics_centre_of_mass_is_between_layers():
    ds = _toy_dataset()
    # One bright layer at 40 m, one at 120 m, everything else silent.
    quiet = xr.full_like(ds["Sv"], -200.0)
    bright = quiet.where(~ds["depth"].isin([40.0, 120.0]), -30.0)
    ds["Sv"] = bright
    m = _metrics_for(ds["Sv"], 2.0, -80.0)
    assert 79.0 < m["Centre of Mass (m)"] < 81.0


def test_window_mask_wraps_past_midnight():
    hours = np.arange(24)
    day = _window_mask(hours, 10, 14)
    night = _window_mask(hours, 22, 2)
    assert hours[day].tolist() == [10, 11, 12, 13]
    assert hours[night].tolist() == [0, 1, 22, 23]


# --- runtime patching --------------------------------------------------

def test_patch_inserts_missing_key_and_leaves_existing_alone():
    import types

    from nektone.core import echopype_patches as ep

    fake = types.ModuleType("fake_parse")
    fake.TABLE = {(38000, 0.1): 1.0}
    sys.modules["fake_parse"] = fake

    assert ep.set_mapping_entry("fake_parse", "TABLE", (200000, 0.2), 9.9) == "applied"
    assert fake.TABLE[(200000, 0.2)] == 9.9

    # re-running is a no-op, so patches are safe to apply on every launch
    assert ep.set_mapping_entry("fake_parse", "TABLE", (200000, 0.2), 9.9) == "already correct"
    assert ep.set_mapping_entry("fake_parse", "TABLE", (38000, 0.1), 5.0) == "already correct"
    assert fake.TABLE[(38000, 0.1)] == 1.0

    # a renamed table or an uninstalled module degrades, never raises
    assert ep.set_mapping_entry("fake_parse", "GONE", (1,), 1) == "not needed (target absent in this version)"
    assert ep.set_mapping_entry("no_such_module", "T", (1,), 1) == "not needed (target absent in this version)"
    del sys.modules["fake_parse"]


def test_apply_all_never_raises():
    from nektone.core import echopype_patches as ep

    broken = ep.Patch(name="deliberately broken", apply=lambda: 1 / 0)
    ep.PATCHES.append(broken)
    try:
        results = ep.apply_all()
        assert any("failed" in outcome for _, outcome in results)
    finally:
        ep.PATCHES.remove(broken)


# --- laziness guard ----------------------------------------------------

def test_is_lazy_detects_dask_backed_data():
    from nektone.core.process import _is_lazy

    ds = _toy_dataset()
    assert _is_lazy(ds) is False
    dask = pytest.importorskip("dask")
    assert _is_lazy(ds.chunk({"ping_time": 2})) is True


# --- crash logging -----------------------------------------------------

def test_crashlog_writes_a_file(tmp_path):
    from nektone.core import crashlog

    path = crashlog.install(tmp_path / "logs")
    assert path.exists()
    crashlog.close()
    assert "session" in path.read_text()


def test_config_round_trip_covers_every_scalar_field():
    """Guards against the whitelist bug: new fields must survive save/load."""
    import dataclasses

    cfg = AppConfig()
    cfg.process.dask_scheduler = "threads"
    cfg.process.gc_every = 11
    cfg.process.memory_warn_mb = 4096.0
    cfg.process.skip_existing = False

    back = AppConfig.from_dict(dataclasses.asdict(cfg))
    for f in dataclasses.fields(cfg.process):
        if f.name in {"env", "geometry", "mask", "noise", "binning"}:
            continue
        assert getattr(back.process, f.name) == getattr(cfg.process, f.name), f.name
