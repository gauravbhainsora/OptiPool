#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
if [ ! -x .venv/bin/python ]; then
  python3.13 -m venv .venv
fi
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
npm --prefix frontend ci
npm --prefix frontend run build
exec .venv/bin/uvicorn optipool.app:create_app --factory --host 127.0.0.1 --port "${OPTIPOOL_PORT:-8000}"
