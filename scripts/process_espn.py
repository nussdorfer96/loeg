"""Turn raw ESPN season JSON into normalized per-season data files.

Inputs (per season YYYY):
  raw/espn/espn_YYYY_core.json            mTeam/mMatchupScore/mSettings/mDraftDetail/mRoster/mStandings
  raw/espn_players/kona_YYYY.json         public player DB with weekly raw stats (scripts/fetch_espn_players.sh)
  espn_archive/espn_YYYY_wWW.json         OPTIONAL weekly archive (mTransactions2+mMatchup+mBoxscore+mRoster)
  espn_YYYY_tx*.json                      OPTIONAL standalone transaction dumps
Output: data/generated/seasons/YYYY.json
"""
import os, sys, datetime, collections
from common import *

MANAGERS = load(os.path.join(DATA, "managers.json"))


def slot_manager(year, team_id):
    for e in MANAGERS["espn"]["slots"].get(str(team_id), []):
        if e["from"] <= year <= e["to"]:
            return e["manager"]
    raise SystemExit(f"No manager configured for ESPN team {team_id} in {year} (edit data/managers.json)")


def predecessor(year, team_id):
    """Who managed this slot the previous season if it was someone else."""
    for e in MANAGERS["espn"]["slots"].get(str(team_id), []):
        if e["from"] <= year - 1 <= e["to"]:
            return e["manager"]
    return None


def scorer(items):
    def pts(stats, pos):
        slot = POS_SLOT.get(pos)
        s = 0.0
        for it in items:
            v = stats.get(str(it["statId"]))
            if not v:
                continue
            p = it.get("pointsOverrides", {}).get(slot, it["points"]) if slot else it["points"]
            s += v * p
        return s
    return pts


def process(year):
    core = load(os.path.join(RAW, "espn", f"espn_{year}_core.json"))
    if core is None:
        print("missing core", year); return None
    st = core["settings"]
    sched = st["scheduleSettings"]
    reg_weeks = sched["matchupPeriodCount"]
    items = st["scoringSettings"]["scoringItems"]
    pts = scorer(items)
    playoff_teams = sched["playoffTeamCount"]
    # matchup period -> scoring periods (1:1 in this league)
    mp = {int(k): v for k, v in sched.get("matchupPeriods", {}).items()}
    last_week = max(m["matchupPeriodId"] for m in core["schedule"])

    teams = {}
    for t in core["teams"]:
        mid = slot_manager(year, t["id"])
        tc = t.get("transactionCounter", {})
        name = MANAGERS["espn"].get("team_names", {}).get(str(year), {}).get(str(t["id"])) or " ".join(t["name"].split())
        pred = predecessor(year, t["id"])
        teams[t["id"]] = {
            "teamId": t["id"], "manager": mid, "teamName": name, "abbrev": t.get("abbrev"),
            "logo": t.get("logo"), "division": t.get("divisionId"),
            "seed": t.get("playoffSeed"), "finalRank": t.get("rankCalculatedFinal") or t.get("rankFinal"),
            "tookOverFrom": pred if pred and pred != mid else None,
            "transactions": {k: tc.get(k, 0) for k in ("acquisitions", "drops", "trades", "moveToActive", "moveToIR")},
            "w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0,
        }
    divisions = {d["id"]: d["name"] for d in sched.get("divisions", [])}

    # ---- matchups
    games = []
    for m in core["schedule"]:
        wk = m["matchupPeriodId"]
        tier = m.get("playoffTierType", "NONE")
        kind = "regular" if tier == "NONE" else ("playoff" if tier == "WINNERS_BRACKET" else "consolation")
        h = m["home"]; a = m.get("away")
        g = {"week": wk, "kind": kind, "tier": tier,
             "home": {"teamId": h["teamId"], "manager": teams[h["teamId"]]["manager"], "score": r2(h["totalPoints"])},
             "away": None, "winner": None}
        if a:
            g["away"] = {"teamId": a["teamId"], "manager": teams[a["teamId"]]["manager"], "score": r2(a["totalPoints"])}
            hs, as_ = h["totalPoints"], a["totalPoints"]
            g["winner"] = "home" if m["winner"] == "HOME" else "away" if m["winner"] == "AWAY" else ("tie" if m["winner"] == "TIE" else None)
            if g["winner"] is None and (hs or as_):
                g["winner"] = "home" if hs > as_ else "away" if as_ > hs else "tie"
        else:
            g["bye"] = True
        games.append(g)
        if kind == "regular" and a:
            for side, other in (("home", "away"), ("away", "home")):
                T = teams[g[side]["teamId"]]
                T["pf"] += g[side]["score"]; T["pa"] += g[other]["score"]
                if g["winner"] == side: T["w"] += 1
                elif g["winner"] == "tie": T["t"] += 1
                else: T["l"] += 1
    for T in teams.values():
        T["pf"] = r2(T["pf"]); T["pa"] = r2(T["pa"])

    # all-play / luck (regular season)
    by_week = collections.defaultdict(list)
    for g in games:
        if g["kind"] == "regular" and g["away"]:
            by_week[g["week"]] += [(g["home"]["teamId"], g["home"]["score"]), (g["away"]["teamId"], g["away"]["score"])]
    for T in teams.values():
        T["allPlayW"] = T["allPlayL"] = 0
    for wk, lst in by_week.items():
        for tid, s in lst:
            teams[tid]["allPlayW"] += sum(1 for o, os_ in lst if o != tid and s > os_)
            teams[tid]["allPlayL"] += sum(1 for o, os_ in lst if o != tid and s < os_)
    for T in teams.values():
        n = T["allPlayW"] + T["allPlayL"]
        gp = T["w"] + T["l"] + T["t"]
        T["expectedWins"] = r2(T["allPlayW"] / n * gp) if n else 0
        T["luck"] = r2(T["w"] - T["expectedWins"])

    # ---- players: names + weekly league-scoring points from public kona stats
    kona = load(os.path.join(RAW, "espn_players", f"kona_{year}.json"), [])
    players = {}
    weekly = {}
    for p in kona:
        pos = p.get("defaultPositionId")
        if (p.get("id", 0) < 0 and pos != 16) or (p.get("fullName") or "").endswith(" TQB"):
            continue  # skip ESPN "team QB" pseudo-players
        players[p["id"]] = {"name": p.get("fullName"), "pos": POS.get(pos, "?"), "proTeamId": p.get("proTeamId")}
        wpts = {}
        for s in p.get("stats", []) or []:
            if s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1 and s.get("seasonId") == year and s.get("stats"):
                sp = s["scoringPeriodId"]
                if 1 <= sp <= last_week:
                    wpts[sp] = round(pts(s["stats"], pos), 2)
        if wpts:
            weekly[p["id"]] = wpts
    # roster/draft embedded player info fills gaps
    for t in core["teams"]:
        for e in t.get("roster", {}).get("entries", []):
            pl = e["playerPoolEntry"]["player"]
            players.setdefault(pl["id"], {"name": pl["fullName"], "pos": POS.get(pl.get("defaultPositionId"), "?"), "proTeamId": pl.get("proTeamId")})

    def season_pts(pid, upto=None):
        w = weekly.get(pid, {})
        upto = upto or last_week
        return round(sum(v for k, v in w.items() if k <= upto), 2)

    # positional ranks over fantasy season (weeks 1..last_week)
    totals = {pid: season_pts(pid) for pid in weekly}
    pos_rank = {}
    by_pos = collections.defaultdict(list)
    for pid, tot in totals.items():
        by_pos[players.get(pid, {}).get("pos", "?")].append((tot, pid))
    REPL = {"QB": 12, "RB": 30, "WR": 36, "TE": 12, "K": 10, "D/ST": 10}
    repl_pts = {}
    for pos, lst in by_pos.items():
        lst.sort(reverse=True)
        for i, (_, pid) in enumerate(lst):
            pos_rank[pid] = i + 1
        k = REPL.get(pos)
        repl_pts[pos] = lst[k - 1][0] if k and len(lst) >= k else 0

    # ---- ESPN ADP (only reported for players still rostered at season's end)
    adp = {}
    for t in core["teams"]:
        for e in t.get("roster", {}).get("entries", []):
            o = e["playerPoolEntry"]["player"].get("ownership") or {}
            if o.get("averageDraftPosition"): adp[str(e["playerId"])] = round(o["averageDraftPosition"], 1)
    # ---- draft
    picks = []
    for pk in core["draftDetail"].get("picks", []):
        pid = pk["playerId"]; pl = players.get(pid, {"name": f"Player {pid}", "pos": "?"})
        tot = season_pts(pid)
        picks.append({"overall": pk["overallPickNumber"], "round": pk["roundId"], "pick": pk["roundPickNumber"],
                      "teamId": pk["teamId"], "manager": teams[pk["teamId"]]["manager"], "playerId": pid,
                      "name": pl["name"], "pos": pl["pos"], "points": tot, "posRank": pos_rank.get(pid),
                      "vor": round(tot - repl_pts.get(pl["pos"], 0), 2), "keeper": pk.get("keeper", False)})
    # value: compare draft slot to value rank among drafted skill players
    skill = [p for p in picks if p["pos"] in ("QB", "RB", "WR", "TE")]
    for i, p in enumerate(sorted(skill, key=lambda x: -x["vor"])):
        p["valueRank"] = i + 1
    skill_by_pick = sorted(skill, key=lambda x: x["overall"])
    for i, p in enumerate(skill_by_pick):
        p["skillPickRank"] = i + 1
        p["valueDelta"] = p["skillPickRank"] - p["valueRank"]  # + = steal
    steals = sorted([p for p in skill if p["valueRank"] <= 40], key=lambda x: -x["valueDelta"])[:5]
    busts = sorted([p for p in skill if p["round"] <= 4], key=lambda x: x["valueDelta"])[:5]
    for p in steals: p["tag"] = "steal"
    for p in busts: p["tag"] = "bust"

    # ---- final rosters + provisional "points while on roster"
    wk1 = {2020: "2020-09-08", 2021: "2021-09-07", 2022: "2022-09-06", 2023: "2023-09-05", 2024: "2024-09-03", 2025: "2025-09-02"}.get(year)
    wk1d = datetime.datetime.fromisoformat(wk1) if wk1 else None

    def first_week_on_roster(acq_ms):
        if not acq_ms or not wk1d: return 1
        d = datetime.datetime.fromtimestamp(acq_ms / 1000, datetime.timezone.utc).replace(tzinfo=None)
        # a week's main slate locks ~Sunday 17:00 UTC = Tuesday + 5 days
        delta = (d - (wk1d + datetime.timedelta(days=5, hours=17))).total_seconds() / 86400
        return max(1, int(delta // 7) + 2) if delta > 0 else 1

    rosters = {}
    for t in core["teams"]:
        lst = []
        for e in t.get("roster", {}).get("entries", []):
            pl = e["playerPoolEntry"]["player"]; pid = pl["id"]
            fw = first_week_on_roster(e.get("acquisitionDate"))
            w = weekly.get(pid, {})
            on = round(sum(v for k, v in w.items() if k >= fw), 2)
            reg_on = round(sum(v for k, v in w.items() if fw <= k <= reg_weeks), 2)
            lst.append({"playerId": pid, "name": pl["fullName"], "pos": POS.get(pl.get("defaultPositionId"), "?"),
                        "acq": e.get("acquisitionType"), "firstWeek": fw, "ptsOnRoster": on, "regPtsOnRoster": reg_on,
                        "seasonPts": season_pts(pid), "posRank": pos_rank.get(pid)})
        lst.sort(key=lambda x: -x["ptsOnRoster"])
        rosters[t["id"]] = lst

    # ---- weekly archive (box scores, lineups, transactions) if available
    arch_files = find_archive_files(year)
    lineups = {}   # week -> teamId -> list of {playerId, slot, pts}
    proj = {}      # week -> teamId -> {playerId: ESPN projected points (statSourceId 1)}
    tx = {}
    for wk, path in arch_files.items():
        d = load(path, {})
        for m in d.get("schedule", []):
            if m.get("matchupPeriodId") != wk:
                continue  # boxscore rosters are only meaningful for the file's scoring period
            for side in ("home", "away"):
                sd = m.get(side)
                if not sd: continue
                ros = sd.get("rosterForCurrentScoringPeriod") or sd.get("rosterForMatchupPeriod")
                if not ros or not ros.get("entries"): continue
                ent = []
                for e in ros["entries"]:
                    ppe = e.get("playerPoolEntry", {})
                    pl = ppe.get("player", {})
                    pid = e.get("playerId") or pl.get("id")
                    if pl.get("fullName"):
                        players.setdefault(pid, {"name": pl["fullName"], "pos": POS.get(pl.get("defaultPositionId"), "?")})
                    ent.append({"playerId": pid, "slot": e.get("lineupSlotId"), "pts": r2(ppe.get("appliedStatTotal", 0))})
                    pj = next((st.get("appliedTotal") for st in pl.get("stats", []) or []
                               if st.get("statSourceId") == 1 and st.get("scoringPeriodId") == wk and st.get("statSplitTypeId") == 1), None)
                    if pj is not None and wk >= 1:
                        proj.setdefault(wk, {}).setdefault(sd["teamId"], {})[str(pid)] = r2(pj)
                if wk >= 1:
                    lineups.setdefault(wk, {})[sd["teamId"]] = ent
        for t in d.get("transactions", []) or []:
            tx[t["id"]] = t
    for p in find_tx_files(year):
        for t in (load(p, {}) or {}).get("transactions", []) or []:
            tx[t["id"]] = t

    lineup_stats = None
    if lineups:
        lineup_stats = {}
        for wk, tm in lineups.items():
            for tid, ent in tm.items():
                if tid not in teams: continue
                L = lineup_stats.setdefault(tid, {"bench": 0.0, "started": collections.Counter(), "weeksCovered": 0, "games": []})
                b = sum(x["pts"] or 0 for x in ent if x["slot"] == 20)
                L["bench"] += b; L["weeksCovered"] += 1
                for x in ent:
                    if x["slot"] not in BENCH_SLOTS:
                        L["started"][x["playerId"]] += x["pts"] or 0
                        L["games"].append({"week": wk, "playerId": x["playerId"], "pts": x["pts"] or 0})

    transactions = []
    for t in tx.values():
        if t.get("status") != "EXECUTED": continue
        typ = t.get("type")
        if typ not in ("FREEAGENT", "WAIVER", "TRADE_ACCEPT", "TRADE_PROPOSAL", "TRADE_UPHOLD"): continue
        its = [i for i in t.get("items", []) if i.get("type") in ("ADD", "DROP", "TRADE")]
        if not its: continue
        transactions.append({"id": t["id"], "type": "TRADE" if "TRADE" in typ else typ, "rawType": typ,
                             "week": t.get("scoringPeriodId"), "date": t.get("proposedDate"), "teamId": t.get("teamId"),
                             "bid": t.get("bidAmount", 0),
                             "items": [{"type": i["type"], "playerId": i["playerId"], "from": i.get("fromTeamId"), "to": i.get("toTeamId")} for i in its]})
    # dedupe trades that appear as proposal+accept+uphold
    seen, deduped = set(), []
    for t in sorted(transactions, key=lambda x: (x["date"] or 0)):
        if t["type"] == "TRADE":
            key = frozenset((i["playerId"], i["from"], i["to"]) for i in t["items"])
            if key in seen: continue
            seen.add(key)
        deduped.append(t)
    transactions = deduped
    for t in transactions:
        for i in t["items"]:
            i["name"] = players.get(i["playerId"], {}).get("name", f"Player {i['playerId']}")
            i["pos"] = players.get(i["playerId"], {}).get("pos", "?")
            for k in ("from", "to"):
                if i.get(k) in teams: i[k + "Manager"] = teams[i[k]]["manager"]

    # ---- playoff bracket structure
    playoff_games = [g for g in games if g["kind"] == "playoff"]
    champ = next((T for T in teams.values() if T["finalRank"] == 1), None)
    runner = next((T for T in teams.values() if T["finalRank"] == 2), None)
    final_game = None
    if playoff_games:
        lw = max(g["week"] for g in playoff_games)
        fg = [g for g in playoff_games if g["week"] == lw and g["away"]]
        final_game = fg[0] if fg else None
        if final_game: final_game["isFinal"] = True

    out = {
        "year": year, "platform": "ESPN", "format": "redraft", "leagueName": st.get("name"),
        "regularSeasonWeeks": reg_weeks, "lastWeek": last_week, "playoffTeams": playoff_teams,
        "playoffSeeding": sched.get("playoffSeedingRule"), "divisions": divisions,
        "rosterSlots": st["rosterSettings"]["lineupSlotCounts"],
        "teams": sorted(teams.values(), key=lambda x: x["finalRank"] or 99),
        "games": games, "champion": champ and champ["manager"], "runnerUp": runner and runner["manager"],
        "draft": sorted(picks, key=lambda x: x["overall"]),
        "rosters": {str(k): v for k, v in rosters.items()},
        "playerWeekly": {str(pid): weekly[pid] for pid in set(
            [p["playerId"] for p in picks] + [e["playerId"] for r in rosters.values() for e in r]) if pid in weekly},
        "players": {str(pid): players[pid] for pid in set(
            [p["playerId"] for p in picks] + [e["playerId"] for r in rosters.values() for e in r]
            + [i["playerId"] for t in transactions for i in t["items"]]
            + ([x["playerId"] for tm in lineups.values() for ent in tm.values() for x in ent] if lineups else [])) if pid in players},
        "posRank": {str(pid): pos_rank[pid] for pid in pos_rank if pos_rank[pid] <= 60},
        "seasonPoints": {str(pid): totals[pid] for pid in totals if pos_rank.get(pid, 999) <= 60},
        "archive": {"weeks": sorted(arch_files.keys()), "lineupWeeks": sorted(lineups.keys()), "transactions": len(transactions)},
        "transactions": transactions,
        "lineupsByWeek": {str(wk): {str(tid): [[str(x["playerId"]), x["slot"], x["pts"]] for x in ent] for tid, ent in tm.items()} for wk, tm in lineups.items()},
        "projByWeek": {str(wk): {str(t): v for t, v in tm.items()} for wk, tm in proj.items()},
        "adp": adp,
        "lineups": {str(tid): {"bench": r2(L["bench"]), "weeksCovered": L["weeksCovered"],
                               "started": {str(k): r2(v) for k, v in L["started"].most_common(25)},
                               "topGames": sorted(L["games"], key=lambda x: -x["pts"])[:10]}
                    for tid, L in (lineup_stats or {}).items()},
    }
    # top-60 players need names too
    for pid in out["posRank"]:
        if pid not in out["players"] and int(pid) in players:
            out["players"][pid] = players[int(pid)]
    save(os.path.join(GEN, "seasons", f"{year}.json"), out)
    print(year, "teams", len(teams), "games", len(games), "picks", len(picks), "archive weeks", len(arch_files),
          "lineup weeks", len(lineups), "tx", len(transactions), "champ", out["champion"])
    return out


if __name__ == "__main__":
    years = [int(y) for y in sys.argv[1:]] or [2020, 2021, 2022, 2023, 2024, 2025]
    for y in years:
        process(y)
