#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/market-watch-bot"

exec uv run market-watch worker start "$@"
