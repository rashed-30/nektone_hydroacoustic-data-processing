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


# --- frozen entry point ------------------------------------------------

def test_frozen_entry_point_uses_absolute_imports():
    """PyInstaller runs the entry script as a top-level module, so a relative
    import there raises 'attempted relative import with no known parent
    package' in the built .exe. Guard against reintroducing one."""
    entry = Path(__file__).resolve().parents[1] / "packaging" / "entry.py"
    assert entry.exists(), "packaging/entry.py is the frozen entry point"

    tree = __import__("ast").parse(entry.read_text(encoding="utf-8"))
    relative = [n for n in __import__("ast").walk(tree)
                if isinstance(n, __import__("ast").ImportFrom) and n.level > 0]
    assert not relative, f"relative imports in the frozen entry point: {relative}"


def test_spec_points_at_the_launcher_not_the_package_dunder_main():
    spec = (Path(__file__).resolve().parents[1] / "packaging" / "nektone.spec").read_text()
    assert 'ROOT / "packaging" / "entry.py"' in spec
    assert '"src" / "nektone" / "__main__.py"' not in spec.split("# NOT")[-1].split("ENTRY =")[-1]


def test_selftest_covers_every_shipped_module():
    """Every nektone module must appear in the frozen self-test, so a new file
    that fails to package is caught by CI rather than by a user."""
    import re

    root = Path(__file__).resolve().parents[1]
    entry = (root / "packaging" / "entry.py").read_text(encoding="utf-8")
    listed = set(re.findall(r'"(nektone[\w.]*)"', entry))

    shipped = set()
    for path in (root / "src" / "nektone").rglob("*.py"):
        if path.name in {"__init__.py", "__main__.py"}:
            continue
        rel = path.relative_to(root / "src").with_suffix("")
        shipped.add(".".join(rel.parts))

    assert not (shipped - listed), f"not covered by the self-test: {sorted(shipped - listed)}"


# --- the AZFP Sv-offset patch -----------------------------------------

def _fake_parse_azfp(with_200us=False):
    """Mimic echopype.convert.parse_azfp.SV_OFFSET: Hz -> microseconds -> dB."""
    import types

    mod = types.ModuleType("echopype.convert.parse_azfp")
    row = {150: 1.4, 250: 1.3, 300: 1.3, 500: 1.25}
    if with_200us:
        row[200] = 9.99
    mod.SV_OFFSET = {
        38000.0: {150: 1.4, 250: 1.3},
        125000.0: {150: 1.4, 250: 1.3},
        200000.0: row,
    }
    sys.modules["echopype.convert.parse_azfp"] = mod
    return mod


def test_azfp_sv_offset_patch_is_registered():
    from nektone.core import echopype_patches as ep

    names = [p.name for p in ep.PATCHES]
    assert any("200 kHz" in n and "Sv offset" in n for n in names), names


def test_azfp_sv_offset_patch_inserts_the_missing_entry():
    from nektone.core import echopype_patches as ep

    mod = _fake_parse_azfp(with_200us=False)
    try:
        assert 200 not in mod.SV_OFFSET[200000.0]
        results = ep.apply_all()
        assert ("AZFP 200 kHz / 200 us Sv offset", "applied") in results
        assert mod.SV_OFFSET[200000.0][200] == 1.35
        # neighbours untouched
        assert mod.SV_OFFSET[200000.0][150] == 1.4
        assert mod.SV_OFFSET[200000.0][250] == 1.3
        # other frequencies untouched
        assert 200 not in mod.SV_OFFSET[38000.0]
    finally:
        del sys.modules["echopype.convert.parse_azfp"]


def test_azfp_patch_defers_to_upstream_if_they_add_the_key():
    """If echopype ships its own 200 us value, ours must not clobber it."""
    from nektone.core import echopype_patches as ep

    mod = _fake_parse_azfp(with_200us=True)
    try:
        ep.apply_all()
        assert mod.SV_OFFSET[200000.0][200] == 9.99
    finally:
        del sys.modules["echopype.convert.parse_azfp"]


def test_azfp_patch_does_not_invent_a_missing_frequency_row():
    """A restructured table must be left alone, not silently fabricated."""
    import types

    from nektone.core import echopype_patches as ep

    mod = types.ModuleType("echopype.convert.parse_azfp")
    mod.SV_OFFSET = {38000.0: {150: 1.4}}          # no 200 kHz row at all
    sys.modules["echopype.convert.parse_azfp"] = mod
    try:
        results = dict(ep.apply_all())
        assert results["AZFP 200 kHz / 200 us Sv offset"].startswith("not needed")
        assert 200000.0 not in mod.SV_OFFSET
    finally:
        del sys.modules["echopype.convert.parse_azfp"]


def test_patch_provenance_lands_in_output_attributes():
    from nektone.core.process import _patch_provenance

    attrs = _patch_provenance([("AZFP 200 kHz / 200 us Sv offset", "applied")])
    assert "200 kHz" in attrs["nektone_echopype_patches"]
    assert "interpolated" in attrs["nektone_sv_offset_note"]
    assert _patch_provenance([])["nektone_echopype_patches"] == "none"


# --- packaging: metadata, not just modules -----------------------------

def test_spec_copies_metadata_for_flox():
    """`import flox` can succeed in a frozen build while its .dist-info is
    absent, which fails as "No package metadata was found for flox" inside
    compute_MVBS. copy_metadata is the fix; make sure it stays."""
    spec = (Path(__file__).resolve().parents[1] / "packaging" / "nektone.spec").read_text()
    assert "copy_metadata" in spec
    metadata_block = spec.split("copy_metadata(")[0]
    assert '"flox"' in metadata_block, "flox must be in the copy_metadata loop"


def test_flox_is_a_declared_dependency():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert "flox" in pyproject, "compute_MVBS requires flox; declare it explicitly"


def test_selftest_verifies_metadata_not_only_imports():
    entry = (Path(__file__).resolve().parents[1] / "packaging" / "entry.py").read_text()
    assert "SELFTEST_METADATA" in entry
    assert "importlib.metadata" in entry or "from importlib.metadata import version" in entry
    assert '"flox",' in entry


def test_binning_backend_check_returns_none_or_a_string():
    from nektone.core.process import check_binning_backend

    result = check_binning_backend()
    assert result is None or isinstance(result, str)
    if isinstance(result, str):
        assert "flox" in result
