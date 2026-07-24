"""Locating raw files, the AZFP master XML, and grouping NetCDF by month.

Deployment folders come in two shapes in the wild:

    DEPLOY/                        DEPLOY/
      instrument.XML                 instrument.XML
      23040100.01A                   202304/
      23040101.01A                     23040100.01A
      ...                            202305/
                                       23050100.01A

`find_raw_files(recursive=True)` handles both.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

# AZFP filenames are YYMMDDHH.01A -> the first 4 digits are the month key.
_YYMMDDHH = re.compile(r"^(\d{2})(\d{2})(\d{2})(\d{2})")


def find_raw_files(root, extension: str = ".01A", recursive: bool = True) -> List[Path]:
    """Return raw instrument files, case-insensitively matched, sorted by name."""
    root = Path(root)
    if not root.is_dir():
        return []
    ext = extension.lower()
    it = root.rglob("*") if recursive else root.glob("*")
    files = [p for p in it if p.is_file() and p.suffix.lower() == ext]
    return sorted(files, key=lambda p: (p.name.lower(), str(p)))


def find_xml(root, explicit: str = "") -> Optional[Path]:
    """Locate the AZFP master XML. Explicit path wins; otherwise search
    shallow-first so a deployment-level XML beats a stray copy in a subfolder."""
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    root = Path(root)
    if not root.is_dir():
        return None
    shallow = sorted(p for p in root.glob("*") if p.is_file() and p.suffix.lower() == ".xml")
    if shallow:
        return shallow[0]
    deep = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".xml")
    return deep[0] if deep else None


def find_nc_files(root, recursive: bool = True) -> List[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    it = root.rglob("*.nc") if recursive else root.glob("*.nc")
    return sorted((p for p in it if p.is_file()), key=lambda p: p.name)


def month_key_from_name(path) -> Optional[str]:
    """'23040100.nc' -> '202304'. Returns None if the name doesn't parse."""
    stem = Path(path).stem
    m = _YYMMDDHH.match(stem)
    if not m:
        return None
    yy, mm = m.group(1), m.group(2)
    if not (1 <= int(mm) <= 12):
        return None
    # AZFP deployments are all post-2000; a 2-digit year maps to 20YY.
    return f"20{yy}{mm}"


def month_key_from_data(path) -> Optional[str]:
    """Fallback: read the first ping_time out of the file itself.

    Slower, but rescues files whose names don't follow the AZFP convention.
    """
    try:
        import xarray as xr
        for group in (None, "Sonar/Beam_group1"):
            try:
                with xr.open_dataset(path, group=group) as ds:
                    if "ping_time" in ds.coords or "ping_time" in ds.variables:
                        import pandas as pd
                        t = pd.to_datetime(ds["ping_time"].values[0])
                        return f"{t.year:04d}{t.month:02d}"
            except Exception:
                continue
    except Exception:
        pass
    return None


def group_by_month(files, use_data_fallback: bool = True) -> Dict[str, List[Path]]:
    """Bucket NetCDF files into YYYYMM groups, preserving sorted order."""
    groups: Dict[str, List[Path]] = {}
    for f in files:
        key = month_key_from_name(f)
        if key is None and use_data_fallback:
            key = month_key_from_data(f)
        if key is None:
            key = "unknown"
        groups.setdefault(key, []).append(Path(f))
    for k in groups:
        groups[k].sort(key=lambda p: p.name)
    return dict(sorted(groups.items()))


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"
