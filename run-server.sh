#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/market-watch-bot"

exec uv run market-watch server start --host 0.0.0.0 --port "${API_PORT:-8000}" --reload
