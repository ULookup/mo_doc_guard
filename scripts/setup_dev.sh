#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3.11 >/dev/null 2>&1; then
  echo "python3.11 not found. Install Python 3.11 first."
  exit 1
fi

python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"

echo "Dev environment is ready."
