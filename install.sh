#!/bin/sh
# Install the Shiplog skill for Claude Code.
#
#   sh install.sh           into this project: <repo root>/.claude/skills/shiplog
#                           (commit it and everyone on the team gets the skill)
#   sh install.sh --user    into ~/.claude/skills/shiplog, for all your projects
#
# Without a local copy of Shiplog, it downloads the latest version from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/mrxvision97/shiplog/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/mrxvision97/shiplog/main/install.sh | sh -s -- --user
set -eu

REPO="${SHIPLOG_REPO:-mrxvision97/shiplog}"
REF="${SHIPLOG_REF:-main}"
SKILL_PATH="plugins/shiplog/skills/shiplog"

case "${1:-}" in
  --user) dest="$HOME/.claude/skills/shiplog" ;;
  ""|--project) dest="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/skills/shiplog" ;;
  *) echo "usage: install.sh [--project | --user]" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
tmp=""
if [ -n "$here" ] && [ -f "$here/$SKILL_PATH/SKILL.md" ]; then
  src="$here/$SKILL_PATH"
else
  command -v curl >/dev/null || { echo "shiplog: curl is required to download" >&2; exit 1; }
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$tmp"
  src="$(find "$tmp" -type d -path "*/$SKILL_PATH" | head -n 1)"
  [ -n "$src" ] || { echo "shiplog: $SKILL_PATH not found in $REPO@$REF" >&2; exit 1; }
fi

rm -rf "$dest"
mkdir -p "$(dirname "$dest")"
cp -R "$src" "$dest"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "Installed Shiplog to $dest"
echo "Next: open Claude Code in your repo and say \"Set up a changelog for this repo\"."
command -v python3 >/dev/null || echo "Note: Shiplog needs Python 3.10+ (python3 was not found)."
