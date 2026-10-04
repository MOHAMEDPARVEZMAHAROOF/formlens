#!/usr/bin/env bash
# Run FormLens locally.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export FORMLENS_DATA="${FORMLENS_DATA:-$PWD/data}"
exec .venv/bin/python -m uvicorn formlens.app:app --host 127.0.0.1 --port "${PORT:-8000}"
