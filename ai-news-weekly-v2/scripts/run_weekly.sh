#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m ai_news_weekly.pipeline "$@"
