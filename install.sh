#!/usr/bin/env bash
# CleatStomp installer — project-level dependencies only, then it EXITS.
#
# Runs as an unprivileged user, installs nothing from the system package
# manager, and never starts the tool. Prerequisites (Python 3.9+) are listed in
# INSTALL.md.
#
#   bash install.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: $PYTHON not found on PATH (install Python 3.9+ first, see INSTALL.md)" >&2
    exit 1
fi

echo "==> Python: $("$PYTHON" -c 'import sys; print(sys.version.split()[0])')"

echo "==> Updating pip, setuptools and wheel"
if ! "$PYTHON" -m pip install --quiet --upgrade pip setuptools wheel; then
    echo "note: could not update pip/setuptools/wheel (offline?). Continuing with the installed versions." >&2
fi

echo "==> Installing declared dependencies (requirements.txt)"
"$PYTHON" -m pip install --quiet -r requirements.txt

echo "==> Installing the cleatstomp console script (editable, no build isolation)"
if ! "$PYTHON" -m pip install --quiet -e . --no-build-isolation; then
    echo "note: the 'cleatstomp' console script was not installed." >&2
    echo "      The tool still works: run it as $PYTHON cleatstomp.py ..." >&2
fi

echo "==> Import self-check"
"$PYTHON" -c 'import cleatstomp; print("cleatstomp", cleatstomp.__version__, "imports cleanly")'

echo "==> Test suite (pytest)"
"$PYTHON" -m pytest -q

echo
echo "Install complete. Nothing was started."
echo "  run:   $PYTHON cleatstomp.py --help      (or: cleatstomp --help)"
echo "  demo:  bash demo.sh"
echo "  data:  ./cleatstomp.json is created in whichever directory you run the tool from"
