"""Stage 1 - raw instrument files to converted NetCDF.

Mirrors `nekt_raw2nc.py`, but: resumable, cancellable, and one bad file can
never take the batch (or the GUI) down with it.
"""
from __future__ import annotations

import gc
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .config import ConvertConfig
from .discovery import find_raw_files, find_xml
from .echopype_patches import apply_all as apply_echopype_patches
from .jobs import JobContext, Cancelled


@dataclass
class ConvertResult:
    output_dir: Path
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    failures: List[str] = field(default_factory=list)
    cancelled: bool = False

    def summary(self) -> str:
        bits = [f"{self.converted} converted", f"{self.skipped} skipped", f"{self.failed} failed"]
        if self.cancelled:
            bits.append("STOPPED EARLY")
        return ", ".join(bits)


def _unique_target(out_dir: Path, stem: str, taken: set) -> Path:
    name = f"{stem}.nc"
    if name.lower() not in taken:
        taken.add(name.lower())
        return out_dir / name
    i = 2
    while f"{stem}_{i}.nc".lower() in taken:
        i += 1
    taken.add(f"{stem}_{i}.nc".lower())
    return out_dir / f"{stem}_{i}.nc"


def run_conversion(cfg: ConvertConfig, ctx: JobContext) -> ConvertResult:
    import echopype as ep

    apply_echopype_patches(ctx)

    in_dir = Path(cfg.input_dir)
    if not in_dir.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {in_dir}")

    out_dir = cfg.resolved_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ConvertResult(output_dir=out_dir)

    files = find_raw_files(in_dir, cfg.raw_extension, cfg.recursive)
    if not files:
        raise FileNotFoundError(
            f"No '{cfg.raw_extension}' files found in {in_dir} "
            f"({'including' if cfg.recursive else 'excluding'} subfolders)."
        )

    xml_path = None
    if cfg.sonar_model.upper().startswith("AZFP"):
        xml_path = find_xml(in_dir, cfg.xml_path)
        if xml_path is None:
            raise FileNotFoundError(
                f"No AZFP master .XML file found in {in_dir}. "
                "Place the instrument XML in the deployment folder, or select it manually."
            )
        ctx.info(f"Master XML: {xml_path.name}")

    ctx.info(f"Found {len(files)} raw file(s).")
    ctx.info(f"Output folder: {out_dir}")

    taken = {p.name.lower() for p in out_dir.glob("*.nc")}
    total = len(files)

    for i, raw in enumerate(files, start=1):
        try:
            ctx.raise_if_cancelled()
        except Cancelled:
            result.cancelled = True
            ctx.warn("Conversion stopped by user.")
            break

        ctx.progress(i - 1, total, raw.name)

        if cfg.flatten_output:
            target = out_dir / f"{raw.stem}.nc"
            if target.exists() and cfg.skip_existing:
                result.skipped += 1
                continue
            if target.exists() is False and target.name.lower() in taken:
                target = _unique_target(out_dir, raw.stem, taken)
        else:
            rel = raw.parent.relative_to(in_dir)
            sub = out_dir / rel
            sub.mkdir(parents=True, exist_ok=True)
            target = sub / f"{raw.stem}.nc"
            if target.exists() and cfg.skip_existing:
                result.skipped += 1
                continue

        ed = None
        try:
            if raw.stat().st_size == 0:
                raise ValueError("file is empty (0 bytes)")

            kwargs = {"sonar_model": cfg.sonar_model}
            if xml_path is not None:
                kwargs["xml_path"] = str(xml_path)
            ed = ep.open_raw(str(raw), **kwargs)
            ed.to_netcdf(save_path=str(target), overwrite=True)
            result.converted += 1
            taken.add(target.name.lower())
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the batch
            result.failed += 1
            result.failures.append(f"{raw.name}: {exc}")
            ctx.error(f"{raw.name} -> {type(exc).__name__}: {exc}")
            # Remove a half-written file so a later resume doesn't trust it.
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
        finally:
            del ed
            if i % 25 == 0:
                gc.collect()

    ctx.progress(total, total, "done")
    gc.collect()
    ctx.ok(f"Conversion finished: {result.summary()}")
    if result.failures:
        ctx.warn(f"{len(result.failures)} file(s) failed - see log for details.")
    return result
