#!/usr/bin/env sh
# Install / refresh the portable QA cores into ONE wiki's tools/ directory.
#
# Distinct from install.sh: that one installs SKILLS to ~/.claude/skills (machine-level, once).
# These cores live inside each wiki repo, because they are run from the wiki root and are committed
# with it, so every clone carries its own QA. This script is what keeps those copies from drifting —
# re-run it after `git pull` on the toolkit and every wiki gets the same version from one upstream.
#
#   ./install-wiki-tools.sh                  # install into the current directory's wiki
#   ./install-wiki-tools.sh /path/to/wiki
#   ./install-wiki-tools.sh --check [path]   # report drift, change nothing (exit 1 if any)
#
# Reports per file: NEW / UPDATED (the target had drifted) / unchanged — so an accidental local edit
# surfaces instead of being silently overwritten without mention.
set -eu

CHECK=0
if [ "${1:-}" = "--check" ]; then CHECK=1; shift; fi
WIKI_ROOT="${1:-$(pwd)}"
SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/wiki-tools"

[ -d "$SRC" ] || { echo "Missing $SRC - run this from the llm-wiki-toolkit checkout." >&2; exit 1; }

# A wiki is identified by the CLAUDE.md schema marker plus a wiki/ directory. Refuse anything else
# rather than scattering tools into a random folder.
if [ ! -f "$WIKI_ROOT/CLAUDE.md" ] || [ ! -d "$WIKI_ROOT/wiki" ]; then
  echo "$WIKI_ROOT does not look like an llm-wiki (expected CLAUDE.md and wiki/)." >&2
  exit 1
fi

DEST_DIR="$WIKI_ROOT/tools"
[ "$CHECK" -eq 1 ] || mkdir -p "$DEST_DIR"

new=0; updated=0; same=0
for f in "$SRC"/*.py; do
  name="$(basename "$f")"
  dest="$DEST_DIR/$name"
  if [ ! -f "$dest" ]; then
    [ "$CHECK" -eq 1 ] || cp "$f" "$dest"
    echo "  NEW       $name"
    new=$((new + 1))
  elif cmp -s "$f" "$dest"; then
    echo "  unchanged $name"
    same=$((same + 1))
  else
    [ "$CHECK" -eq 1 ] || cp "$f" "$dest"
    echo "  UPDATED   $name   (target had drifted from the toolkit version)"
    updated=$((updated + 1))
  fi
done

verb=$([ "$CHECK" -eq 1 ] && echo "would change" || echo "installed")
echo "$WIKI_ROOT: $new new, $updated $verb, $same already current  ->  $DEST_DIR"
[ "$CHECK" -eq 1 ] && [ $((new + updated)) -gt 0 ] && exit 1
exit 0
