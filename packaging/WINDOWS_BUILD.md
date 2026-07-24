# Building NekTone on Windows

From the `nektone.zip` file to a `NekTone.exe` you can hand to someone else.

Read the ladder in **Part B** before you build. Each rung proves one layer works,
so when something breaks you know which layer to blame. Freezing an app takes
20–40 minutes; finding out at the end that the problem was a missing Python
package wastes all of it.

---

## Part A — Set up

### A1. Install Python 3.12

Download from **python.org/downloads** — pick 3.12.x. echopype supports
3.10–3.12; 3.13 is not supported yet and will fail at install.

> **Do not use the Microsoft Store version of Python.** It runs in a sandbox
> that redirects file writes and regularly breaks PyInstaller. If you already
> have it, install the python.org one alongside and call it explicitly with
> `py -3.12`.

On the first installer screen, tick **Add python.exe to PATH** before clicking
Install. Then open a new Command Prompt and check:

```bat
py -3.12 --version
```

You should see `Python 3.12.x`.

### A2. Extract the zip

Right-click `nektone.zip` → **Extract All**. Extract to a **short path close to
the drive root**, for example:

```
C:\dev\nektone
```

Windows still has a 260-character path limit that some build tools hit. A deep
path like `C:\Users\...\OneDrive\Documents\Research\...\nektone` is a real cause
of build failures.

> If the extracted folder contains a single `nektone` folder which itself
> contains `src`, `packaging` and `pyproject.toml`, use that inner folder as
> your project root.

Also: if the folder is inside OneDrive or Dropbox, **pause syncing** while you
build. Sync clients lock files mid-write and produce baffling errors.

### A3. Open a Command Prompt in that folder

In File Explorer, click the address bar, type `cmd`, press Enter. Confirm you're
in the right place:

```bat
dir pyproject.toml
```

If that says "File Not Found", you're in the wrong folder.

---

## Part B — The ladder

Do these in order. Stop at the first one that fails; that is your problem.

### Rung 1 — Create an isolated environment

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Your prompt should now start with `(.venv)`. It must stay that way for every
command below. If you close the window, re-run `.venv\Scripts\activate`.

A virtual environment matters here beyond tidiness: if you have PyQt5 or PySide2
installed globally from some other project, they collide with PySide6 at runtime
and the window closes instantly with no message. A clean venv rules that out.

### Rung 2 — Install the dependencies

```bat
pip install -e .
```

Ten to twenty minutes. It pulls numpy, scipy, xarray, netCDF4, echopype, Qt.

Optional but recommended — enables memory reporting in the app:

```bat
pip install psutil
```

### Rung 3 — Prove the dependencies actually load

```bat
nektone-cli doctor
```

Every line should show a version number. **Any `NOT AVAILABLE` line is your
launch crash.** A package that installed without error can still fail to import
on Windows if a DLL is missing.

### Rung 4 — Run the pipeline with no GUI at all

Point this at a small test folder — one day of files, not a whole deployment:

```bat
nektone-cli convert "C:\path\to\DEPLOY"
```

If this works, the science layer is sound and any remaining problem is the
interface. If it fails, the error text tells you exactly what and where.

### Rung 5 — Run the GUI from source

```bat
nektone
```

**This is the rung that answers your question.** If the window opens and stays
open here, but a frozen `.exe` closes at launch, the problem is *packaging* —
a missing hidden import — and Rung 6 will show you which one.

If it closes here too, packaging is innocent. Look at:

```bat
type "%LOCALAPPDATA%\NekTone\logs\crash.log"
```

A Python traceback means a missing package. A stack trace with no Python
exception means a native crash — usually a Qt or HDF5 DLL conflict, and the fix
is almost always a clean venv (Rung 1) with no other Qt binding installed.

### Rung 6 — Build a debug .exe first

Open `packaging\nektone.spec` in Notepad. Find this line:

```python
    console=False,          # set True temporarily if the app won't start
```

Change it to `console=True`, save, then:

```bat
pip install pyinstaller
pyinstaller packaging\nektone.spec --noconfirm --clean
```

Twenty to forty minutes. Then:

```bat
dist\NekTone\NekTone.exe
```

A black console window opens behind the app. **If the app closes, the reason is
printed in that console** — normally `ModuleNotFoundError: No module named 'x'`.
Fix it by adding `"x"` to the `hiddenimports` list in the spec and rebuilding.
This is the single most useful debugging tool in the whole process, and it is
why the debug build comes before the real one.

### Rung 7 — Build the real .exe

Once the debug build launches cleanly, set `console=False` back in the spec and
rebuild:

```bat
pyinstaller packaging\nektone.spec --noconfirm --clean
```

Your application is `dist\NekTone\NekTone.exe`.

---

## Part C — Shipping it

The `.exe` **will not run on its own.** It needs every file beside it. Zip the
whole folder:

```bat
powershell Compress-Archive -Path dist\NekTone -DestinationPath NekTone-windows.zip
```

The recipient extracts and double-clicks `NekTone.exe`. They need no Python,
no pip, nothing.

Expect 700 MB – 1 GB unpacked. That is numpy, scipy, Qt and the HDF5 stack, not
your code. It cannot be made much smaller without dropping functionality.

### The shortcut, once it works

`packaging\build_windows.bat` does Rungs 1, 2, 6 and 7 in one command. Use it
for rebuilds *after* a first successful manual build — not for the first one,
because it hides the output you need when something goes wrong.

---

## Part D — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `'py' is not recognized` | Python not on PATH | Reinstall, tick **Add python.exe to PATH** |
| `pip install -e .` fails on `echopype` | Python 3.13 | Use 3.12: `py -3.12 -m venv .venv` |
| Window flashes and vanishes | Missing hidden import | Rung 6 — build with `console=True` |
| `Could not load the Qt platform plugin "windows"` | Another Qt binding installed | Clean venv; ensure no PyQt5/PySide2 |
| App runs from source, `.exe` does not | Packaging | Rung 6; add the named module to `hiddenimports` |
| Windows Defender blocks the exe | Unsigned PyInstaller binary | Expected. Add an exclusion, or code-sign for wider distribution |
| `pyinstaller` not recognized | venv not active | Re-run `.venv\Scripts\activate` |
| Build fails with path errors | Path too long, or OneDrive | Move to `C:\dev\nektone`, pause syncing |
| App opens but conversion finds no files | Wrong extension or subfolder setting | Check the preview line under the folder picker |

Whatever happens, **Help ▸ Diagnostics… ▸ Copy** in the running app, or
`nektone-cli doctor` at the prompt, gives the full environment in one block.
The logs live in `%LOCALAPPDATA%\NekTone\logs\`.

---

## Part E — Letting GitHub build it instead

If the Windows build keeps fighting you, GitHub can build on a clean machine —
no command line at all. **See [`GITHUB_BUILD.md`](GITHUB_BUILD.md)** for the
browser-only walkthrough.

If you already use git, the short version is:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Open the **Actions** tab, wait for the run to finish, and download the
`NekTone-windows` artifact. Same result, someone else's computer.

Note that the runner installs echopype clean from PyPI — so any local edits you
made inside `site-packages\echopype\` will **not** be present. That is exactly
what `src/nektone/core/echopype_patches.py` exists to solve.
