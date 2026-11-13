#!/bin/sh
# Run the map checks against the shell this change replaces, to show that they fail there.
#
# The prior shell (the merge of PR #41) put the key inside the map box and fitted Sweden to the
# broad `sverige` view, so there is no `.ot-map-canvas` to measure and the country only covers
# about half the box height. check_map_key.py must complain about both; if it passes, the checks
# are not testing what this change did.
#
#   screen/tools/check_prior_shell.sh [git-ref]
#
# The ref defaults to the shell from PR #41; the output is committed next to this change's
# evidence in screen/review/2026-11-13-map-phone/check-prior-shell.txt.
set -eu

ref=${1:-7c2cbfec370bbdf5b91431b0a2605cc811ccfe99}
screen=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$screen/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/shell/data"
for f in frame.html shell.css shell.js; do
  git -C "$repo" show "$ref:screen/shell/$f" > "$tmp/shell/$f"
done
cp "$screen/shell/data/lan-sverige.json" "$tmp/shell/data/"

cd "$repo"
echo "Measured on the prior shell ($ref), table only:"
uv run --project server python screen/tools/check_map_key.py --shell "$tmp/shell" --table-only
echo
echo "The same checks, with their assertions:"
if uv run --project server python screen/tools/check_map_key.py --shell "$tmp/shell"; then
  echo "UNEXPECTED: the checks passed on the prior shell ($ref); they no longer pin the new layout." >&2
  exit 1
fi
echo "OK: the checks fail on the prior shell ($ref), as they should."
