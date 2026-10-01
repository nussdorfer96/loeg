#!/usr/bin/env bash
# Weekly power rankings: compute rankings for the current Sleeper week, then publish the site.
# Run AFTER Wednesday waivers (Sleeper processes claims Wednesday ~3 AM ET), e.g. Wednesday morning.
#   bash scripts/publish_power_rankings.sh                 # current week (Sleeper state display_week)
#   bash scripts/publish_power_rankings.sh --week 6        # any args are passed to scripts/power_rankings.py
#   FORCE=1 bash scripts/publish_power_rankings.sh         # skip the "waivers haven't run yet" guard
# Optional hand-written blurbs: data/power_rankings_blurbs/<season>_wNN.json ({"<manager-id>": "text"}); others are auto-written.
# scripts/publish.sh on its own NEVER recomputes rankings; it re-renders the latest saved
# data/generated/power_rankings/latest.json, so the Tuesday refresh keeps last week's rankings.
set -euo pipefail
cd "$(dirname "$0")/.."
dow=$(date +%u); hr=$(date +%H)   # box clock is America/Detroit; 1=Mon .. 7=Sun
if [[ "${FORCE:-}" != 1 ]] && { [[ $dow == 1 || $dow == 2 ]] || { [[ $dow == 3 ]] && (( 10#$hr < 4 )); }; }; then
  echo "Waivers haven't processed yet this week (Sleeper runs them Wednesday ~3 AM ET). Re-run after that, or FORCE=1." >&2
  exit 1
fi
python3 scripts/power_rankings.py "$@"
bash scripts/publish.sh
