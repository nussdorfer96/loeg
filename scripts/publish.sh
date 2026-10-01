#!/usr/bin/env bash
# Weekly update: refresh Sleeper data, rebuild everything, check links, push dist/ to the gh-pages branch.
# Usage: bash scripts/publish.sh            (add --no-fetch to skip the Sleeper refresh)
# Power rankings are NOT recomputed here: the build renders the highest saved week in data/power_rankings_history/.
# To compute a new week and publish, run scripts/publish_power_rankings.sh (Wednesdays, after waivers).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
if [[ "${1:-}" == "--no-fetch" ]]; then python3 scripts/build_all.py; else python3 scripts/build_all.py --fetch; fi
python3 scripts/check_links.py
REMOTE="$(git -C "$ROOT" remote get-url origin)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone --quiet --branch gh-pages --single-branch "$REMOTE" "$TMP"
find "$TMP" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a dist/. "$TMP"/
touch "$TMP/.nojekyll"
cd "$TMP"
git config user.name "$(git -C "$ROOT" config user.name)"
git config user.email "$(git -C "$ROOT" config user.email)"
git add -A
if git diff --cached --quiet; then
  echo "gh-pages already up to date; nothing to publish."
else
  git commit --quiet -m "Publish site $(date '+%Y-%m-%d %H:%M %Z')"
  git push --quiet origin gh-pages
  echo "Published: https://nussdorfer96.github.io/loeg/ (GitHub Pages usually updates within a minute or two)"
fi
