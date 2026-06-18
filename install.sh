#!/usr/bin/env bash
# Install the llm-wiki-toolkit skills into your Claude Code skills directory.
# Re-run after `git pull` to update. Copies skills/*.md and skills/*.py to ~/.claude/skills/.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/skills" && pwd)"
DEST="${HOME}/.claude/skills"

mkdir -p "$DEST"
cp "$SRC"/*.md "$SRC"/*.py "$DEST"/

echo "Installed $(ls "$SRC"/*.md "$SRC"/*.py | wc -l) skill files to $DEST"
echo "Next: pip install -r requirements.txt   (for the PDF engine)"
