#!/usr/bin/env bash
# Refresh raw Sleeper data for a league. Usage: scripts/fetch_sleeper.sh [league_id] [season]
set -euo pipefail
L=${1:-1387967526775824384}; S=${2:-2026}
D="$(cd "$(dirname "$0")/.." && pwd)/raw/sleeper"; [ "$S" != "2026" ] && D="$D/$S"; mkdir -p "$D"
B=https://api.sleeper.app/v1
curl -sf $B/league/$L -o "$D/sleeper_league.json"
curl -sf $B/league/$L/users -o "$D/sleeper_users.json"
curl -sf $B/league/$L/rosters -o "$D/sleeper_rosters.json"
curl -sf $B/league/$L/drafts -o "$D/drafts.json"
curl -sf $B/league/$L/traded_picks -o "$D/traded_picks.json"
curl -sf $B/league/$L/winners_bracket -o "$D/winners_bracket.json" || true
curl -sf $B/league/$L/losers_bracket -o "$D/losers_bracket.json" || true
curl -sf $B/state/nfl -o "$D/state.json"
for w in $(seq 1 18); do
  curl -sf $B/league/$L/matchups/$w -o "$D/matchups_$w.json"
  curl -sf $B/league/$L/transactions/$w -o "$D/transactions_$w.json"
done
# Games played per player per week (gp from Sleeper's weekly stats; compacted, the raw file is ~2 MB/week)
for w in $(seq 1 18); do
  curl -sf "https://api.sleeper.app/stats/nfl/$S/$w?season_type=regular" -o "$D/.stats_tmp.json" || continue
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));json.dump({str(x['player_id']):x.get('stats',{}).get('gp',0) for x in d if (x.get('stats') or {}).get('gp')},open(sys.argv[2],'w'))" "$D/.stats_tmp.json" "$D/gp_$w.json"
done
rm -f "$D/.stats_tmp.json"
for id in $(python3 -c "import json;print(' '.join(d['draft_id'] for d in json.load(open('$D/drafts.json'))))"); do
  curl -sf $B/draft/$id -o "$D/draft_$id.json"; curl -sf $B/draft/$id/picks -o "$D/draft_${id}_picks.json"
done
# Players DB is ~15 MB; refresh at most weekly.
P="$(dirname "$D")/players_nfl.json"; [ -f "$(dirname "$0")/../raw/sleeper/players_nfl.json" ] && P="$(cd "$(dirname "$0")/.." && pwd)/raw/sleeper/players_nfl.json"
if [ ! -f "$P" ] || [ $(( $(date +%s) - $(stat -c %Y "$P") )) -gt 604800 ]; then curl -sf $B/players/nfl -o "$P"; fi
echo "Sleeper data saved to $D"
