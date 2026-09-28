#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/scripts/tvs.py" "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "$ROOT/scripts/tvs.py" "$@"
else
  echo "[tvs] ERROR: Python 3.10+ is required" >&2
  exit 1
fi
