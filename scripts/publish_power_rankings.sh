#!/usr/bin/env bash
# Weekly power rankings: compute rankings for the current Sleeper week, then publish the site.
# Run AFTER Wednesday waivers (Sleeper processes claims Wednesday ~3 AM ET), e.g. Wednesday morning.
#   bash scripts/publish_power_rankings.sh                 # current week (Sleeper state display_week)
#   bash scripts/publish_power_rankings.sh --week 6        # any args are passed to scripts/power_rankings.py
#   FORCE=1 bash scripts/publish_power_rankings.sh         # skip the "waivers haven't run yet" guard
# Optional hand-written blurbs: data/power_rankings_blurbs/<season>_wNN.json ({"<manager-id>": "text"}); others are auto-written.
# Each week is saved to data/power_rankings_history/<season>_wNN.json and committed + pushed to main (only that file),
# so the movement chart's history survives a box wipe.
# scripts/publish.sh on its own NEVER recomputes rankings; it re-renders the highest saved week, so the Tuesday
# refresh keeps last week's rankings.
set -euo pipefail
cd "$(dirname "$0")/.."
dow=$(date +%u); hr=$(date +%H)   # box clock is America/Detroit; 1=Mon .. 7=Sun
if [[ "${FORCE:-}" != 1 ]] && { [[ $dow == 1 || $dow == 2 ]] || { [[ $dow == 3 ]] && (( 10#$hr < 4 )); }; }; then
  echo "Waivers haven't processed yet this week (Sleeper runs them Wednesday ~3 AM ET). Re-run after that, or FORCE=1." >&2
  exit 1
fi
python3 scripts/power_rankings.py "$@"
HIST=data/power_rankings_history
if [[ -n "$(git status --porcelain -- "$HIST")" ]]; then
  git add -- "$HIST"
  git commit --quiet -m "Power rankings: $(ls "$HIST" | sort | tail -1 | sed 's/.json//')" -- "$HIST"
  git push --quiet origin HEAD:main || echo "WARNING: could not push $HIST to main (pull --rebase and push manually)." >&2
fi
bash scripts/publish.sh
