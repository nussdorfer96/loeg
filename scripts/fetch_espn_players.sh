#!/usr/bin/env bash
# Public ESPN player DB (names + weekly raw stats) for a season. No auth needed. Usage: scripts/fetch_espn_players.sh 2026
set -euo pipefail
Y=$1; D="$(cd "$(dirname "$0")/.." && pwd)/raw/espn_players"; mkdir -p "$D"
curl -sf "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/$Y/players?scoringPeriodId=0&view=kona_player_info" \
  -H 'X-Fantasy-Filter: {"filterActive":null}' -o "$D/kona_$Y.json"
echo "saved $D/kona_$Y.json"
