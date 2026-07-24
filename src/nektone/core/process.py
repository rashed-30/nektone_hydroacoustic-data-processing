"""Stage 2 - calibrate, mask, denoise, bin, and concatenate into monthly files.

Mirrors `nekt_bin.py`. Two things are different by design:

1.  Every echopype call goes through `_call_supported`, which drops keyword
    arguments the installed version doesn't accept. echopype's cleaning API has
    churned across releases; this keeps the app running instead of raising
    TypeError halfway through a month.
2.  Masking is expressed as a keep-window plus arbitrary exclude bands, so the
    "surface / bottom / bad line" trio generalises to any instrument geometry.
"""
from __future__ import annotations

import gc
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import ProcessConfig
from .discovery import find_nc_files, group_by_month
from .echopype_patches import apply_all as apply_echopype_patches
from .jobs import JobContext, Cancelled


# ---------------------------------------------------------------------------
# echopype version-compatibility helpers
# ---------------------------------------------------------------------------

def _call_supported(fn, *args, **kwargs):
    """Call `fn`, silently dropping kwargs it does not declare."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **kwargs)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(*args, **allowed)


def _resolve_background_fn():
    """Find remove_background_noise across echopype layouts / dev branches."""
    import echopype as ep
    candidates = []
    try:
        candidates.append(ep.clean.remove_background_noise)
    except AttributeError:
        pass
    try:
        from echopype.clean.api import remove_background_noise as f  # type: ignore
        candidates.append(f)
    except Exception:
        pass
    try:
        from echopype_dev.echopype.clean.api import remove_background_noise as f  # type: ignore
        candidates.append(f)
    except Exception:
        pass
    return candidates[0] if candidates else None


def _is_lazy(ds) -> bool:
    """True if any variable is still a dask graph."""
    try:
        return any(hasattr(v.data, "dask") for v in ds.data_vars.values())
    except Exception:  # noqa: BLE001
        return False


def configure_dask(mode: str, ctx=None) -> None:
    """Pick a dask scheduler for this run.

    'synchronous' keeps peak memory at roughly one chunk and makes tracebacks
    readable; the threaded scheduler is faster but can hold several chunks per
    worker at once, which is what pushes a 32-bit-ish memory ceiling over on
    long AZFP months.
    """
    try:
        import dask
        if mode == "synchronous":
            dask.config.set(scheduler="synchronous")
        else:
            dask.config.set(scheduler="threads")
        if ctx:
            ctx.info(f"dask scheduler: {mode}")
    except Exception:  # noqa: BLE001
        pass


def check_binning_backend() -> Optional[str]:
    """Verify flox is usable before a long batch starts.

    echopype.commongrid.compute_MVBS calls flox.xarray.xarray_reduce. In a
    frozen build flox's code can be present while its .dist-info is not, so
    `import flox` succeeds and the version lookup then fails deep inside the
    first file. Checking up front turns a cryptic mid-batch error into a
    message that says what to do. Returns None if fine, else an explanation.
    """
    try:
        import flox  # noqa: F401
        import flox.xarray  # noqa: F401
    except ImportError as exc:
        return (f"The binning backend 'flox' is not available ({exc}).\n\n"
                "echopype needs it for compute_MVBS. Install it with:\n"
                "    pip install flox")
    try:
        from importlib.metadata import version
        version("flox")
    except Exception:  # noqa: BLE001
        return ("flox is installed but its package metadata is missing "
                "(\"No package metadata was found for flox\").\n\n"
                "This is a packaging fault in a frozen build, not a problem "
                "with your data. Rebuild with copy_metadata('flox') present in "
                "packaging/nektone.spec, or run from source instead.")
    return None


def _rss_mb() -> Optional[float]:
    """Resident memory in MB, if psutil is available."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _normalise_time_bin(value: str) -> str:
    """pandas >= 2.2 deprecates 'H'/'T'/'S' in favour of lowercase aliases."""
    v = str(value).strip()
    for old, new in (("H", "h"), ("T", "min"), ("S", "s")):
        if v.endswith(old) and v[:-1].replace(".", "", 1).isdigit():
            return v[:-len(old)] + new
    return v


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def calibrate(ed, cfg: ProcessConfig):
    import echopype as ep
    env_params = None
    if cfg.env.use_env_params:
        pressure = cfg.env.pressure
        if pressure is None:
            pressure = cfg.geometry.mooring_depth * 1.01
        env_params = {
            "temperature": float(cfg.env.temperature),
            "salinity": float(cfg.env.salinity),
            "pressure": float(pressure),
        }
    return _call_supported(ep.calibrate.compute_Sv, ed, env_params=env_params)


def assign_depth(ds_Sv, cfg: ProcessConfig):
    """Turn instrument-relative echo_range into true water-column depth."""
    if "echo_range" in ds_Sv.coords:
        ds_Sv = ds_Sv.reset_coords("echo_range")
    if "echo_range" not in ds_Sv.variables:
        raise KeyError("Calibrated dataset has no 'echo_range' - cannot compute depth.")
    if "depth" in ds_Sv.coords:
        ds_Sv = ds_Sv.drop_vars("depth")
    elif "depth" in ds_Sv.variables:
        ds_Sv = ds_Sv.drop_vars("depth")
    depth = cfg.geometry.depth_from_range(ds_Sv["echo_range"])
    return ds_Sv.assign_coords(depth=depth)


def apply_masks(ds_Sv, cfg: ProcessConfig):
    m = cfg.mask
    if not m.enabled:
        return ds_Sv
    depth = ds_Sv["depth"]
    sv = ds_Sv["Sv"]
    if m.keep_min is not None:
        sv = sv.where(depth > float(m.keep_min))
    if m.keep_max is not None:
        sv = sv.where(depth < float(m.keep_max))
    for lo, hi in (m.exclude_bands or []):
        lo, hi = float(min(lo, hi)), float(max(lo, hi))
        sv = sv.where((depth < lo) | (depth > hi))
    ds_Sv["Sv"] = sv
    return ds_Sv


def _apply_mask_array(ds_Sv, mask):
    """mask is True where noise -> those samples become NaN."""
    mask = mask.transpose(*ds_Sv["Sv"].dims)
    ds_Sv["Sv"] = ds_Sv["Sv"].where(~mask.fillna(False).astype(bool).values)
    return ds_Sv


def remove_noise(ds_Sv, cfg: ProcessConfig, ctx: JobContext):
    import echopype as ep
    import xarray as xr

    n = cfg.noise
    if not n.enabled:
        return ds_Sv

    if n.impulse:
        mask = _call_supported(
            ep.clean.mask_impulse_noise,
            ds_Sv,
            impulse_noise_threshold=f"{n.impulse_threshold_db}dB",
            depth_bin=f"{n.impulse_depth_bin_m}m",
            range_var="echo_range",
            use_index_binning=True,
        )
        ds_Sv = _apply_mask_array(ds_Sv, mask)
        del mask

    if n.transient:
        mask = _call_supported(
            ep.clean.mask_transient_noise,
            ds_Sv,
            transient_noise_threshold=f"{n.transient_threshold_db}dB",
            depth_bin=f"{n.transient_depth_bin_m}m",
            num_side_pings=int(n.transient_side_pings),
            range_var="echo_range",
            use_index_binning=True,
        )
        ds_Sv = _apply_mask_array(ds_Sv, mask)
        del mask

    if n.background:
        bg_fn = _resolve_background_fn()
        if bg_fn is None:
            ctx.warn("remove_background_noise unavailable in this echopype build - skipped.")
            return ds_Sv

        # Build a minimal dataset: the function is picky about extra variables.
        ds_tmp = xr.Dataset({"Sv": ds_Sv["Sv"]}).assign_coords(echo_range=ds_Sv["echo_range"])
        if "sound_absorption" in ds_Sv.variables:
            ds_tmp["sound_absorption"] = ds_Sv["sound_absorption"]
        if "frequency_nominal" not in ds_tmp.variables:
            freqs = _frequencies_from(ds_Sv)
            if freqs is not None:
                ds_tmp = ds_tmp.assign_coords(frequency_nominal=("channel", freqs))

        ds_clean = _call_supported(
            bg_fn,
            ds_tmp,
            range_sample_num=int(n.background_range_sample_num),
            ping_num=int(n.background_ping_num),
            SNR_threshold=f"{n.background_snr_db}dB",
        )
        var = next((v for v in ("Sv_corrected", "Sv_clean", "Sv") if v in ds_clean), None)
        if var is None:
            ctx.warn("Background noise removal returned no Sv variable - skipped.")
        else:
            ds_Sv["Sv"] = ds_Sv["Sv"].copy(
                data=ds_clean[var].transpose(*ds_Sv["Sv"].dims).values
            )
        del ds_tmp, ds_clean

    return ds_Sv


def _frequencies_from(ds) -> Optional[list]:
    """Best-effort nominal frequencies in Hz, for older cleaning APIs."""
    if "frequency_nominal" in ds.variables:
        return [float(v) for v in ds["frequency_nominal"].values]
    out = []
    for ch in ds.channel.values:
        try:
            token = str(ch).split("-")[1]
            out.append(float(token) * 1000.0)
        except (IndexError, ValueError):
            return None
    return out or None


def bin_dataset(ds_Sv, cfg: ProcessConfig):
    import echopype as ep
    b = cfg.binning
    return _call_supported(
        ep.commongrid.compute_MVBS,
        ds_Sv,
        range_var="depth",
        range_bin=f"{b.range_bin_m}m",
        ping_time_bin=_normalise_time_bin(b.ping_time_bin),
    )


def process_one_file(path: Path, cfg: ProcessConfig, ctx: JobContext):
    """Full per-file chain: open -> calibrate -> depth -> mask -> denoise -> bin."""
    import echopype as ep
    ed = None
    ds_Sv = None
    try:
        ed = ep.open_converted(str(path))
        ds_Sv = calibrate(ed, cfg)
        ds_Sv = assign_depth(ds_Sv, cfg)
        ds_Sv = apply_masks(ds_Sv, cfg)
        ctx.raise_if_cancelled()
        ds_Sv = remove_noise(ds_Sv, cfg, ctx)
        ctx.raise_if_cancelled()
        mvbs = bin_dataset(ds_Sv, cfg)
        # Critical: compute *before* the finally block closes the source file.
        # compute_MVBS can return a lazy dask graph that still points at `ed`;
        # returning it un-computed means the concat at the end of the month
        # reads through a closed HDF5 handle, which segfaults rather than
        # raising. Loading here also caps open file handles at one, instead of
        # one per hourly file held in the month list.
        return mvbs.compute() if _is_lazy(mvbs) else mvbs.load()
    finally:
        for obj in (ds_Sv, ed):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        del ds_Sv, ed


# ---------------------------------------------------------------------------
# Batch driver
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    output_dir: Path
    months_written: List[str] = field(default_factory=list)
    months_skipped: List[str] = field(default_factory=list)
    files_ok: int = 0
    files_failed: int = 0
    failures: List[str] = field(default_factory=list)
    cancelled: bool = False

    def summary(self) -> str:
        bits = [
            f"{len(self.months_written)} month(s) written",
            f"{self.files_ok} file(s) processed",
            f"{self.files_failed} failed",
        ]
        if self.months_skipped:
            bits.append(f"{len(self.months_skipped)} month(s) already existed")
        if self.cancelled:
            bits.append("STOPPED EARLY")
        return ", ".join(bits)


def _provenance(cfg: ProcessConfig, patch_results=None) -> Dict[str, str]:
    m, n, b, g, e = cfg.mask, cfg.noise, cfg.binning, cfg.geometry, cfg.env
    bands = "; ".join(f"{lo}-{hi}m" for lo, hi in (m.exclude_bands or [])) or "none"
    return {
        "nektone_geometry": f"{g.orientation}-looking, mooring depth {g.mooring_depth} m",
        "nektone_environment": (
            f"T={e.temperature} degC, S={e.salinity} PSU, "
            f"P={e.pressure if e.pressure is not None else round(g.mooring_depth * 1.01, 2)} dbar"
            if e.use_env_params else "instrument defaults"
        ),
        "nektone_masking": (
            f"keep {m.keep_min}-{m.keep_max} m; excluded bands: {bands}"
            if m.enabled else "disabled"
        ),
        "nektone_noise_removal": (
            ", ".join(
                filter(None, [
                    f"impulse({n.impulse_threshold_db}dB/{n.impulse_depth_bin_m}m)" if n.impulse else "",
                    f"transient({n.transient_threshold_db}dB/{n.transient_depth_bin_m}m/"
                    f"{n.transient_side_pings}pings)" if n.transient else "",
                    f"background(SNR {n.background_snr_db}dB)" if n.background else "",
                ])
            ) or "none"
            if n.enabled else "disabled"
        ),
        "nektone_binning": f"{b.range_bin_m} m x {b.ping_time_bin}",
    }


def _patch_provenance(patch_results) -> Dict[str, str]:
    """Record which echopype patches were live for this run.

    An interpolated calibration constant changes absolute Sv, so the product
    file has to carry that fact. Without it, a NetCDF written today and one
    written after an echopype upgrade look identical and are not.
    """
    from .echopype_patches import AZFP_SV_OFFSET_NOTE, PatchOutcome

    if not patch_results:
        return {"nektone_echopype_patches": "none"}
    applied = [name for name, outcome in patch_results
               if outcome in (PatchOutcome.APPLIED, PatchOutcome.ALREADY_OK)]
    attrs = {"nektone_echopype_patches": "; ".join(applied) if applied else "none"}
    if any("Sv offset" in name for name in applied):
        attrs["nektone_sv_offset_note"] = AZFP_SV_OFFSET_NOTE
    return attrs


def run_processing(cfg: ProcessConfig, ctx: JobContext) -> ProcessResult:
    import xarray as xr

    in_dir = Path(cfg.input_dir)
    if not in_dir.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {in_dir}")

    out_dir = cfg.resolved_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ProcessResult(output_dir=out_dir)

    problem = check_binning_backend()
    if problem:
        raise RuntimeError(problem)

    patch_results = apply_echopype_patches(ctx)
    configure_dask(cfg.dask_scheduler, ctx)
    baseline = _rss_mb()
    if baseline is not None:
        ctx.info(f"Memory at start: {baseline:.0f} MB")

    files = find_nc_files(in_dir, recursive=True)
    if not files:
        raise FileNotFoundError(f"No .nc files found in {in_dir}")

    if cfg.binning.group_by_month:
        groups = group_by_month(files)
    else:
        groups = {"all": files}

    ctx.info(f"{len(files)} file(s) across {len(groups)} group(s): {', '.join(groups)}")
    suffix = f"{cfg.binning.range_bin_m:g}m"
    total = len(files)
    done = 0

    for month, file_list in groups.items():
        if ctx.cancelled:
            result.cancelled = True
            break

        out_name = f"{month}_{suffix}.nc"
        save_path = out_dir / out_name
        if save_path.exists() and cfg.skip_existing:
            ctx.info(f"{month}: {out_name} already exists - skipping.")
            result.months_skipped.append(month)
            done += len(file_list)
            ctx.progress(done, total, month)
            continue

        ctx.info(f"--- {month}: {len(file_list)} file(s) ---")
        binned = []

        for f in file_list:
            try:
                ctx.raise_if_cancelled()
            except Cancelled:
                result.cancelled = True
                break

            ctx.progress(done, total, f"{month} / {f.name}")
            try:
                binned.append(process_one_file(f, cfg, ctx))
                result.files_ok += 1
            except Cancelled:
                result.cancelled = True
                break
            except Exception as exc:  # noqa: BLE001
                result.files_failed += 1
                result.failures.append(f"{f.name}: {exc}")
                ctx.error(f"{f.name} -> {type(exc).__name__}: {exc}")
            finally:
                done += 1
                if cfg.gc_every > 0 and done % cfg.gc_every == 0:
                    gc.collect()
                    if cfg.memory_warn_mb > 0:
                        rss = _rss_mb()
                        if rss is not None and rss > cfg.memory_warn_mb:
                            ctx.warn(
                                f"Memory in use: {rss:.0f} MB (above the "
                                f"{cfg.memory_warn_mb:.0f} MB warning level). "
                                "Consider a coarser time bin or the synchronous scheduler."
                            )

        if not binned:
            ctx.warn(f"{month}: nothing processed, no output written.")
            continue

        try:
            ds_month = xr.concat(binned, dim="ping_time", combine_attrs="override")
            ds_month = ds_month.sortby("ping_time")
            # Overlapping deployments can duplicate timestamps; keep the first.
            _, idx = _unique_index(ds_month["ping_time"].values)
            if len(idx) != ds_month.sizes.get("ping_time", 0):
                ctx.warn(f"{month}: dropped {ds_month.sizes['ping_time'] - len(idx)} duplicate ping_time(s).")
                ds_month = ds_month.isel(ping_time=idx)

            ds_month.attrs.update(_provenance(cfg))
            ds_month.attrs.update(_patch_provenance(patch_results))
            ds_month.attrs["nektone_source_files"] = str(len(file_list))

            tmp = save_path.with_suffix(".nc.part")
            ds_month.to_netcdf(tmp)
            ds_month.close()
            tmp.replace(save_path)          # atomic-ish: never leave a half file
            result.months_written.append(month)
            ctx.ok(f"{month}: wrote {out_name}")
        except Exception as exc:  # noqa: BLE001
            ctx.exception(f"{month}: failed to write output", exc)
            result.failures.append(f"{month} (write): {exc}")
        finally:
            for ds in binned:
                try:
                    ds.close()
                except Exception:
                    pass
            binned.clear()
            gc.collect()
            rss = _rss_mb()
            if rss is not None:
                drift = f" (+{rss - baseline:.0f} MB since start)" if baseline else ""
                ctx.info(f"Memory after {month}: {rss:.0f} MB{drift}")

    ctx.progress(total, total, "done")
    ctx.ok(f"Processing finished: {result.summary()}")
    return result


def _unique_index(values):
    import numpy as np
    _, idx = np.unique(values, return_index=True)
    return values, np.sort(idx)
