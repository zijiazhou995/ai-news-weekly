#!/bin/zsh
set -euo pipefail

WORKDIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$WORKDIR/automation/com.matchaaa.weekly-ai-news.plist.template"
TARGET="$HOME/Library/LaunchAgents/com.matchaaa.weekly-ai-news.plist"
LABEL="com.matchaaa.weekly-ai-news"

mkdir -p "$HOME/Library/LaunchAgents"
sed "s#/Users/matchaaa/Documents/ai新闻资讯#$WORKDIR#g" "$TEMPLATE" > "$TARGET"

launchctl unload "$TARGET" 2>/dev/null || true
launchctl load "$TARGET"

echo "Installed $LABEL"
echo "Schedule: every Thursday at 09:30"
echo "Drafts: $WORKDIR/outputs"
