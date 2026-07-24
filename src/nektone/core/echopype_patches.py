"""Runtime patches applied to the installed echopype.

Why this exists
---------------
Editing files inside `site-packages/echopype/` works on one machine and then
silently disappears three ways:

* `pip install --upgrade echopype` overwrites it,
* a fresh virtual environment never had it,
* **PyInstaller bundles whatever is in site-packages at build time** — so a
  GitHub Actions runner, which pip-installs echopype clean, produces an .exe
  *without* the fix. The app then works locally and fails for everyone else,
  on exactly the data the patch was written for.

Patching at import time instead means the fix travels with this repository and
is applied to whichever echopype happens to be installed. Every patch logs
whether it was needed, applied, or already present, so a silent no-op is
impossible to miss.

Adding a patch
--------------
Append an entry to `PATCHES`. `set_mapping_entry` handles the common case of a
lookup table that is missing a row:

    Patch(
        name="AZFP 200 kHz @ 200 ms ping period",
        apply=lambda: set_mapping_entry(
            "echopype.convert.parse_azfp", "SOME_TABLE",
            key=(200000, 0.2), value=1.234,
        ),
    )

Run `nektone-cli patches` to see what is active against your installed version.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, List, Optional


class PatchOutcome:
    APPLIED = "applied"
    ALREADY_OK = "already correct"
    NOT_NEEDED = "not needed (target absent in this version)"
    FAILED = "failed"


@dataclass
class Patch:
    name: str
    apply: Callable[[], str]
    note: str = ""


def set_mapping_entry(module_path: str, attr: str, key: Any, value: Any,
                      overwrite: bool = False) -> str:
    """Insert `key -> value` into a module-level dict, creating nothing else.

    Returns a PatchOutcome. A missing module or attribute is reported as
    NOT_NEEDED rather than raising, so an echopype upgrade that renames the
    table degrades to a log line instead of a crash on startup.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return PatchOutcome.NOT_NEEDED

    table = getattr(module, attr, None)
    if table is None or not hasattr(table, "__setitem__"):
        return PatchOutcome.NOT_NEEDED

    try:
        if key in table and not overwrite:
            return PatchOutcome.ALREADY_OK if table[key] == value else PatchOutcome.ALREADY_OK
        table[key] = value
        return PatchOutcome.APPLIED
    except Exception:  # noqa: BLE001
        return PatchOutcome.FAILED


def set_nested_entry(module_path: str, attr: str, keys: tuple, value: Any,
                     overwrite: bool = False, create_missing: bool = False) -> str:
    """Same, for a table nested one or more levels deep: table[k1][k2] = value.

    `create_missing` is False on purpose. If the outer key is absent, echopype
    has probably restructured the table, and inventing `{k1: {k2: value}}` would
    write a plausible-looking entry into the wrong place — worse than not
    patching at all, because it fails silently and produces wrong numbers.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return PatchOutcome.NOT_NEEDED

    node = getattr(module, attr, None)
    if node is None:
        return PatchOutcome.NOT_NEEDED

    try:
        for k in keys[:-1]:
            if k not in node:
                if not create_missing:
                    return PatchOutcome.NOT_NEEDED
                node[k] = {}
            node = node[k]
        last = keys[-1]
        if last in node and not overwrite:
            return PatchOutcome.ALREADY_OK
        node[last] = value
        return PatchOutcome.APPLIED
    except Exception:  # noqa: BLE001
        return PatchOutcome.FAILED


# ---------------------------------------------------------------------------
# The patch registry.
# ---------------------------------------------------------------------------

# echopype's AZFP Sv-offset lookup (echopype.convert.parse_azfp.SV_OFFSET) is a
# nested table: frequency in Hz -> pulse length in microseconds -> offset in dB.
# The 200 kHz row has entries for 150 us and 250 us but not 200 us, so any AZFP
# file with a 200 kHz channel at a 200 us pulse raises:
#
#   ValueError: Pulse length 200 us is not in the Sv offset dictionary ...
#
# 1.35 dB is the midpoint of the neighbouring 150 us (1.4) and 250 us (1.3)
# entries. It is an interpolation, not a manufacturer figure — see AZFP_SV_OFFSET_NOTE.
AZFP_SV_OFFSET_NOTE = (
    "200 kHz / 200 us Sv offset = 1.35 dB, linearly interpolated between the "
    "150 us (1.4) and 250 us (1.3) entries. Not a manufacturer-supplied value; "
    "confirm against your ASL calibration sheet before publishing absolute Sv."
)

PATCHES: List[Patch] = [
    Patch(
        name="AZFP 200 kHz / 200 us Sv offset",
        apply=lambda: set_nested_entry(
            "echopype.convert.parse_azfp",
            "SV_OFFSET",
            keys=(200000.0, 200),
            value=1.35,
        ),
        note=AZFP_SV_OFFSET_NOTE,
    ),
]


def apply_all(ctx=None) -> List[tuple]:
    """Apply every registered patch. Never raises."""
    results = []
    for patch in PATCHES:
        try:
            outcome = patch.apply()
        except Exception as exc:  # noqa: BLE001
            outcome = f"{PatchOutcome.FAILED}: {exc}"
        results.append((patch.name, outcome))
        if ctx:
            level = "warning" if "failed" in outcome else "info"
            ctx.log(f"echopype patch — {patch.name}: {outcome}", level)
            # An approximated constant must never be applied silently: it ends
            # up in published Sv values, so it belongs in the run log.
            if patch.note and outcome == PatchOutcome.APPLIED:
                ctx.log(f"    note: {patch.note}", "warning")
    if ctx and not PATCHES:
        ctx.log("echopype patches: none registered (using stock echopype).", "info")
    return results


def describe() -> str:
    if not PATCHES:
        return "No echopype patches are registered; stock echopype is used as installed."
    lines = ["Registered echopype patches:"]
    for name, outcome in apply_all():
        lines.append(f"  - {name}: {outcome}")
    return "\n".join(lines)


def installed_version() -> Optional[str]:
    try:
        import echopype
        return getattr(echopype, "__version__", None)
    except Exception:  # noqa: BLE001
        return None
