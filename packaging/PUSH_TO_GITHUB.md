# Getting this into your repository

I cannot push to GitHub for you, so here are the two ways to do it.

## Option A — replace the contents of your existing repo

```bash
git clone https://github.com/rashed-30/nektone_gui.git
cd nektone_gui

git checkout -b rewrite

# delete the old application code, keep the git history
git rm -r --cached src packaging tests README.md pyproject.toml 2>/dev/null
rm -rf src packaging tests README.md pyproject.toml

# copy everything from the unzipped nektone/ folder into this directory, then:
git add -A
git commit -m "Rewrite as a batch pipeline GUI"
git push -u origin rewrite
```

Open a pull request from `rewrite` to `main`, or push straight to `main` if you
prefer. Keeping it on a branch first means the old version stays reachable.

## Option B — fresh repository

```bash
cd nektone            # the unzipped folder
git init
git add -A
git commit -m "NekTone 1.0.0"
git branch -M main
git remote add origin https://github.com/rashed-30/nektone.git
git push -u origin main
```

Create the empty `nektone` repo on GitHub first (no README, no .gitignore — this
folder already has both).

## Then build the .exe

On a Windows machine:

```bat
packaging\build_windows.bat
```

Or push a tag and let GitHub Actions build it for you:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Download the `NekTone-windows` artifact from the Actions tab when it finishes.
