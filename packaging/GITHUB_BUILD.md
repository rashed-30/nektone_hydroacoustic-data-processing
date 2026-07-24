# Building through GitHub — no command line, no Windows machine

GitHub will run the build for you on its own Windows computer and hand you back
a finished `NekTone.exe`. You need a browser and about 30 minutes, most of which
is waiting.

There is **one genuine trap** in this route. It is Step 3. Read it before you
start uploading.

---

## Step 1 — Extract the zip

Right-click `nektone.zip` → **Extract All**.

Open the extracted folder. You should see:

```
.github/          <-- may be invisible; see Step 3
packaging/
src/
tests/
.gitignore
README.md
pyproject.toml
```

**If instead you see a single folder called `nektone`, open it.** That inner
folder is what you upload — not the wrapper.

---

## Step 2 — Create the repository

1. Go to **github.com** and sign in.
2. Top right **+** → **New repository**.
3. Name it `nektone` (or reuse `nektone_gui` — see the note at the bottom).
4. Choose **Public**. Actions minutes are free and unlimited on public repos;
   private repos bill Windows runners at **2× the minute rate**, and a build of
   this size uses roughly 25–40 minutes of quota per run.
5. Leave "Add a README" **unticked** — the folder already has one.
6. **Create repository**.

---

## Step 3 — Upload the files (the trap)

On the empty repository page, click **uploading an existing file**.

Now, before you drag anything:

> ### Windows hides folders whose name starts with a dot
>
> `.github` and `.gitignore` are invisible in File Explorer by default. If you
> select-all and drag, **you will silently upload everything except the build
> instructions** — and then the Actions tab will be empty and nothing will
> explain why.
>
> **Fix:** in File Explorer, open the **View** tab (Windows 10) or **View ▸
> Show** (Windows 11) and tick **Hidden items**. `.github` and `.gitignore`
> appear. Now select everything and drag.
>
> On macOS, press **Cmd + Shift + .** in Finder to show hidden files.

Drag all the files and folders into the browser window. Wait for the count to
finish, then scroll down and click **Commit changes**.

### Verifying you didn't fall in the trap

Look at your repository's file list. You should see a `.github` folder. Click
into it — there should be `workflows/build.yml` inside.

**If `.github` is missing**, don't re-upload everything. Do this instead:

1. **Add file** → **Create new file**.
2. In the filename box, type exactly: `.github/workflows/build.yml`
   — typing the slashes creates the folders automatically.
3. Open `.github/workflows/build.yml` from your extracted folder in Notepad,
   copy all of it, and paste it into the browser's editor.
4. **Commit changes**.

---

## Step 4 — Start the build

1. Click the **Actions** tab.
2. If you see a green "I understand my workflows, go ahead and enable them"
   button, click it. GitHub disables workflows on newly uploaded repositories
   as a safety measure.
3. In the left sidebar, click **Build desktop apps**.
4. On the right, click **Run workflow** → leave macOS unticked → **Run workflow**.

A yellow dot appears within a few seconds. Refresh if it doesn't.

You do **not** need a tag, a release, or any command line for this.

---

## Step 5 — Wait

Click into the run to watch it. Three stages:

| Stage | Time | What it does |
|---|---|---|
| Tests | ~1 min | Runs the test suite |
| Install dependencies | ~10 min | numpy, scipy, xarray, echopype, Qt |
| Freeze | ~15–25 min | PyInstaller bundles it all into an `.exe` |

Green tick = done. You can close the tab; it keeps running.

---

## Step 6 — Download

On the finished run's summary page, scroll to **Artifacts** at the bottom.
Download **NekTone-windows**.

You now unzip **twice** — this surprises everyone:

1. GitHub wraps artifacts in its own zip → extract it, you get `NekTone-windows.zip`.
2. Extract *that* → you get a `NekTone` folder.

Inside is `NekTone.exe`. Double-click it.

> Windows SmartScreen may say "Windows protected your PC". This is expected —
> the file is unsigned, not malicious. Click **More info** → **Run anyway**.
>
> Keep the whole `NekTone` folder together. The `.exe` will not run on its own;
> it needs the files beside it.

---

## Step 7 — Sharing it (optional)

Artifacts expire after 30 days and require a GitHub login to download. For
colleagues, make a **Release** instead — permanent, and downloadable by anyone
with the link.

Without touching a command line:

1. Repository home → **Releases** in the right sidebar → **Create a new release**.
2. **Choose a tag** → type `v1.0.0` → **Create new tag on publish**.
3. **Publish release**.

Pushing the tag triggers the workflow again, and this time it attaches
`NekTone-windows.zip` to the release page automatically. Wait for the green
tick, then refresh the release — the file will be there.

---

## Reading a failed run

A red X is information, not a disaster. To see why:

1. Click the run's title.
2. In the left sidebar, click the job with the red X.
3. Click the red step to expand it. The error is usually in the last 10 lines.

### What runs when

| Trigger | Jobs that run | Time |
|---|---|---|
| Any push to `main` | Check repository contents, Tests | ~1 min |
| **Run workflow** button | …plus the Windows build | ~30 min |
| Push a `v*` tag | …plus a published Release | ~30 min |

Ordinary pushes deliberately skip the expensive build, so editing a file doesn't
spend 30 minutes of runner time. **Saving a file will never produce an `.exe` —
you have to press Run workflow.**

### Common failures

| What the log says | What it means |
|---|---|
| `INCOMPLETE UPLOAD` in *Check repository contents* | The code wasn't uploaded, only `build.yml`. The step lists exactly which files are missing and what the repository does contain |
| `No such file or directory: pyproject.toml` | You uploaded the wrapper folder instead of its contents |
| Nothing in the Actions tab at all | `.github` didn't upload — see Step 3 |
| `no tests ran` / exit code 5 | Same cause: `tests/` is missing |
| `Could not find a version that satisfies echopype` | Rare; a PyPI hiccup. Re-run the workflow |
| `NekTone.exe was not produced` | The freeze failed; the real error is in the **Freeze** step above it |
| `ModuleNotFoundError` in the Freeze step | A missing hidden import — add it to `hiddenimports` in `packaging/nektone.spec` |

You can edit any file directly in the browser (open it, click the pencil icon,
commit) and re-run the workflow. No local setup needed for any of it.

---

## A note on your existing repository

`rashed-30/nektone_gui` is a **fork** of `sakib412/nektone`. Forks behave
awkwardly: Actions are disabled by default, and pull requests default to
targeting the upstream repository rather than yours, which is easy to do by
accident.

A fresh repository avoids both. If you'd rather keep the existing one, go to
**Settings ▸ General ▸ Danger Zone ▸ Leave fork network** first — this is
also where you'd rename it.

---

## Which route should you use?

| | GitHub build | Local Windows build |
|---|---|---|
| Command line needed | No | Yes |
| Time to first `.exe` | ~30 min, mostly waiting | ~45 min, hands-on |
| Debugging a launch crash | Slow — one edit per run | Fast — `console=True` shows it live |
| Your local echopype edits | **Not included** | Included, but invisibly |

Use GitHub for producing releases. Use the local build
(`packaging/WINDOWS_BUILD.md`) when something is broken and you need to see why.

That last row is the important one: the runner installs echopype clean from
PyPI, so any edit you made inside `site-packages\echopype\` is **absent** from a
GitHub-built `.exe`. That is precisely what `src/nektone/core/echopype_patches.py`
exists to solve — register the patch there and it travels with the repository
into every build.
