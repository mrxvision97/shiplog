#!/bin/sh
# Install the Shiplog skill for Claude Code.
#
#   sh install.sh           into this project: <repo root>/.claude/skills/shiplog
#                           (commit it and everyone on the team gets the skill)
#   sh install.sh --user    into ~/.claude/skills/shiplog, for all your projects
#
# Requires git and Python 3.10+ (checked at the end).
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

# Shiplog's scripts need Python 3.10+. Say so clearly if it isn't there.
found=""
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    [ -n "$ver" ] || continue
    if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      found="$py"; break
    fi
    old="$py $ver"
  fi
done

if [ -n "$found" ]; then
  echo "Found Python $ver ($found)."
  echo "Next: open Claude Code in your repo and say \"Set up a changelog for this repo\"."
else
  cat >&2 <<MSG

  !! Shiplog needs Python 3.10 or newer, and ${old:+only found $old}${old:-none was found}.
     The skill is installed, but its commands won't run until Python is available.

     macOS:          brew install python
     Windows:        winget install Python.Python.3.12
     Debian/Ubuntu:  sudo apt install python3
     Fedora/RHEL:    sudo dnf install python3
     Or download it: https://www.python.org/downloads/

     Then check with: python3 --version

MSG
fi
