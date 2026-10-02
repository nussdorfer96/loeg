"""Normalize a Sleeper season into data/generated/seasons/YYYY.json (same shape as ESPN seasons where possible)."""
import os, sys, glob, collections
from common import *

MANAGERS = load(os.path.join(DATA, "managers.json"))



def games_played(D, player_pts, done_weeks):
    """Games each player actually played in completed weeks: Sleeper's weekly 'gp' stat (bye/inactive weeks don't count).
    Only weeks with a league scoring record count, so PPG = league points / those games.
    Falls back to weeks with nonzero points when the stats file for a week is missing."""
    out = {}
    gpw = {w: load(os.path.join(D, f"gp_{w}.json")) for w in range(1, (done_weeks or 0) + 1)}
    for pid, w in player_pts.items():
        n = 0
        for wk in range(1, (done_weeks or 0) + 1):
            if wk not in w: continue   # no league scoring record that week (e.g. not yet on a roster in this league)
            g = gpw.get(wk)
            if g:
                n += 1 if g.get(str(pid)) else 0
            elif w.get(wk):
                n += 1
        out[pid] = n
    return out

def process(year=2026):
    D = os.path.join(RAW, "sleeper") if year == 2026 else os.path.join(RAW, "sleeper", str(year))
    league = load(os.path.join(D, "sleeper_league.json"))
    users = {u["user_id"]: u for u in load(os.path.join(D, "sleeper_users.json"))}
    rosters = load(os.path.join(D, "sleeper_rosters.json"))
    P = load(os.path.join(RAW, "sleeper", "players_nfl.json"), {})
    umap = MANAGERS["sleeper"]["users"]
    tn_over = MANAGERS["sleeper"].get("team_names", {}).get(str(year), {})
    S = league["settings"]
    done_weeks = S.get("last_scored_leg") or 0
    reg_end = S.get("playoff_week_start", 15) - 1

    def pinfo(pid):
        p = P.get(pid, {})
        if not p and pid.isalpha():
            return {"name": f"{pid} D/ST", "pos": "DEF", "team": pid}
        return {"name": p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip() or pid,
                "pos": p.get("position") or "?", "team": p.get("team"), "age": p.get("age"), "yearsExp": p.get("years_exp")}

    teams = {}
    for r in rosters:
        u = users.get(r["owner_id"], {})
        cfg = umap.get(r["owner_id"], {})
        name = tn_over.get(r["owner_id"]) or (u.get("metadata") or {}).get("team_name") or u.get("display_name")
        s = r["settings"]
        teams[r["roster_id"]] = {
            "teamId": r["roster_id"], "manager": cfg.get("manager"), "managerConfirmed": cfg.get("confirmed", False),
            "sleeperUser": u.get("display_name"), "teamName": " ".join((name or "").split()), "avatar": (u.get("metadata") or {}).get("avatar"),
            "officialW": s.get("wins", 0), "officialL": s.get("losses", 0), "officialT": s.get("ties", 0),
            "pf": r2(s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100), "pa": r2(s.get("fpts_against", 0) + s.get("fpts_against_decimal", 0) / 100),
            "maxPF": r2(s.get("ppts", 0) + s.get("ppts_decimal", 0) / 100),
            "w": 0, "l": 0, "t": 0, "medW": 0, "medL": 0,
            "transactions": {"acquisitions": 0, "drops": 0, "trades": 0},
            "players": r.get("players") or [], "taxi": r.get("taxi") or [], "reserve": r.get("reserve") or [],
            "starters": r.get("starters") or [], "seed": None, "finalRank": None, "tookOverFrom": None,
        }

    games, lineups, player_pts, lbw, sbw = [], {}, collections.defaultdict(dict), {}, {}
    for wk in range(1, done_weeks + 1):
        ms = load(os.path.join(D, f"matchups_{wk}.json"), []) or []
        if not ms or all((m.get("points") or 0) == 0 for m in ms):
            continue
        by = collections.defaultdict(list)
        for m in ms:
            by[m["matchup_id"]].append(m)
            T = teams[m["roster_id"]]
            started = set(m.get("starters") or [])
            stash = set(T["taxi"]) | set(T["reserve"])  # current taxi/IR players don't count as bench points
            bench = sum(v for k, v in (m.get("players_points") or {}).items() if k not in started and k not in stash)
            lineups.setdefault(m["roster_id"], {"bench": 0.0, "weeks": 0, "started": collections.Counter(), "games": []})
            L = lineups[m["roster_id"]]
            L["bench"] += bench; L["weeks"] += 1
            for pid, pts in zip(m.get("starters") or [], m.get("starters_points") or []):
                L["started"][pid] += pts; L["games"].append({"week": wk, "playerId": pid, "pts": pts})
            sbw.setdefault(str(wk), {})[str(m["roster_id"])] = list(m.get("starters") or [])
            for pid, pts in (m.get("players_points") or {}).items():
                player_pts[pid][wk] = pts
            lbw.setdefault(str(wk), {})[str(m["roster_id"])] = [[pid, "ST" if pid in started else ("TX" if pid in stash else "BE"), r2(pts)] for pid, pts in (m.get("players_points") or {}).items()]
        scores = sorted([m["points"] for m in ms])
        median = (scores[len(scores) // 2 - 1] + scores[len(scores) // 2]) / 2
        for mid, pair in by.items():
            if len(pair) != 2 or mid is None:
                continue
            a, b = pair
            kind = "regular" if wk <= reg_end else "playoff"
            g = {"week": wk, "kind": kind, "tier": "NONE",
                 "home": {"teamId": a["roster_id"], "manager": teams[a["roster_id"]]["manager"], "score": r2(a["points"])},
                 "away": {"teamId": b["roster_id"], "manager": teams[b["roster_id"]]["manager"], "score": r2(b["points"])}}
            g["winner"] = "home" if a["points"] > b["points"] else "away" if b["points"] > a["points"] else "tie"
            games.append(g)
            if kind == "regular":
                for side in ("home", "away"):
                    T = teams[g[side]["teamId"]]
                    if g["winner"] == side: T["w"] += 1
                    elif g["winner"] == "tie": T["t"] += 1
                    else: T["l"] += 1
        for m in ms:
            T = teams[m["roster_id"]]
            if m["points"] > median: T["medW"] += 1
            else: T["medL"] += 1

    # all-play luck
    byw = collections.defaultdict(list)
    for g in games:
        if g["kind"] == "regular":
            byw[g["week"]] += [(g["home"]["teamId"], g["home"]["score"]), (g["away"]["teamId"], g["away"]["score"])]
    for T in teams.values():
        T["allPlayW"] = T["allPlayL"] = 0
    for lst in byw.values():
        for tid, s in lst:
            teams[tid]["allPlayW"] += sum(1 for o, x in lst if o != tid and s > x)
            teams[tid]["allPlayL"] += sum(1 for o, x in lst if o != tid and s < x)
    for T in teams.values():
        n = T["allPlayW"] + T["allPlayL"]; gp = T["w"] + T["l"] + T["t"]
        T["expectedWins"] = r2(T["allPlayW"] / n * gp) if n else 0
        T["luck"] = r2(T["w"] - T["expectedWins"])
        T["luckX"] = (T["w"] - T["allPlayW"] / n * gp) if n else 0  # full precision, for ties

    # transactions
    txs = {}
    for f in glob.glob(os.path.join(D, "transactions_*.json")):
        for t in load(f, []) or []:
            if t.get("status") == "complete":
                txs[t["transaction_id"]] = t
    transactions = []
    for t in sorted(txs.values(), key=lambda x: x["created"]):
        items = []
        for pid, rid in (t.get("adds") or {}).items():
            frm = (t.get("drops") or {}).get(pid) if t["type"] == "trade" else None
            items.append({"type": "TRADE" if t["type"] == "trade" else "ADD", "playerId": pid, **pinfo(pid), "to": rid, "from": frm or 0})
        for pid, rid in (t.get("drops") or {}).items():
            if t["type"] == "trade" and pid in (t.get("adds") or {}):
                continue
            items.append({"type": "DROP", "playerId": pid, **pinfo(pid), "from": rid, "to": 0})
        for it in items:
            for k in ("from", "to"):
                if it.get(k) in teams: it[k + "Manager"] = teams[it[k]]["manager"]
        picks = [{"season": p["season"], "round": p["round"], "originalRosterId": p["roster_id"],
                  "from": p["previous_owner_id"], "to": p["owner_id"],
                  "fromManager": teams.get(p["previous_owner_id"], {}).get("manager"),
                  "toManager": teams.get(p["owner_id"], {}).get("manager"),
                  "originalManager": teams.get(p["roster_id"], {}).get("manager")} for p in t.get("draft_picks") or []]
        typ = {"trade": "TRADE", "waiver": "WAIVER", "free_agent": "FREEAGENT"}.get(t["type"], t["type"].upper())
        transactions.append({"id": t["transaction_id"], "type": typ, "week": t.get("leg"), "date": t["created"],
                             "rosterIds": t.get("roster_ids"), "items": items, "picks": picks,
                             "bid": None})  # league uses traditional waivers, not FAAB
        for rid in t.get("roster_ids") or []:
            if rid not in teams: continue
            if typ == "TRADE": teams[rid]["transactions"]["trades"] += 1
            else:
                teams[rid]["transactions"]["acquisitions"] += sum(1 for i in items if i["type"] == "ADD" and i["to"] == rid)
                teams[rid]["transactions"]["drops"] += sum(1 for i in items if i["type"] == "DROP" and i["from"] == rid)

    # drafts
    drafts = []
    for f in sorted(glob.glob(os.path.join(D, "draft_*_picks.json"))):
        did = os.path.basename(f).split("_")[1]
        meta = load(os.path.join(D, f"draft_{did}.json"), {})
        pk = []
        for p in load(f, []):
            pi = pinfo(p["player_id"])
            pts = sum(player_pts.get(p["player_id"], {}).values())
            pk.append({"overall": p["pick_no"], "round": p["round"], "pick": p.get("draft_slot"), "teamId": p["roster_id"],
                       "manager": teams.get(p["roster_id"], {}).get("manager"), "playerId": p["player_id"],
                       "name": pi["name"], "pos": p["metadata"].get("position") or pi["pos"], "nflTeam": p["metadata"].get("team"),
                       "yearsExp": p["metadata"].get("years_exp"), "points": r2(pts)})
        drafts.append({"id": did, "type": meta.get("type"), "season": meta.get("season"), "rounds": meta.get("settings", {}).get("rounds"),
                       "status": meta.get("status"), "start": meta.get("start_time"), "kind": "startup" if len(drafts) == 0 else "rookie",
                       "slotToTeam": meta.get("slot_to_roster_id"), "picks": sorted(pk, key=lambda x: x["overall"])})

    traded = [{"season": p["season"], "round": p["round"], "originalRosterId": p["roster_id"], "owner": p["owner_id"],
               "previousOwner": p["previous_owner_id"], "originalManager": teams.get(p["roster_id"], {}).get("manager"),
               "ownerManager": teams.get(p["owner_id"], {}).get("manager")} for p in load(os.path.join(D, "traded_picks.json"), []) or []]

    roster_out = {}
    for rid, T in teams.items():
        lst = []
        for pid in T["players"]:
            pi = pinfo(pid)
            pts = player_pts.get(pid, {})
            lst.append({"playerId": pid, **pi, "seasonPts": r2(sum(pts.values())),
                        "status": "taxi" if pid in T["taxi"] else "IR" if pid in T["reserve"] else "active"})
        lst.sort(key=lambda x: (-(x["seasonPts"] or 0)))
        roster_out[str(rid)] = lst
        del T["players"], T["taxi"], T["reserve"], T["starters"]

    # current standings order: official wins, then PF
    order = sorted(teams.values(), key=lambda T: (-T["officialW"], -T["pf"]))
    for i, T in enumerate(order):
        T["standing"] = i + 1
    # NFL team per player per week, from Sleeper's weekly stats (statline_W.json 'tm', saved by fetch_sleeper.sh)
    nfl_by_week = {}
    for w in range(1, 19):
        st = load(os.path.join(D, f"statline_{w}.json"), {}) or {}
        tw = {pid: v["tm"] for pid, v in st.items() if isinstance(v, dict) and v.get("tm")}
        if tw: nfl_by_week[str(w)] = tw
    players = {}
    for pid in set(list(player_pts.keys()) + [p["playerId"] for d in drafts for p in d["picks"]]):
        players[pid] = pinfo(pid)
    out = {
        "year": year, "platform": "Sleeper", "format": "dynasty", "leagueName": league["name"], "leagueId": league["league_id"],
        "status": league["status"], "completedWeeks": done_weeks, "regularSeasonWeeks": reg_end,
        "playoffTeams": S.get("playoff_teams"), "medianGame": bool(S.get("league_average_match")),
        "rosterPositions": league.get("roster_positions"), "scoringType": "PPR",
        "settings": {k: S.get(k) for k in ("taxi_slots", "reserve_slots", "trade_deadline", "waiver_type", "waiver_clear_days", "draft_rounds", "pick_trading", "playoff_week_start")},
        "teams": order, "games": games, "champion": None, "runnerUp": None,
        "drafts": drafts, "draft": drafts[0]["picks"] if drafts else [], "rosters": roster_out,
        "transactions": transactions, "tradedPicks": traded, "players": players,
        "nflTeamByWeek": nfl_by_week,
        "playerWeekly": {pid: {str(k): v for k, v in w.items()} for pid, w in player_pts.items()},
        "gamesPlayed": games_played(D, player_pts, done_weeks),
        "lineupsByWeek": lbw,
        "startersByWeek": sbw,   # starters in roster_positions order (for slot labels in box scores)
        "lineups": {str(rid): {"bench": r2(L["bench"]), "weeksCovered": L["weeks"],
                               "started": {k: r2(v) for k, v in L["started"].most_common(25)},
                               "topGames": sorted(L["games"], key=lambda x: -x["pts"])[:10]} for rid, L in lineups.items()},
    }
    save(os.path.join(GEN, "seasons", f"{year}.json"), out)
    print(year, "sleeper teams", len(teams), "games", len(games), "tx", len(transactions), "drafts", [(d["kind"], len(d["picks"])) for d in drafts])


if __name__ == "__main__":
    process(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
