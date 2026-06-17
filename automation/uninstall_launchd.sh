#!/bin/zsh
set -euo pipefail

TARGET="$HOME/Library/LaunchAgents/com.matchaaa.weekly-ai-news.plist"
LABEL="com.matchaaa.weekly-ai-news"

if [[ -f "$TARGET" ]]; then
  launchctl unload "$TARGET" 2>/dev/null || true
  rm "$TARGET"
  echo "Uninstalled $LABEL"
else
  echo "$LABEL is not installed"
fi
