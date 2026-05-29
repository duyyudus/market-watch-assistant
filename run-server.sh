#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/api-server"

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --reload
