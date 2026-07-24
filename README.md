# NekTone

A desktop GUI for the [echopype](https://echopype.readthedocs.io/) AZFP processing
pipeline. It reproduces the notebook workflow — raw `.01A` → converted NetCDF →
calibrated, masked, denoised, binned monthly products → baseline metrics — as a
batch application that a non-programmer can drive.

Built for moored, multi-frequency AZFP deployments where a single deployment folder
holds thousands of hourly files.

---

## What it does

| Tab | Replaces | What happens |
|---|---|---|
| **1 · Convert** | `nekt_raw2nc.py` | Recursively finds `.01A` files in one deployment folder (flat *or* per-month subfolders), locates the master `.XML`, converts each to `.nc` in `<folder>_converted`. Resumable. |
| **2 · Process & bin** | `nekt_bin.py` | Calibrates with your T/S/P, maps `echo_range` onto true depth, applies vertical masking, runs the three noise-removal algorithms, bins to your resolution, groups by calendar month and writes `YYYYMM_2m.nc`. |
| **3 · Metrics** | `nekt_metric_multichannel.py` | Occupied Area, Mean S<sub>a</sub> and Centre of Mass per channel per month, with optional day/night solar windows in local time. One tidy CSV. |
| **Echogram viewer** | `nekt_viz_ui.py` | Opens any `.nc` product, per-channel echogram with adjustable colour scale, pan/zoom, export to PNG/PDF/SVG. |

Masking and noise removal are each **optional** — untick the group header to skip
the step entirely. Every individual noise algorithm can also be toggled on its own.

Vertical masking is expressed as a **keep window** (cut above / cut below) plus any
number of **exclude bands**. Your `surface_cutoff=0`, `bottom_cutoff=157`,
`bad_line=97–102` becomes: keep 0–157 m, exclude one band 97–102 m. Adding a second
artefact line is a click, not a code edit.

---

## Install (for development)

echopype supports Python 3.10–3.12. 3.13 is not yet supported.

```bash
git clone https://github.com/rashed-30/nektone_gui.git
cd nektone_gui

python -m venv .venv
# Windows:  .venv\Scripts\activate
source .venv/bin/activate

pip install -e .
nektone            # launch the GUI
```

Headless equivalent, useful for overnight batches and for isolating bugs:

```bash
nektone-cli convert /path/to/DEPLOY
nektone-cli process /path/to/DEPLOY_converted --settings my_settings.json
nektone-cli metrics /path/to/data_products_monthly
nektone-cli all     /path/to/DEPLOY --settings my_settings.json
```

If `nektone-cli` works but the GUI misbehaves, the problem is in the interface,
not the science. That split is deliberate.

---

## Building `NekTone.exe` for Windows

Two step-by-step guides, depending on what you have:

* **[`packaging/GITHUB_BUILD.md`](packaging/GITHUB_BUILD.md)** — GitHub builds it for you on its own Windows machine. Browser only, no command line, no Windows machine required. **Start here.**
* **[`packaging/WINDOWS_BUILD.md`](packaging/WINDOWS_BUILD.md)** — building locally, as a diagnostic ladder. Use this when something is broken and you need to see why.

The summary below assumes a working Python environment.

PyInstaller is not a cross-compiler — a Windows `.exe` must be built on Windows.

```bat
git clone https://github.com/rashed-30/nektone_gui.git
cd nektone_gui
packaging\build_windows.bat
```

Result: `dist\NekTone\NekTone.exe`. Zip the **whole** `dist\NekTone` folder to
share it; the `.exe` alone will not run. Expect roughly 700 MB–1 GB unpacked —
that is numpy, scipy, Qt and the HDF5 stack, not the application.

On macOS or Linux: `bash packaging/build.sh`.

### Building without a Windows machine

`.github/workflows/build.yml` builds Windows and macOS bundles on GitHub's own
runners. Push a tag and download the artifacts:

```bash
git tag v1.0.0
git push origin v1.0.0
```

You can also trigger it manually from the repository's **Actions** tab.

### If the frozen build won't start

Set `console=False` → `console=True` in `packaging/nektone.spec` and rebuild. The
console window will show the real traceback, which is almost always a missing
hidden import; add it to the `hiddenimports` list in the spec.

---

## Settings

Every field is saved automatically on exit and restored next launch
(`%LOCALAPPDATA%\NekTone\settings.json` on Windows). **File ▸ Save settings as…**
writes a portable JSON you can archive alongside a dataset or pass to
`nektone-cli --settings` — which makes a processing run reproducible by someone
else, on another machine, months later.

Every output file also carries its processing parameters as NetCDF attributes
(`nektone_masking`, `nektone_noise_removal`, `nektone_binning`, …), so a product
can never become separated from the settings that made it.

---

## Architecture

```
src/nektone/
  core/            pure pipeline — no Qt anywhere, independently testable
    config.py      dataclasses + JSON persistence
    discovery.py   file finding, XML detection, YYMM month grouping
    jobs.py        logging / progress / cooperative cancellation
    convert.py     stage 1
    process.py     stage 2
    metrics.py     stage 3
  gui/             PySide6 — depends on core, never the reverse
    worker.py      QThread wrapper; all heavy work happens here
    base_tab.py    shared Run/Stop/progress/log behaviour
    tab_*.py       one file per tab
    main_window.py tabs, shared log, menus, settings
  cli.py           headless runner
```

### Why the previous version was unstable

The failure modes this rewrite targets, in rough order of how often they bite:

1. **Work on the GUI thread.** Any multi-minute call inside a button handler makes
   Windows paint the window "Not Responding". Users then force-quit mid-write and
   corrupt an output file. *Fix:* every long operation runs in a `QThread`; the
   window stays live and Stop is always reachable.
2. **One bad file killing the batch.** *Fix:* per-file `try/except` that logs and
   continues, plus deletion of any half-written target so a resume never trusts it.
3. **echopype API drift.** The cleaning API has changed across releases —
   your `nekt_bin.py` already imports `remove_background_noise` from a dev branch.
   *Fix:* `_call_supported()` inspects each function's signature and drops keyword
   arguments the installed version doesn't accept, and the background-noise
   function is resolved across three possible import paths.
4. **Memory growth over thousands of files.** *Fix:* datasets closed in `finally`
   blocks, periodic `gc.collect()`, and monthly concatenation held only as long
   as it takes to write.
5. **Concurrent HDF5 access.** netCDF4/HDF5 is not reliably thread-safe; reading
   in the viewer while a batch writes is a hard-crash route. *Fix:* one job at a
   time — other tabs are disabled while work runs.
6. **Half-written outputs.** *Fix:* each monthly product is written to `.nc.part`
   and renamed only on success.

---

## Corrections carried over from the notebooks

* `mean_linear` multiplied by a hard-coded `2` for the bin thickness. The metrics
  stage now reads the actual bin spacing from the file, so changing the vertical
  resolution no longer silently biases S<sub>a</sub>.
* Occupied Area divided by `ds_ch.size`, which counts masked NaN cells in the
  denominator — so masking more of the column mechanically lowered the percentage.
  Both denominators are now reported side by side (`% valid` and `% all cells`),
  so earlier numbers remain reproducible while the corrected figure is available.
* Centre of Mass divided by a backscatter sum that can be zero. Now guarded.
* `'1H'` is deprecated in pandas ≥ 2.2; time-bin strings are normalised.
* Duplicate `ping_time` values from overlapping files are dropped, and each
  monthly product is sorted in time before writing.

---

## Memory and crashes

**Memory.** The Process tab has a Memory group:

* **Dask scheduler** — `synchronous` (default) keeps peak memory at roughly one
  chunk and makes tracebacks readable. `threads` is faster but can hold several
  chunks per worker, which is what pushes a long AZFP month over the edge.
* **Collect garbage every N files** — default 5.
* **Warn above N MB** — logs a warning when resident memory crosses your limit.
  0 disables it. Memory is also reported at start and after each month, so
  a genuine leak shows up as a rising number in the log rather than a silent death.

The largest structural fix: `compute_MVBS` can return a **lazy dask graph** that
still points at the source file. The previous flow closed that file and kept the
graph in a list until the end of the month — so the final concatenation read
through closed HDF5 handles, and held one open handle per hourly file. Each
binned result is now computed into memory before its source is closed. On a
720-file month that is the difference between 720 open file handles and one.

**Crashes.** "Closed unexpectedly" has two causes that need different tools, and
both are now armed *before* Qt loads:

* A Python exception escaping the event loop → `sys.excepthook` writes a
  traceback and shows a dialog; the app stays up.
* A **native** crash — a segfault inside HDF5, netCDF4, Qt or BLAS. Python never
  sees these, which is why the process just vanishes with no message. `faulthandler`
  installs an OS-level signal handler and writes a stack trace to `crash.log`.

Both land in **Help ▸ Open log folder**. **Help ▸ Diagnostics…** gives a copyable
block with every library version, available RAM and the active patch list; the
headless equivalent is `nektone-cli doctor`.

If the app closes *on launch*, run `nektone-cli doctor` first. A crash that early
is almost always a missing or mismatched binary dependency rather than anything
to do with your data.

---

## Patching echopype

Editing `site-packages/echopype/` directly disappears three ways: a `pip install
--upgrade`, a fresh virtual environment, and — most damaging — **PyInstaller
bundles whatever is in site-packages at build time**. A GitHub Actions runner
pip-installs echopype clean, so the resulting `.exe` ships *without* your edit.
The app then works on your machine and fails for everyone else, on precisely the
data the patch was written for.

`src/nektone/core/echopype_patches.py` applies fixes at import time instead, so
they travel with this repository. Patches are idempotent, degrade to a logged
no-op if an upgrade renames the target, and are reported by
`nektone-cli patches`.

### Registered patches

**AZFP 200 kHz / 200 µs Sv offset.** `echopype.convert.parse_azfp.SV_OFFSET`
maps frequency (Hz) → pulse length (µs) → offset (dB). The 200 kHz row has
150 µs and 250 µs but no 200 µs entry, so any AZFP file with a 200 kHz channel
at a 200 µs pulse fails with:

```
ValueError: Pulse length 200 us is not in the Sv offset dictionary
```

The patch inserts **1.35 dB**, the midpoint of the neighbouring 1.4 and 1.3
entries.

> ⚠️ **1.35 dB is interpolated, not a manufacturer figure.** It shifts absolute
> Sv on that channel by up to ±0.05 dB relative to the true value. Confirm it
> against your ASL Environmental Sciences calibration sheet before publishing
> absolute backscatter, and state it in your methods. The app logs a warning
> each time the patch is applied, and writes both the patch list and this
> caveat into every output file as `nektone_echopype_patches` and
> `nektone_sv_offset_note` — so a product can never be separated from the
> assumption behind it.

The patch defers to upstream: if echopype ever ships its own 200 µs value, the
existing entry wins. If the table is restructured, the patch reports
"not needed" rather than fabricating a row in the wrong place.

---

## Removing the Metrics tab

Metrics are isolated. To drop them entirely:

```bash
git rm src/nektone/core/metrics.py src/nektone/gui/tab_metrics.py
```

then delete the `MetricsTab` import, the `addTab` line and `metrics_tab` from the
tab tuples in `gui/main_window.py`, and the `metrics` stage from `cli.py`. Nothing
else references them.

---

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

The suite covers month grouping, config round-trips, masking geometry for both
upward- and downward-looking moorings, and the metric maths including the
all-NaN and zero-backscatter edge cases. It does not require echopype.

---

## License

MIT.
