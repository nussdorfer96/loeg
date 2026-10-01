#!/usr/bin/env python3
"""Scaffold next week's roast file (roasts drop Wednesdays 6 PM ET, after waivers): data/roasts/<season>_wNN.json (then write the jokes by hand and commit).
Usage: python3 scripts/new_roast.py [--week N]
Pre-fills manager / owner / team / record from the latest saved power rankings (data/power_rankings_history/)
in power-ranking order, with empty roast / this_week / prediction fields. The Dynasty page shows the highest week.
Fields: title, preview (one-line teaser on the collapsed card), schedule_note, intro, facts_note, entries[]."""
import argparse, glob, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int); a = ap.parse_args()
pr = sorted(glob.glob(os.path.join(ROOT, "data", "power_rankings_history", "*_w*.json")))
if not pr:
    raise SystemExit("no power rankings saved yet; run scripts/power_rankings.py first")
P = json.load(open(pr[-1])); season, week = P["meta"]["season"], a.week or P["meta"]["week"]
out = os.path.join(ROOT, "data", "roasts", f"{season}_w{int(week):02d}.json")
if os.path.exists(out):
    raise SystemExit(f"{out} already exists")
doc = {"season": int(season), "week": int(week), "title": f"🔥 The Roast: Week {week}", "preview": "",
       "schedule_note": "New roasts drop every Wednesday at 6 PM ET, right after waivers and before Thursday night.",
       "intro": "Wow, that just happened. What's next?", "facts_note": "Every fact is real Sleeper data. A roast among friends.",
       "entries": [{"manager": t["manager_id"], "owner": t["owner"], "team": t["team"], "record": t["record"],
                    "roast": "", "this_week": "", "prediction": ""} for t in P["teams"]]}
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(doc, open(out, "w"), indent=1, ensure_ascii=False)
print("wrote", out)
