#!/bin/zsh
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-8765}"

echo "Serving AI news site at http://localhost:$PORT/"
python3 -m http.server "$PORT" --directory "$WORKDIR/site"
