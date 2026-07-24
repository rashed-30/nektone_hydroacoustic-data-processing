"""Configuration objects for the NekTone pipeline.

Everything the GUI collects is funnelled into these dataclasses, so the core
pipeline never touches Qt and can be driven from the CLI or a notebook.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class ConvertConfig:
    """Raw (.01A / .azfp) -> converted NetCDF."""
    input_dir: str = ""
    output_dir: str = ""            # blank -> <input_dir>_converted
    raw_extension: str = ".01A"
    xml_path: str = ""              # blank -> auto-detect in input_dir
    recursive: bool = True          # descend into per-month subfolders
    sonar_model: str = "AZFP"
    skip_existing: bool = True
    flatten_output: bool = True     # all .nc into one folder (month grouping is by filename)

    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        src = Path(self.input_dir)
        return src.parent / f"{src.name}_converted"


@dataclass
class EnvConfig:
    """Environmental parameters handed to ep.calibrate.compute_Sv."""
    temperature: float = 4.0        # degC
    salinity: float = 32.0          # PSU
    pressure: Optional[float] = None  # dbar; None -> derived from mooring depth
    use_env_params: bool = True


@dataclass
class GeometryConfig:
    """How echo_range maps onto true water-column depth."""
    mooring_depth: float = 160.0
    orientation: str = "upward"     # "upward" | "downward"

    def depth_from_range(self, echo_range):
        if self.orientation == "upward":
            return self.mooring_depth - echo_range
        return self.mooring_depth + echo_range


@dataclass
class MaskConfig:
    """Vertical (depth) masking.

    `keep_min` / `keep_max` define the window that survives; `exclude_bands`
    knocks out arbitrary interior bands (ringdown lines, sensor artefacts).
    Set enabled=False to skip masking entirely.
    """
    enabled: bool = True
    keep_min: Optional[float] = 0.0
    keep_max: Optional[float] = 157.0
    exclude_bands: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class NoiseConfig:
    """Each of the three algorithms is independently switchable."""
    enabled: bool = True

    impulse: bool = True
    impulse_threshold_db: float = 10.0
    impulse_depth_bin_m: float = 3.0

    transient: bool = True
    transient_threshold_db: float = 12.0
    transient_depth_bin_m: float = 5.0
    transient_side_pings: int = 20

    background: bool = True
    background_snr_db: float = 5.0
    background_range_sample_num: int = 5
    background_ping_num: int = 3


@dataclass
class BinConfig:
    range_bin_m: float = 2.0
    ping_time_bin: str = "1h"       # pandas offset alias
    group_by_month: bool = True


@dataclass
class ProcessConfig:
    input_dir: str = ""             # folder of converted .nc
    output_dir: str = ""            # blank -> <input_dir>/../data_products
    env: EnvConfig = field(default_factory=EnvConfig)
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    mask: MaskConfig = field(default_factory=MaskConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    binning: BinConfig = field(default_factory=BinConfig)
    skip_existing: bool = True
    # --- memory management ---
    dask_scheduler: str = "synchronous"  # "synchronous" (low RAM) | "threads" (faster)
    gc_every: int = 5                    # force a collection every N files
    memory_warn_mb: float = 0.0          # 0 disables; otherwise warn above this RSS

    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return Path(self.input_dir).parent / "data_products_monthly"


@dataclass
class MetricsConfig:
    input_dir: str = ""
    output_csv: str = ""
    bio_threshold_db: float = -80.0
    # Solar-window standardisation (concept note section 3.3).
    split_day_night: bool = True
    timezone: str = "America/St_Johns"
    day_start_hour: int = 10
    day_end_hour: int = 14
    night_start_hour: int = 22
    night_end_hour: int = 2


@dataclass
class AppConfig:
    convert: ConvertConfig = field(default_factory=ConvertConfig)
    process: ProcessConfig = field(default_factory=ProcessConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)

    # ---- persistence -------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def save(self, path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "AppConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        cfg = cls()
        c = d.get("convert", {})
        for k, v in c.items():
            if hasattr(cfg.convert, k):
                setattr(cfg.convert, k, v)

        p = d.get("process", {})
        for section, obj in (
            ("env", cfg.process.env),
            ("geometry", cfg.process.geometry),
            ("mask", cfg.process.mask),
            ("noise", cfg.process.noise),
            ("binning", cfg.process.binning),
        ):
            for k, v in p.get(section, {}).items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
        # Copy every scalar key rather than a hand-written list: a whitelist
        # silently drops any field added later, so settings appear to save and
        # then quietly revert on the next launch.
        nested = {"env", "geometry", "mask", "noise", "binning"}
        for k, v in p.items():
            if k not in nested and hasattr(cfg.process, k):
                setattr(cfg.process, k, v)
        # tuples survive a JSON round-trip as lists
        cfg.process.mask.exclude_bands = [
            (float(a), float(b)) for a, b in cfg.process.mask.exclude_bands
        ]

        m = d.get("metrics", {})
        for k, v in m.items():
            if hasattr(cfg.metrics, k):
                setattr(cfg.metrics, k, v)
        return cfg
