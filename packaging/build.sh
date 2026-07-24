#!/usr/bin/env bash
# Build NekTone for the current platform. Run from the repository root.
set -euo pipefail

python -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pyinstaller
pyinstaller packaging/nektone.spec --noconfirm --clean

echo
echo "Built: dist/NekTone/"
