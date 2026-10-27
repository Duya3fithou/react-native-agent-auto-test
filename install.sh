#!/usr/bin/env bash
# Install the rn-smoke-test skill for Claude Code.
#   ./install.sh                    personal skill: ~/.claude/skills/rn-smoke-test (symlink to this repo)
#   ./install.sh --copy             copy the files instead of symlinking
#   ./install.sh --project <path>   project skill: <path>/.claude/skills/rn-smoke-test
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/skills/rn-smoke-test"
MODE="link"
TARGET_ROOT="$HOME/.claude/skills"

while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE="copy" ;;
    --project)
      [ $# -ge 2 ] || { echo "--project needs a path" >&2; exit 1; }
      TARGET_ROOT="$(cd "$2" && pwd)/.claude/skills"
      shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

DEST="$TARGET_ROOT/rn-smoke-test"
mkdir -p "$TARGET_ROOT"
if [ -L "$DEST" ]; then
  rm "$DEST"
elif [ -e "$DEST" ]; then
  BACKUP="$DEST.backup.$(date +%Y%m%d%H%M%S)"
  mv "$DEST" "$BACKUP"
  echo "Existing skill moved to $BACKUP"
fi

chmod +x "$SRC/bin/rnsmoke"
if [ "$MODE" = "copy" ]; then
  cp -R "$SRC" "$DEST"
else
  ln -s "$SRC" "$DEST"
fi
echo "Installed rn-smoke-test -> $DEST ($MODE)"
echo

# First run also bootstraps the Python env (openpyxl) and reports missing tools.
"$DEST/bin/rnsmoke" doctor || true

cat <<'EOF'

Next: start a new Claude Code session and ask, for example:
  "Chạy smoke test cho app React Native ở ~/projects/my-app với file test case ~/Downloads/smoke.xlsx trên iOS"
EOF
