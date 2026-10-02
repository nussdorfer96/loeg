"""Build league-wide history (managers, H2H, records, awards, stories, lore) from normalized seasons.
Output: data/generated/league.json
"""
import os, glob, collections, re, statistics
from common import *

MANAGERS = load(os.path.join(DATA, "managers.json"))
MGR = {m["id"]: m for m in MANAGERS["managers"]}
LORE = load(os.path.join(DATA, "lore.json"), {"entries": []})
BELT = LORE.get("belt") or {"name": "The Belt", "introduced": 9999}
BELT_YEAR = BELT.get("introduced", 9999)
SEATS = MANAGERS.get("sleeper", {}).get("seat_successions", [])  # display-only lineage; no stats carry over


def nm(mid):
    return MGR.get(mid, {}).get("name", mid or "Unknown")


def first(mid):
    return nm(mid).split()[0]


def norm_name(n):
    n = (n or "").lower().replace(".", "").replace("'", "")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"[^a-z]", "", n)


def fmt(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def succ_line(s):
    if s.get("kind") == "seat":
        return f" {s['name']} took the {ordinal_s(s['seat']) if s.get('seat') else 'open'} seat he vacated in {s['year']} (no history carried over)."
    return f" The team slot passed to {s['name']} in {s['year']}."


def rp(p):
    """Draft slot as R.PP, e.g. 1.01, 3.07, 10.04."""
    return f"{p['round']}.{p['pick']:02d}"


def is_starter(slot):
    return slot not in (20, 21, "BE", "IR", "TX")


def load_seasons():
    out = {}
    for p in sorted(glob.glob(os.path.join(GEN, "seasons", "*.json"))):
        s = load(p); out[s["year"]] = s
    sl = [y for y, s in out.items() if s.get("platform") == "Sleeper"]
    CURRENT_SLEEPER_YEAR[0] = max(sl) if sl else None
    return out


def team_of(season, tid):
    for T in season["teams"]:
        if T["teamId"] == tid: return T


def pname(season, pid):
    p = season.get("players", {}).get(str(pid))
    return p["name"] if p else f"Player {pid}"


def nfl_of(season, pid, week=None):
    """NFL team abbreviation for a player IN THAT SEASON (never today's team for a past season).
    Weekly contexts use the team he played for that week; otherwise the team he finished the season with."""
    if pid is None: return None
    if week is not None:
        t = ((season.get("nflTeamByWeek") or {}).get(str(week)) or {}).get(str(pid))
        if t: return NFL_ABBR.get(t) if isinstance(t, int) else t
    p = season.get("players", {}).get(str(pid)) or {}
    if season.get("platform") == "ESPN":
        if p.get("nfl"): return p["nfl"]
        wk = [int(w) for w, m in (season.get("nflTeamByWeek") or {}).items() if str(pid) in m]
        return NFL_ABBR.get(season["nflTeamByWeek"][str(max(wk))][str(pid)]) if wk else None
    # Sleeper: latest week's team from the season's own weekly stats; the live players DB only for the current season
    wk = [int(w) for w, m in (season.get("nflTeamByWeek") or {}).items() if str(pid) in m]
    if wk: return season["nflTeamByWeek"][str(max(wk))][str(pid)]
    if season.get("year") == CURRENT_SLEEPER_YEAR[0] and p.get("team") and p.get("pos") != "DEF": return p["team"]
    return None


CURRENT_SLEEPER_YEAR = [None]


def plab(season, pid, name, pos, week=None):
    """'Name (POS, TEAM)' label with the player's NFL team for that season/week."""
    t = nfl_of(season, pid, week)
    return f"{name} ({pos}, {t})" if t else f"{name} ({pos})"


def ppos(season, pid):
    p = season.get("players", {}).get(str(pid))
    return p.get("pos", "?") if p else "?"


def lineup_coverage(s):
    lw = s.get("lineupsByWeek") or {}
    need = s.get("lastWeek") or s.get("completedWeeks") or 0
    if s["platform"] == "Sleeper":
        need = s.get("completedWeeks", 0)
    have = len([w for w in lw if 1 <= int(w) <= need])
    return have, need


def _eq(a, b):
    return abs((a or 0) - (b or 0)) < 1e-6


def _holders(cands, best):
    """cands: [(value, manager, headline)]; every candidate whose value equals best (ties, full precision), unique per manager+headline."""
    out, seen = [], set()
    for v, m, h in cands:
        if _eq(v, best) and (m, h) not in seen:
            seen.add((m, h)); out.append({"manager": m, "headline": h})
    return out


def _pg(s, p, inner=False):
    """' (14.2 PPG over 15 games)' for a drafted player's season, from weekly lines (games actually played)."""
    w = (s.get("playerWeekly") or {}).get(str(p.get("playerId")))
    if not w: return ""
    gp = len(w); txt = f"{sum(w.values()) / gp:.1f} PPG over {gp} games"
    return f", {txt}" if inner else f" ({txt})"


# Commissioner-approved asterisks on score records (Ryan, Oct 2026). Key: (year, week, manager).
RECORD_ASTERISKS = {(2025, 14, "jacob-maddox"): {"note": "The Betrayal — benched on purpose", "lore": "the-betrayal"}}

# ESPN stat ids -> labels for real box-score stat lines (kona weekly actuals, statSourceId 0).
_ESPN_STAT = {"passCmp": "1", "passAtt": "0", "passYds": "3", "passTD": "4", "int": "20", "rushAtt": "23", "rushYds": "24", "rushTD": "25",
              "rec": "53", "tgt": "58", "recYds": "42", "recTD": "43", "fumLost": "72"}
_KONA = {}


def espn_stat_line(year, week, pid):
    """Real stat line from the ESPN public player archive, or None if not available."""
    if year not in _KONA:
        fp = os.path.join(ROOT, "raw", "espn_players", f"kona_{year}.json")
        _KONA[year] = {str(p.get("id")): p for p in (json.load(open(fp)) if os.path.exists(fp) else [])}
    p = _KONA[year].get(str(pid))
    if not p: return None
    st = next((x["stats"] for x in p.get("stats") or [] if x.get("statSourceId") == 0 and x.get("statSplitTypeId") == 1
               and x.get("seasonId") == year and x.get("scoringPeriodId") == week and x.get("stats")), None)
    if not st: return None
    v = lambda k: int(round(st.get(_ESPN_STAT[k], 0) or 0))
    parts = []
    if v("passAtt"):
        parts.append(f"{v('passCmp')}/{v('passAtt')}, {v('passYds')} pass yds, {v('passTD')} TD" + (f", {v('int')} INT" if v("int") else ""))
    if v("rushAtt") or v("rushYds"):
        parts.append(f"{v('rushAtt')} rush, {v('rushYds')} yds" + (f", {v('rushTD')} TD" if v("rushTD") else ""))
    if v("rec") or v("recYds"):
        parts.append(f"{v('rec')} rec, {v('recYds')} yds" + (f", {v('recTD')} TD" if v("recTD") else ""))
    if v("fumLost"): parts.append(f"{v('fumLost')} fum lost")
    return " · ".join(parts) or None


def top_starter(s, week, manager):
    T = next((t for t in s["teams"] if t["manager"] == manager), None)
    ent = ((s.get("lineupsByWeek") or {}).get(str(week)) or {}).get(str(T["teamId"])) if T else None
    st = [(pts, pid) for pid, slot, pts in (ent or []) if is_starter(slot)]
    if not st: return None
    pts, pid = max(st, key=lambda t: t[0])
    return {"name": pname(s, pid), "pos": ppos(s, pid), "nfl": nfl_of(s, pid, week), "pts": pts}


def records_that_matter(records, seasons, profiles, team_mvps, years):
    """Headline cards for the top of the Record Book (Ryan's list, Oct 2026). All values from data; ties keep every holder."""
    R = records; H = {}
    hi = R["highScores"][0]
    H["high"] = dict(hi, mvp=top_starter(seasons[hi["year"]], hi["week"], hi["manager"]))
    H["closest"] = R["closest"][0]
    pg = R["playerGames"]
    top = pg[0]["pts"] if pg else None
    H["playerGames"] = [dict(x, statLine=espn_stat_line(x["year"], x["week"], x["playerId"]) if seasons[x["year"]]["platform"] == "ESPN" else None)
                        for x in pg if x["pts"] == top]
    for key, src in (("winStreak", "winStreaks"), ("lossStreak", "lossStreaks")):
        L0 = R[src][0]["length"] if R[src] else 0
        H[key] = [x for x in R[src] if x["length"] == L0]
    most = max(len(p["titles"]) for p in profiles.values())
    H["titles"] = {"count": most, "holders": [{"manager": m, "years": profiles[m]["titles"]} for m in profiles if len(profiles[m]["titles"]) == most and most]}
    b = R["seasonPF"][0]
    H["bestSeason"] = dict(b, mvp=team_mvps.get(b["year"], {}).get(b["manager"]))
    lows = R["lowScores"]
    out = []
    for r in lows:
        a = RECORD_ASTERISKS.get((r["year"], r["week"], r["manager"]))
        out.append(dict(r, asterisk=a))
        if not a: break
    H["lowScores"] = out
    return H


def sleeper_stat_line(year, week, pid):
    """Real stat line from Sleeper weekly stats (raw/sleeper[/YEAR]/statline_W.json, saved by fetch_sleeper.sh), or None."""
    d = os.path.join(RAW, "sleeper") if year == 2026 else os.path.join(RAW, "sleeper", str(year))
    st = (load(os.path.join(d, f"statline_{week}.json"), {}) or {}).get(str(pid))
    if not st: return None
    v = lambda k: int(round(st.get(k, 0) or 0))
    parts = []
    if v("pass_att"):
        parts.append(f"{v('pass_cmp')}/{v('pass_att')}, {v('pass_yd')} pass yds, {v('pass_td')} TD" + (f", {v('pass_int')} INT" if v("pass_int") else ""))
    if v("rush_att") or v("rush_yd"):
        parts.append(f"{v('rush_att')} rush, {v('rush_yd')} yds" + (f", {v('rush_td')} TD" if v("rush_td") else ""))
    if v("rec") or v("rec_yd"):
        parts.append(f"{v('rec')} rec, {v('rec_yd')} yds" + (f", {v('rec_td')} TD" if v("rec_td") else ""))
    if v("fum_lost"): parts.append(f"{v('fum_lost')} fum lost")
    return " · ".join(parts) or None


def dynasty_records(seasons, years):
    """Dynasty-era (Sleeper) score records, kept separate from the ESPN redraft era (superflex + different scoring).
    Ties keep every holder. Only completed weeks with real scores count."""
    sy = [y for y in years if seasons[y]["platform"] == "Sleeper"]
    if not sy: return None
    games, sides, pg = [], [], []
    for y in sy:
        s = seasons[y]; done = s.get("completedWeeks") or 0
        tn = {T["manager"]: T["teamName"] for T in s["teams"]}
        for g in s["games"]:
            if not g.get("away") or g["kind"] not in ("regular", "playoff") or g["week"] > done: continue
            if not (g["home"]["score"] and g["away"]["score"]): continue
            games.append(dict(g, year=y))
            for side, other in (("home", "away"), ("away", "home")):
                sides.append({"year": y, "week": g["week"], "kind": g["kind"], "manager": g[side]["manager"], "team": tn.get(g[side]["manager"]),
                              "score": g[side]["score"], "opp": g[other]["manager"], "oppScore": g[other]["score"], "won": g["winner"] == side})
        for wk, tm in (s.get("lineupsByWeek") or {}).items():
            if int(wk) > done: continue
            for tid, ent in tm.items():
                T = team_of(s, int(tid))
                for pid, slot, pts in ent:
                    if is_starter(slot) and pts:
                        pg.append({"year": y, "week": int(wk), "manager": T["manager"], "playerId": pid, "name": pname(s, pid), "pos": ppos(s, pid), "nfl": nfl_of(s, pid, int(wk)), "pts": pts})
    if not games: return None
    def ties(rows, key, best):
        if not rows: return []
        b = best(r[key] for r in rows); return [r for r in rows if r[key] == b]
    margins = []
    for g in games:
        if g["winner"] in ("home", "away"):
            w, l = (g["home"], g["away"]) if g["winner"] == "home" else (g["away"], g["home"])
            margins.append({"year": g["year"], "week": g["week"], "kind": g["kind"], "winner": w["manager"], "loser": l["manager"],
                            "wScore": w["score"], "lScore": l["score"], "margin": r2(w["score"] - l["score"])})
    top_pg = ties(pg, "pts", max)
    for r in top_pg: r["statLine"] = sleeper_stat_line(r["year"], r["week"], r["playerId"])
    # current streaks within the dynasty era
    per = collections.defaultdict(list)
    for g in sorted(games, key=lambda g: (g["year"], g["week"])):
        for side, other in (("home", "away"), ("away", "home")):
            res = "W" if g["winner"] == side else "T" if g["winner"] == "tie" else "L"
            per[g[side]["manager"]].append({"res": res, "year": g["year"], "week": g["week"], "opp": g[other]["manager"],
                                            "score": g[side]["score"], "oppScore": g[other]["score"]})
    cur = []
    for m, lst in per.items():
        r = lst[-1]["res"]; n = 0
        for x in reversed(lst):
            if x["res"] != r: break
            n += 1
        if r in ("W", "L"):
            cur.append({"manager": m, "type": r, "length": n, "from": [lst[-n]["year"], lst[-n]["week"]], "last": lst[-1]})
    cw = [c for c in cur if c["type"] == "W"]; cl = [c for c in cur if c["type"] == "L"]
    last = max(games, key=lambda g: (g["year"], g["week"]))
    return {"years": sy, "through": {"year": last["year"], "week": last["week"]}, "games": len(games),
            "high": ties(sides, "score", max), "low": ties(sides, "score", min),
            "closest": ties(margins, "margin", min), "blowout": ties(margins, "margin", max), "playerGame": top_pg,
            "winStreak": sorted(ties(cw, "length", max), key=lambda c: c["manager"]), "lossStreak": sorted(ties(cl, "length", max), key=lambda c: c["manager"])}


def season_awards(s):
    """Superlatives for a season. Lineup-based awards use weekly box scores when available.
    Ties: every award carries 'holders' (all managers tied at exactly the same value); 'manager' is the first holder."""
    yr = s["year"]; A = []
    teams = {T["teamId"]: T for T in s["teams"]}
    have, need = lineup_coverage(s)
    full = need > 0 and have >= need
    lbw = s.get("lineupsByWeek") or {}
    reg_weeks = s.get("regularSeasonWeeks")
    reg_games = [g for g in s["games"] if g["kind"] == "regular" and g.get("away")]

    # started points per (team, player) and per manager
    started = collections.defaultdict(float)
    bench = collections.defaultdict(float)
    single = []
    for wk, tm in lbw.items():
        for tid, ent in tm.items():
            for pid, slot, pts in ent:
                pts = pts or 0
                if is_starter(slot):
                    started[(int(tid), pid)] += pts
                    single.append((pts, int(wk), int(tid), pid))
                elif slot in (20, "BE") and (not reg_weeks or int(wk) <= reg_weeks):
                    bench[int(tid)] += pts
    cov_note = None if full else (f"Based on {have} of {need} weeks of box scores in the archive so far." if have else None)

    def team_mvps():
        out = {}
        if started and (full or s["platform"] == "Sleeper"):
            for (tid, pid), v in started.items():
                if tid not in out or v > out[tid]["points"]:
                    out[tid] = {"playerId": pid, "name": pname(s, pid), "pos": ppos(s, pid), "nfl": nfl_of(s, pid), "points": r2(v), "basis": "started"}
        elif s.get("rosters"):
            for tid, lst in s["rosters"].items():
                if lst:
                    best = max(lst, key=lambda x: x["ptsOnRoster"])
                    out[int(tid)] = {"playerId": best["playerId"], "name": best["name"], "pos": best["pos"], "nfl": nfl_of(s, best["playerId"]), "points": best["ptsOnRoster"], "basis": "final-roster"}
        return out

    mvps = team_mvps()
    basis_txt = {"started": "fantasy points scored in his team's starting lineup",
                 "final-roster": "fantasy points scored while on the team's season-ending roster (weekly lineup data not yet available)"}
    if mvps:
        tid, m = max(mvps.items(), key=lambda kv: kv[1]["points"])
        _h = _holders([(v["points"], teams[t]["manager"], plab(s, v["playerId"], v['name'], v['pos'])) for t, v in sorted(mvps.items(), key=lambda kv: kv[0] != tid)], m["points"])
        A.append({"key": "mvp", "holders": _h, "title": "Season MVP", "icon": "🏆", "manager": teams[tid]["manager"],
                  "headline": plab(s, m["playerId"], m['name'], m['pos']), "value": m["points"], "unit": "pts",
                  "detail": f"{fmt(m['points'])} {basis_txt[m['basis']]} for {teams[tid]['teamName']}."})
    team_mvp = {teams[t]["manager"]: m for t, m in mvps.items()}

    # waiver pickup
    best_pick = None; picks_all = []
    txs = s.get("transactions") or []
    if txs and lbw and (full or s["platform"] == "Sleeper"):
        for t in txs:
            if t["type"] not in ("WAIVER", "FREEAGENT"): continue
            for it in t["items"]:
                if it["type"] != "ADD" or it.get("to") not in teams: continue
                pts = 0.0
                for wk, tm in lbw.items():
                    if int(wk) < (t["week"] or 0): continue
                    for pid, slot, p in tm.get(str(it["to"]), []):
                        if str(pid) == str(it["playerId"]) and is_starter(slot): pts += p or 0
                picks_all.append((pts, it, t))
                if not best_pick or pts > best_pick[0]:
                    best_pick = (pts, it, t)
        if best_pick and best_pick[0] > 0:
            pts, it, t = best_pick
            _h = _holders([(p_, i_["to"] in teams and teams[i_["to"]]["manager"], plab(s, i_.get("playerId"), i_['name'], i_.get('pos','?'))) for p_, i_, _ in [best_pick] + picks_all], pts)
            A.append({"key": "waiver", "holders": _h, "title": "Best Waiver Pickup", "icon": "🧲", "manager": teams[it["to"]]["manager"],
                      "headline": plab(s, it.get("playerId"), it['name'], it.get('pos','?')), "value": r2(pts), "unit": "pts",
                      "detail": f"Added in week {t['week']} ({t['type'].replace('FREEAGENT','free agent').lower()}), then put up {fmt(r2(pts))} starting points for {teams[it['to']]['teamName']}" + (f" ({cov_note.lower()[:-1]})" if cov_note else "") + "."})
    elif s.get("rosters"):
        cands = [(e["ptsOnRoster"], int(tid), e) for tid, lst in s["rosters"].items() for e in lst if e.get("acq") == "ADD"]
        if cands:
            pts, tid, e = max(cands, key=lambda x: x[0])
            _h = _holders([(p_, teams[t_]["manager"], plab(s, e_.get("playerId"), e_['name'], e_['pos'])) for p_, t_, e_ in [(pts, tid, e)] + cands], pts)
            A.append({"key": "waiver", "holders": _h, "title": "Best Waiver Pickup", "icon": "🧲", "manager": teams[tid]["manager"],
                      "headline": plab(s, e.get("playerId"), e['name'], e['pos']), "value": pts, "unit": "pts", "provisional": True,
                      "detail": f"Picked up off waivers/free agency (first counted week ≈ {e['firstWeek']}) and still on the roster at season's end: {fmt(pts)} points from then on. Provisional until weekly transaction data is processed."})

    draft = s.get("draft") or []
    if s["platform"] == "ESPN" and draft:
        steal = max([p for p in draft if p.get("valueDelta") is not None and p.get("valueRank", 99) <= 40], key=lambda p: p["valueDelta"], default=None)
        bust = min([p for p in draft if p.get("valueDelta") is not None and p["round"] <= 3], key=lambda p: p["valueDelta"], default=None)
        if steal:
            _h = _holders([(p["valueDelta"], p["manager"], plab(s, p.get("playerId"), p['name'], p['pos'])) for p in [steal] + [p for p in draft if p.get("valueDelta") is not None and p.get("valueRank", 99) <= 40]], steal["valueDelta"])
            A.append({"key": "steal", "holders": _h, "title": "Draft Steal", "icon": "💎", "manager": steal["manager"],
                      "headline": plab(s, steal.get("playerId"), steal['name'], steal['pos']), "value": steal["points"], "unit": "pts",
                      "pick": rp(steal), "detail": f"Pick {rp(steal)} (#{steal['overall']} overall) → finished {steal['pos']}{steal['posRank']} with {fmt(steal['points'])} points{_pg(s, steal)}."})
        if bust:
            _h = _holders([(p["valueDelta"], p["manager"], plab(s, p.get("playerId"), p['name'], p['pos'])) for p in [bust] + [p for p in draft if p.get("valueDelta") is not None and p["round"] <= 3]], bust["valueDelta"])
            A.append({"key": "bust", "holders": _h, "title": "Draft Bust", "icon": "💀", "manager": bust["manager"],
                      "headline": plab(s, bust.get("playerId"), bust['name'], bust['pos']), "value": bust["points"], "unit": "pts",
                      "pick": rp(bust), "detail": f"Pick {rp(bust)} (#{bust['overall']} overall) → only {fmt(bust['points'])} points" + (f" ({bust['pos']}{bust['posRank']}" + _pg(s, bust, inner=True) + ")" if bust.get("posRank") else _pg(s, bust)) + "."})

    if bench and (full or s["platform"] == "Sleeper"):
        tid, b = max(bench.items(), key=lambda kv: kv[1])
        _h = _holders([(v, teams[t]["manager"], teams[t]["teamName"]) for t, v in [(tid, b)] + list(bench.items())], b)
        A.append({"key": "bench", "holders": _h, "title": "Most Points Left on the Bench", "icon": "🪑", "manager": teams[tid]["manager"],
                  "headline": teams[tid]["teamName"], "value": r2(b), "unit": "pts",
                  "detail": f"{fmt(r2(b))} points rotted on the bench" + (f" across {have} weeks" if s['platform'] == 'Sleeper' else f" during the {reg_weeks}-week regular season") + "."})

    if reg_games:
        unl = min(s["teams"], key=lambda T: T.get("luckX", T["luck"]))
        lk = max(s["teams"], key=lambda T: T.get("luckX", T["luck"]))
        A.append({"key": "unlucky", "holders": _holders([(T.get("luckX", T["luck"]), T["manager"], T["teamName"]) for T in [unl] + s["teams"]], unl.get("luckX", unl["luck"])), "title": "Unluckiest Manager", "icon": "🌧️", "manager": unl["manager"],
                  "headline": unl["teamName"], "value": unl["luck"], "unit": "wins vs expected",
                  "detail": f"Went {unl['w']}-{unl['l']}{'-'+str(unl['t']) if unl['t'] else ''} but an all-play record of {unl['allPlayW']}-{unl['allPlayL']} says {fmt(unl['expectedWins'])} wins were deserved. {fmt(unl['pa'])} points against."})
        A.append({"key": "lucky", "holders": _holders([(T.get("luckX", T["luck"]), T["manager"], T["teamName"]) for T in [lk] + s["teams"]], lk.get("luckX", lk["luck"])), "title": "Luckiest Manager", "icon": "🍀", "manager": lk["manager"],
                  "headline": lk["teamName"], "value": lk["luck"], "unit": "wins vs expected",
                  "detail": f"Went {lk['w']}-{lk['l']}{'-'+str(lk['t']) if lk['t'] else ''} on an all-play pace of {fmt(lk['expectedWins'])} wins (+{fmt(lk['luck'])}). Only {fmt(lk['pa'])} points against."})
        pa = max(s["teams"], key=lambda T: T["pa"])
        A.append({"key": "pa", "holders": _holders([(T["pa"], T["manager"], T["teamName"]) for T in [pa] + s["teams"]], pa["pa"]), "title": "Most Points Against", "icon": "🎯", "manager": pa["manager"], "headline": pa["teamName"],
                  "value": pa["pa"], "unit": "pts", "detail": f"Opponents dropped {fmt(pa['pa'])} on them in the regular season."})
        pf = max(s["teams"], key=lambda T: T["pf"])
        A.append({"key": "pf", "holders": _holders([(T["pf"], T["manager"], T["teamName"]) for T in [pf] + s["teams"]], pf["pf"]), "title": "Points Machine", "icon": "🔥", "manager": pf["manager"], "headline": pf["teamName"],
                  "value": pf["pf"], "unit": "pts", "detail": f"Led the league with {fmt(pf['pf'])} regular-season points."})
        # weekly high / low counts
        hi = collections.Counter(); lo = collections.Counter()
        byw = collections.defaultdict(list)
        for g in reg_games:
            byw[g["week"]] += [g["home"], g["away"]]
        for wk, lst in byw.items():
            hi[max(lst, key=lambda x: x["score"])["manager"]] += 1
            lo[min(lst, key=lambda x: x["score"])["manager"]] += 1
        m, c = hi.most_common(1)[0]
        A.append({"key": "tophigh", "holders": _holders([(v, k, nm(k)) for k, v in hi.most_common()], c), "title": "Weekly High-Score King", "icon": "👑", "manager": m, "headline": nm(m), "value": c, "unit": "weeks",
                  "detail": f"Top score of the week {c} times in the regular season."})
        m, c = lo.most_common(1)[0]
        A.append({"key": "toplow", "holders": _holders([(v, k, nm(k)) for k, v in lo.most_common()], c), "title": "Basement Dweller", "icon": "🧱", "manager": m, "headline": nm(m), "value": c, "unit": "weeks",
                  "detail": f"Lowest score of the week {c} times in the regular season."})
        heart = collections.Counter()
        for g in reg_games:
            if g["winner"] in ("home", "away"):
                los = g["away"] if g["winner"] == "home" else g["home"]
                if abs(g["home"]["score"] - g["away"]["score"]) < 5: heart[los["manager"]] += 1
        if heart:
            m, c = heart.most_common(1)[0]
            A.append({"key": "heartbreak", "holders": _holders([(v, k, nm(k)) for k, v in heart.most_common()], c), "title": "Heartbreak Kid", "icon": "💔", "manager": m, "headline": nm(m), "value": c, "unit": "losses",
                      "detail": f"Lost {c} regular-season game{'s' if c > 1 else ''} by fewer than 5 points."})

    if single and (full or s["platform"] == "Sleeper"):
        pts, wk, tid, pid = max(single)
        _h = _holders([(p_, teams[t_]["manager"], plab(s, i_, pname(s, i_), ppos(s, i_), w_)) for p_, w_, t_, i_ in [(pts, wk, tid, pid)] + single], pts)
        A.append({"key": "game", "holders": _h, "title": "Highest Single-Game Player Performance", "icon": "💥", "manager": teams[tid]["manager"],
                  "headline": plab(s, pid, pname(s, pid), ppos(s, pid), wk), "value": r2(pts), "unit": "pts",
                  "detail": f"{fmt(r2(pts))} points in week {wk} in {teams[tid]['teamName']}'s starting lineup."})
    elif single:
        pass

    tc = [(T["transactions"].get("acquisitions", 0), T) for T in s["teams"]]
    if any(c for c, _ in tc):
        c, T = max(tc, key=lambda x: x[0])
        A.append({"key": "moves", "holders": _holders([(v, X["manager"], X["teamName"]) for v, X in [(c, T)] + tc], c), "title": "Most Transactions", "icon": "📝", "manager": T["manager"], "headline": T["teamName"], "value": c, "unit": "adds",
                  "detail": f"{c} acquisitions, {T['transactions'].get('drops', 0)} drops. The waiver wire knows this manager by name."})
    tr = [(T["transactions"].get("trades", 0), T) for T in s["teams"]]
    if any(c for c, _ in tr):
        c, T = max(tr, key=lambda x: x[0])
        ties = [x[1] for x in tr if x[0] == c]
        A.append({"key": "trader", "holders": _holders([(v, X["manager"], X["teamName"]) for v, X in [(c, T)] + tr], c), "title": "Most Active Trader", "icon": "🤝", "manager": T["manager"],
                  "headline": " & ".join(x["teamName"] for x in ties) if len(ties) <= 3 else T["teamName"], "value": c, "unit": "trades",
                  "detail": f"{c} trade{'s' if c != 1 else ''} completed" + (" (tied: " + ", ".join(nm(x['manager']) for x in ties) + ")" if len(ties) > 1 else "") + "."})
    for a in A:
        a["season"] = yr
        a.setdefault("holders", [{"manager": a["manager"], "headline": a["headline"]}])
        a["holderIds"] = list(dict.fromkeys(h["manager"] for h in a["holders"]))
        a["holdersArePeople"] = all(h["headline"] == nm(h["manager"]) for h in a["holders"])
        if len(a["holderIds"]) > 1 and a["key"] != "trader":
            others = [nm(m) for m in a["holderIds"] if m != a["manager"]]
            a["detail"] = a.get("detail", "") + f" Tied at exactly the same mark with {' & '.join(others)}."
        if cov_note and a["key"] in ("waiver",) and not a.get("provisional"):
            a["note"] = cov_note
    return A, team_mvp, {"lineupWeeks": have, "neededWeeks": need, "full": full}


def build():
    seasons = load_seasons()
    years = sorted(seasons)
    espn_years = [y for y in years if seasons[y]["platform"] == "ESPN"]

    # ---------- per manager season rows
    rows = collections.defaultdict(list)
    for y in years:
        s = seasons[y]
        for T in s["teams"]:
            done = s["platform"] == "ESPN"
            row = {"year": y, "platform": s["platform"], "teamName": T["teamName"], "teamId": T["teamId"],
                   "w": T["w"], "l": T["l"], "t": T["t"], "pf": T["pf"], "pa": T["pa"],
                   "seed": T.get("seed"), "finalRank": T.get("finalRank"), "standing": T.get("standing"),
                   "complete": done, "luck": T.get("luck"), "luckX": T.get("luckX", T.get("luck")), "expectedWins": T.get("expectedWins"),
                   "madePlayoffs": bool(done and T.get("seed") and T["seed"] <= s["playoffTeams"]),
                   "champion": s.get("champion") == T["manager"], "runnerUp": s.get("runnerUp") == T["manager"],
                   "tookOverFrom": T.get("tookOverFrom"), "transactions": T.get("transactions", {}),
                   "officialRecord": f"{T['officialW']}-{T['officialL']}" if "officialW" in T else None,
                   "medianRecord": f"{T['medW']}-{T['medL']}" if "medW" in T else None}
            gp = row["w"] + row["l"] + row["t"]
            row["pct"] = round((row["w"] + 0.5 * row["t"]) / gp, 3) if gp else 0
            row["pctX"] = ((row["w"] + 0.5 * row["t"]) / gp) if gp else 0
            rows[T["manager"]].append(row)

    # ---------- games list (person-attributed)
    allgames = []
    for y in years:
        for g in seasons[y]["games"]:
            if not g.get("away"): continue
            allgames.append({**g, "year": y, "platform": seasons[y]["platform"],
                             "homeTeam": team_of(seasons[y], g["home"]["teamId"])["teamName"],
                             "awayTeam": team_of(seasons[y], g["away"]["teamId"])["teamName"]})
    real = [g for g in allgames if g["kind"] in ("regular", "playoff")]

    # ---------- H2H
    h2h = collections.defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pw": 0, "pl": 0, "pf": 0.0, "pa": 0.0, "games": 0})
    for g in real:
        a, b = g["home"], g["away"]
        for x, o, side in ((a, b, "home"), (b, a, "away")):
            H = h2h[(x["manager"], o["manager"])]
            H["games"] += 1; H["pf"] += x["score"]; H["pa"] += o["score"]
            won = g["winner"] == side; tie = g["winner"] == "tie"
            if g["kind"] == "regular":
                H["w" if won else "t" if tie else "l"] += 1
            else:
                H["pw" if won else "pl"] += 1
    h2h_out = {f"{a}|{b}": {**v, "pf": r2(v["pf"]), "pa": r2(v["pa"])} for (a, b), v in h2h.items()}

    # ---------- streaks (regular season + winners-bracket playoff games, chronological, by person)
    streaks = []
    per = collections.defaultdict(list)
    for g in sorted(real, key=lambda g: (g["year"], g["week"])):
        for side, x in (("home", g["home"]), ("away", g["away"])):
            res = "W" if g["winner"] == side else "T" if g["winner"] == "tie" else "L"
            o = g["away"] if side == "home" else g["home"]
            per[x["manager"]].append((res, g["year"], g["week"], {"year": g["year"], "week": g["week"], "kind": g["kind"], "result": res,
                                     "score": x["score"], "opp": o["manager"], "oppScore": o["score"]}))
    for m, lst in per.items():
        cur = None; n = 0; start = None
        for i, (r, y, w, info) in enumerate(lst + [("END", 0, 0, None)]):
            if r == cur:
                n += 1
            else:
                if cur in ("W", "L") and n >= 2:
                    streaks.append({"manager": m, "type": cur, "length": n, "from": start, "to": list(lst[i - 1][1:3]),
                                    "endedBy": info if r != "END" else None})
                cur, n, start = r, 1, (y, w)
    win_streaks = sorted([s for s in streaks if s["type"] == "W"], key=lambda s: -s["length"])[:10]
    loss_streaks = sorted([s for s in streaks if s["type"] == "L"], key=lambda s: -s["length"])[:10]

    # ---------- records
    def side_rows(gs):
        out = []
        for g in gs:
            for side, other in (("home", "away"), ("away", "home")):
                out.append({"year": g["year"], "week": g["week"], "kind": g["kind"], "manager": g[side]["manager"], "score": g[side]["score"],
                            "team": g[side + "Team"], "opp": g[other]["manager"], "oppScore": g[other]["score"], "oppTeam": g[other + "Team"],
                            "won": g["winner"] == side, "platform": g["platform"]})
        return out
    # Score-based records use the ESPN era only (Sleeper dynasty scoring/lineups differ); see the Dynasty page for Sleeper marks.
    sr = side_rows([g for g in allgames if (g["home"]["score"] or g["away"]["score"]) and g["platform"] == "ESPN"])
    sr_real = [r for r in sr if r["kind"] in ("regular", "playoff")]
    margins = []
    for g in real:
        if g["winner"] in ("home", "away") and g["platform"] == "ESPN":
            w, l = (g["home"], g["away"]) if g["winner"] == "home" else (g["away"], g["home"])
            margins.append({"year": g["year"], "week": g["week"], "kind": g["kind"], "winner": w["manager"], "loser": l["manager"],
                            "wScore": w["score"], "lScore": l["score"], "margin": r2(w["score"] - l["score"]), "platform": g["platform"],
                            "wTeam": g["homeTeam"] if g["winner"] == "home" else g["awayTeam"], "lTeam": g["awayTeam"] if g["winner"] == "home" else g["homeTeam"]})
    season_rows = [dict(r, manager=m, games=r["w"] + r["l"] + r["t"]) for m, rs in rows.items() for r in rs if r["complete"]]
    for r in season_rows:
        r["ppg"] = r2(r["pf"] / r["games"]) if r["games"] else 0
        r["pct"] = round((r["w"] + 0.5 * r["t"]) / r["games"], 3) if r["games"] else 0
        r["pctX"] = ((r["w"] + 0.5 * r["t"]) / r["games"]) if r["games"] else 0
        r["ppgX"] = (r["pf"] / r["games"]) if r["games"] else 0
        r["papgX"] = (r["pa"] / r["games"]) if r["games"] else 0
    records = {
        "highScores": sorted(sr_real, key=lambda r: -r["score"])[:10],
        "lowScores": sorted([r for r in sr_real if r["platform"] == "ESPN" or r["score"] > 0], key=lambda r: r["score"])[:10],
        "blowouts": sorted(margins, key=lambda m: -m["margin"])[:10],
        "closest": sorted(margins, key=lambda m: m["margin"])[:10],
        "highLoss": sorted([r for r in sr_real if not r["won"]], key=lambda r: -r["score"])[:10],
        "lowWin": sorted([r for r in sr_real if r["won"]], key=lambda r: r["score"])[:10],
        "seasonPF": sorted(season_rows, key=lambda r: -r["ppgX"])[:10],
        "seasonPFlow": sorted(season_rows, key=lambda r: r["ppgX"])[:10],
        "seasonPA": sorted(season_rows, key=lambda r: -r["pa"] / max(r["games"], 1))[:10],
        "bestRecords": sorted(season_rows, key=lambda r: (-r["pctX"], -r["pf"]))[:10],
        "worstRecords": sorted(season_rows, key=lambda r: (r["pctX"], r["pf"]))[:10],
        "luckiest": sorted(season_rows, key=lambda r: -(r["luckX"] or 0))[:8],
        "unluckiest": sorted(season_rows, key=lambda r: (r["luckX"] or 0))[:8],
        "winStreaks": win_streaks, "lossStreaks": loss_streaks,
        "consolationNote": "Score and margin records cover the ESPN era (2020-2025), regular season plus winners-bracket playoff games; consolation games are excluded. Sleeper dynasty scoring is different (superflex, bonuses), so 2026+ marks live on the Dynasty page. Win/loss streaks span both platforms.",
    }
    # player single-game records from lineup data
    pgames = []
    for y in years:
        s = seasons[y]
        for wk, tm in (s.get("lineupsByWeek") or {}).items():
            for tid, ent in tm.items():
                T = team_of(s, int(tid))
                for pid, slot, pts in ent:
                    if is_starter(slot) and pts:
                        pgames.append({"year": y, "week": int(wk), "manager": T["manager"], "team": T["teamName"], "playerId": pid,
                                       "name": pname(s, pid), "pos": ppos(s, pid), "nfl": nfl_of(s, pid, int(wk)), "pts": pts})
    records["playerGames"] = sorted(pgames, key=lambda x: -x["pts"])[:15]

    # ---------- awards per season
    awards, team_mvps, coverage = {}, {}, {}
    for y in years:
        awards[y], team_mvps[y], coverage[y] = season_awards(seasons[y])

    # ---------- manager profiles
    profiles = {}
    for mid, rs in rows.items():
        rs.sort(key=lambda r: r["year"])
        comp = [r for r in rs if r["complete"]]
        W = sum(r["w"] for r in rs); L = sum(r["l"] for r in rs); Tt = sum(r["t"] for r in rs)
        pw = sum(v["pw"] for (a, b), v in h2h.items() if a == mid); pl = sum(v["pl"] for (a, b), v in h2h.items() if a == mid)
        prof = {"id": mid, "name": nm(mid), "nickname": MGR.get(mid, {}).get("nickname"), "role": MGR.get(mid, {}).get("role"),
                "note": MGR.get(mid, {}).get("note"), "confirmed": MGR.get(mid, {}).get("confirmed", True),
                "seasons": rs, "years": [r["year"] for r in rs],
                "active": years[-1] in [r["year"] for r in rs],
                "w": W, "l": L, "t": Tt, "pf": r2(sum(r["pf"] for r in rs)), "pa": r2(sum(r["pa"] for r in rs)),
                "games": W + L + Tt, "playoffW": pw, "playoffL": pl,
                "titles": [r["year"] for r in rs if r["champion"]], "runnerUps": [r["year"] for r in rs if r["runnerUp"]],
                "playoffApps": [r["year"] for r in comp if r["madePlayoffs"]],
                "lastPlace": [r["year"] for r in comp if r["finalRank"] == 10],
                "avgFinish": r2(statistics.mean([r["finalRank"] for r in comp])) if comp else None,
                "teamNames": [{"year": r["year"], "platform": r["platform"], "name": r["teamName"]} for r in rs],
                "inherited": [{"year": r["year"], "from": r["tookOverFrom"], "fromName": nm(r["tookOverFrom"])} for r in rs if r.get("tookOverFrom")],
                "teamMVPs": [{"year": y, **team_mvps[y][mid]} for y in years if mid in team_mvps[y]],
                "awards": [a for y in years for a in awards[y] if mid in a.get("holderIds", [a["manager"]])]}
        prof["pct"] = round((W + 0.5 * Tt) / prof["games"], 3) if prof["games"] else 0
        prof["pctX"] = ((W + 0.5 * Tt) / prof["games"]) if prof["games"] else 0
        prof["ppg"] = r2(prof["pf"] / prof["games"]) if prof["games"] else 0
        # successors: who took over this person's slot after they left
        prof["succeededBy"] = []
        prof["seatFrom"] = next(({"year": s["year"], "from": s["from"], "fromName": nm(s["from"]), "seat": s.get("seat")}
                                 for s in SEATS if s["manager"] == mid), None)
        for y in espn_years:
            for T in seasons[y]["teams"]:
                if T.get("tookOverFrom") == mid:
                    prof["succeededBy"].append({"year": y, "manager": T["manager"], "name": nm(T["manager"])})
        for s in SEATS:
            if s["from"] == mid:
                prof["succeededBy"].append({"year": s["year"], "manager": s["manager"], "name": nm(s["manager"]), "seat": s.get("seat"), "kind": "seat"})
        h = []
        for (a, b), v in h2h.items():
            if a == mid:
                h.append({"opp": b, "oppName": nm(b), **{k: (r2(x) if isinstance(x, float) else x) for k, x in v.items()}})
        prof["h2h"] = sorted(h, key=lambda x: (-x["games"], x["oppName"]))
        # favorite players: seasons in which player was drafted by / on final roster / in lineups for this manager
        fav = collections.defaultdict(lambda: {"seasons": set(), "drafted": 0, "name": None, "pos": None, "started": 0.0})
        for y in years:
            s = seasons[y]
            tids = [T["teamId"] for T in s["teams"] if T["manager"] == mid]
            if not tids: continue
            tid = tids[0]
            for p in s.get("draft") or []:
                if p["manager"] == mid:
                    k = norm_name(p["name"]); fav[k]["seasons"].add(y); fav[k]["drafted"] += 1; fav[k]["name"] = p["name"]; fav[k]["pos"] = p["pos"]
            for e in (s.get("rosters") or {}).get(str(tid), []):
                k = norm_name(e["name"]); fav[k]["seasons"].add(y); fav[k]["name"] = e["name"]; fav[k]["pos"] = e["pos"]
            for wk, tm in (s.get("lineupsByWeek") or {}).items():
                for pid, slot, pts in tm.get(str(tid), []):
                    k = norm_name(pname(s, pid)); fav[k]["seasons"].add(y); fav[k]["name"] = fav[k]["name"] or pname(s, pid); fav[k]["pos"] = fav[k]["pos"] or ppos(s, pid)
                    if is_starter(slot): fav[k]["started"] += pts or 0
        favl = [{"name": v["name"], "pos": v["pos"], "seasons": sorted(v["seasons"]), "count": len(v["seasons"]), "drafted": v["drafted"], "started": r2(v["started"])}
                for v in fav.values() if len(v["seasons"]) >= 2 and v["pos"] not in ("D/ST", "DEF", "K")]
        prof["favorites"] = sorted(favl, key=lambda x: (-x["count"], -x["drafted"], -x["started"]))[:10]
        picks = [dict(p, year=y) for y in espn_years for p in seasons[y]["draft"] if p["manager"] == mid and p.get("valueDelta") is not None]
        prof["bestPicks"] = sorted([p for p in picks if p.get("valueRank", 99) <= 50], key=lambda p: -p["valueDelta"])[:5]
        prof["worstPicks"] = sorted([p for p in picks if p["round"] <= 5], key=lambda p: p["valueDelta"])[:5]
        prof["firstRounders"] = [dict(p, year=y) for y in years for p in (seasons[y].get("draft") or []) if p["manager"] == mid and p["round"] == 1]
        prof["transactionsTotal"] = {k: sum((r.get("transactions") or {}).get(k, 0) for r in rs) for k in ("acquisitions", "drops", "trades")}
        profiles[mid] = prof

    # Loyalist: original member who has played every season from the first year through the latest one, no gaps
    for mid, p in profiles.items():
        p["loyalist"] = p["years"] == years
    for y in years:
        if seasons[y].get("champion"): _CHAMPS[y] = seasons[y]["champion"]
    lineage = belt_lineage(seasons, years)
    for e in lineage:
        if e["manager"] in profiles:
            profiles[e["manager"]].setdefault("belt", []).append(e)
    latest = years[-1]
    for mid, p in profiles.items():
        yrs = p["years"]
        p["fallen"] = latest not in yrs
        p["resurrected"] = (latest in yrs) and any(b - a > 1 for a, b in zip(yrs, yrs[1:]))
        if p["resurrected"]:
            gap = next((a, b) for a, b in zip(yrs, yrs[1:]) if b - a > 1)
            p["resurrection"] = {"leftAfter": gap[0], "returned": gap[1]}
    for mid, p in profiles.items():
        p["story"] = manager_story(p, profiles, seasons)
        p["book"] = manager_book(p, profiles, seasons, awards, team_mvps)
        p["lore"] = [x["id"] for x in LORE.get("entries", []) if mid in (x.get("managers") or [])]
    # ---------- season stories, notable games
    season_meta = {}
    for y in years:
        s = seasons[y]
        gs = [g for g in allgames if g["year"] == y]
        nb = notable(gs)
        st = season_story(s, nb, awards[y], team_mvps[y], gs)
        season_meta[y] = {"notable": nb, "story": st, "chapters": season_chapters(st), "awards": awards[y],
                          "teamMVPs": team_mvps[y], "coverage": coverage[y]}

    champions = [{"year": y, "manager": seasons[y]["champion"], "name": nm(seasons[y]["champion"]),
                  "team": next(T["teamName"] for T in seasons[y]["teams"] if T["manager"] == seasons[y]["champion"]),
                  "runnerUp": seasons[y]["runnerUp"], "platform": seasons[y]["platform"]} for y in years if seasons[y].get("champion")]
    # Lore is curated by the commissioner: entries come only from data/lore.json (record nights live in the Record Book).
    lore = [dict(e, source=e.get("source", "league")) for e in LORE.get("entries", [])]
    for e in lore:
        for bx in e.get("boxscores", []) or []:
            s_ = seasons.get(bx["season"])
            if not s_: continue
            T = next((t for t in s_["teams"] if t["manager"] == bx["manager"]), None)
            if T:
                bx["team"] = T["teamName"]; bx["lineup"] = lineup_of(s_, bx["week"], T["teamId"])
    allt = alltime(profiles)
    headline = records_that_matter(records, seasons, profiles, team_mvps, years)
    out = {"headline": headline, "dynastyRecords": dynasty_records(seasons, years), "belt": BELT, "beltLineage": lineage, "years": years, "espnYears": espn_years, "champions": champions, "profiles": profiles,
           "h2h": h2h_out, "records": records, "seasonMeta": season_meta, "lore": lore, "allTime": allt,
           "loyalists": [m for m in profiles if profiles[m]["loyalist"]],
           "fallen": memorial(profiles, records, seasons, years), "championships": championships(seasons, years), "resurrected": [m for m in profiles if profiles[m].get("resurrected")], "leagueStory": league_story(seasons, champions, profiles, records, years),
           "podium": podium(seasons, years), "pressArchive": (LORE.get("press_conferences") or {}).get("archive", []),
           "draftOrder": draft_order(seasons, years), "era": era_awards(seasons, years, awards),
           "managerOrder": sorted(profiles, key=lambda m: (-len(profiles[m]["titles"]), -profiles[m]["pctX"]))}
    save(os.path.join(GEN, "league.json"), out)
    print("league.json written:", len(profiles), "managers,", len(lore), "lore entries")


ERA_AWARDS = [  # Commissioner-approved picks; every number on the card is computed from season data.
    {"key": "redraftMVP", "title": "Redraft Era MVP", "icon": "🏆", "label": "ESPN",
     "winner": "brian-mulvihill", "runnerUp": "ryan-nussdorfer", "honorable": "bradley-kochheiser"},
]
_MERIT = {"pf", "tophigh", "waiver", "steal", "mvp", "game"}


def era_awards(seasons, years, awards):
    """Per-person career stats over the ESPN redraft era, plus the era award cards built from them."""
    ys = [y for y in years if seasons[y]["platform"] == "ESPN"]
    st = collections.defaultdict(lambda: {"seasons": 0, "titles": [], "finals": 0, "playoffs": 0, "pw": 0, "pl": 0, "w": 0, "l": 0, "t": 0,
                                          "apw": 0, "apl": 0, "pf": 0.0, "pfRanks": [], "pfCrowns": 0, "luck": 0.0, "merit": 0, "awards": 0})
    for y in ys:
        s = seasons[y]
        for i, t in enumerate(sorted(s["teams"], key=lambda t: -t["pf"])):
            d = st[t["manager"]]; d["seasons"] += 1
            if t["finalRank"] == 1: d["titles"].append(y)
            d["finals"] += t["finalRank"] <= 2
            for k in ("w", "l", "t"): d[k] += t[k]
            d["apw"] += t["allPlayW"]; d["apl"] += t["allPlayL"]; d["pf"] += t["pf"]; d["luck"] += t.get("luckX", t.get("luck", 0))
            d["pfRanks"].append(i + 1)
        app = set()
        for g in s["games"]:
            if g["kind"] != "playoff" or g.get("tier") != "WINNERS_BRACKET": continue
            app.add(g["home"]["manager"])
            if g.get("away") and not g.get("bye"):
                app.add(g["away"]["manager"]); h, a = g["home"], g["away"]
                if h["score"] != a["score"]:
                    w_, l_ = (h, a) if h["score"] > a["score"] else (a, h); st[w_["manager"]]["pw"] += 1; st[l_["manager"]]["pl"] += 1
        for m in app: st[m]["playoffs"] += 1
        for a in awards[y]:
            for m in a.get("holderIds", [a["manager"]]):
                st[m]["awards"] += 1; st[m]["merit"] += a["key"] in _MERIT; st[m]["pfCrowns"] += a["key"] == "pf"
                st[m].setdefault("awardYears", {}).setdefault(a["key"], []).append({"year": y, "shared": len(a.get("holderIds", [a["manager"]]))})
    for d in st.values():
        g = d["w"] + d["l"] + d["t"]
        d.update(games=g, pct=round((d["w"] + .5 * d["t"]) / g, 3), apPct=round(d["apw"] / (d["apw"] + d["apl"]), 3),
                 pf=r2(d["pf"]), ppg=r2(d["pf"] / g), avgPfRank=r2(sum(d["pfRanks"]) / len(d["pfRanks"])), luck=r2(d["luck"]))
    pct = lambda v: f"{v:.3f}".lstrip("0")
    span = f"{ys[0]}-{ys[-1]}"
    cards = []
    for E in ERA_AWARDS:
        W, R, H = st[E["winner"]], st[E["runnerUp"]], st[E["honorable"]]
        num = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
        topm = max(d["merit"] for d in st.values())
        wtxt = (f"{num.get(len(W['titles']), len(W['titles'])).capitalize()} title{'s' if len(W['titles']) != 1 else ''} ({', '.join(map(str, W['titles']))}), "
                f"{num.get(W['finals'], W['finals'])} finals, {num.get(W['pfCrowns'], W['pfCrowns'])} points crown{'s' if W['pfCrowns'] != 1 else ''} and "
                f"{'a league-high ' if W['merit'] == topm else ''}{num.get(W['merit'], W['merit'])} merit awards")
        if W["luck"] < 0:
            champ_min = min(d["luck"] for d in st.values() if d["titles"])
            wtxt += f", all through {'the worst schedule luck of any champion' if W['luck'] == champ_min else 'negative schedule luck'} ({W['luck']:+.2f} wins)"
        wtxt += "."
        rtxt = f"{R['w']}-{R['l']}{'-' + str(R['t']) if R['t'] else ''}, a {R['avgPfRank']:.2f} average points-for finish, {R['pw']}-{R['pl']} in the playoffs"
        htxt = f"{pct(H['pct'])}, " + (f"playoffs in all {num.get(H['seasons'], H['seasons'])} of his seasons" if H["playoffs"] == H["seasons"] else f"{H['playoffs']} playoff trips in {H['seasons']} seasons")
        AY = W.get("awardYears", {})
        yrs = lambda k, solo=None: [x["year"] for x in AY.get(k, []) if solo is None or (x["shared"] == 1) == solo]
        def ylist(v): return " and ".join(map(str, v)) if len(v) < 3 else ", ".join(map(str, v[:-1])) + " and " + str(v[-1])
        roll = [f"{num.get(len(W['titles']), len(W['titles'])).capitalize()} championships: {ylist(W['titles'])}",
                f"{num.get(W['finals'], W['finals']).capitalize()} trips to the final",
                f"A {W['pw']}-{W['pl']} playoff record"]
        if yrs("pf"): roll.append(f"Points leader in {ylist(yrs('pf'))}")
        if yrs("mvp"): roll.append(f"Season MVP in {ylist(yrs('mvp'))}")
        if yrs("tophigh", True) or yrs("tophigh", False):
            t_ = f"The {ylist(yrs('tophigh', True))} weekly high-score title" if yrs("tophigh", True) else "A share of the weekly high-score title"
            if yrs("tophigh", True) and yrs("tophigh", False): t_ += f" (plus a share in {ylist(yrs('tophigh', False))})"
            roll.append(t_)
        roll.append(f"{'A league-high ' if W['merit'] == topm else ''}{num.get(W['merit'], W['merit'])} merit awards")
        champ_min = min(d["luck"] for d in st.values() if d["titles"])
        if W["luck"] < 0:
            roll.append(f"And he did it all with {'the worst schedule luck of any champion' if W['luck'] == champ_min else 'negative schedule luck'}: {W['luck']:+.2f} wins".replace("-", "−"))
        cards.append({**E, "roll": roll, "unluckiestChamp": W["luck"] < 0 and W["luck"] == champ_min, "luck": W["luck"], "span": span, "years": ys, "winnerText": wtxt, "runnerUpText": rtxt, "honorableText": htxt,
                      "trophy": {"key": E["key"], "icon": E["icon"], "title": E["title"], "season": f"{E['label']} {span}", "manager": E["winner"],
                                 "headline": f"{len(W['titles'])} titles, {W['finals']} finals", "detail": wtxt}})
    return {"years": ys, "span": span, "stats": dict(st), "awards": cards}


_CHAMPS = {}


def podium(seasons, years):
    """Who takes the press-conference podium each completed week: the manager with the biggest LOSING MARGIN
    (verified against the confirmed 2026 pressers: Bradley wk1 -79.4, Taylor wk2 -65.15, Cardillo wk3 -80.95).
    Commissioner-confirmed entries in lore.json press_conferences.archive always win over this computed pick."""
    start = (LORE.get("press_conferences") or {}).get("introduced_season", 2026)
    out = []
    for y in years:
        s = seasons[y]
        if y < start: continue
        done = s.get("completedWeeks") or s.get("lastWeek") or 0
        for wk in sorted(set(g["week"] for g in s["games"])):
            if wk > done: continue
            losses = []
            for g in s["games"]:
                if g["week"] != wk or not g.get("away") or g["home"]["score"] == g["away"]["score"]: continue
                w, l = (g["home"], g["away"]) if g["home"]["score"] > g["away"]["score"] else (g["away"], g["home"])
                losses.append((round(w["score"] - l["score"], 2), l, w))
            if not losses: continue
            m, l, w = max(losses, key=lambda x: x[0])
            out.append({"year": y, "week": wk, "manager": l["manager"], "score": l["score"], "team": team_of(s, l["teamId"])["teamName"],
                        "opp": w["manager"], "oppScore": w["score"], "margin": m, "lost": True})
    return out

def draft_order(seasons, years):
    """Real first-round draft order per year from ESPN/Sleeper, merged with data/draft_order_games.json (hand-edited)."""
    cfg = load(os.path.join(DATA, "draft_order_games.json"), {"years": {}}).get("years", {})
    out = []
    for y in years:
        s = seasons[y]
        r1 = sorted([p for p in (s.get("draft") or []) if p["round"] == 1], key=lambda p: p["pick"])
        order = [{"pick": p["pick"], "manager": p["manager"], "team": (team_of(s, p["teamId"]) or {}).get("teamName", ""),
                  "player": p["name"], "pos": p["pos"], "nfl": nfl_of(s, p.get("playerId"))} for p in r1]
        c = cfg.get(str(y), {})
        kind = next((d.get("kind") for d in (s.get("drafts") or []) if d.get("picks")), None) or ("redraft" if s["platform"] == "ESPN" else "startup")
        out.append({"year": y, "platform": s["platform"], "draftKind": kind, "order": order,
                    "competition": c.get("competition") or "", "description": c.get("description") or "", "winner": c.get("winner"),
                    "notes": c.get("notes") or "", "video": c.get("video")})
    return out


def belt_holder_before(y):
    prev = [yy for yy in _CHAMPS if BELT_YEAR <= yy < y]
    return _CHAMPS[max(prev)] if prev else None


def belt_lineage(seasons, years):
    out, reigns = [], collections.Counter()
    for y in years:
        c = seasons[y].get("champion")
        if not c: continue
        T = next(t for t in seasons[y]["teams"] if t["manager"] == c)
        e = {"year": y, "manager": c, "team": T["teamName"], "runnerUp": seasons[y].get("runnerUp"), "seed": T.get("seed")}
        if y < BELT_YEAR:
            e["beltless"] = True
        else:
            prev = belt_holder_before(y)
            if prev == c:
                e["defense"] = True; e["reign"] = reigns[c]
            else:
                reigns[c] += 1; e["reign"] = reigns[c]; e["wonFrom"] = prev
            e["reignNumber"] = len([x for x in out if not x.get("beltless") and not x.get("defense")]) + (0 if e.get("defense") else 1)
        out.append(e)
    return out


SLOT_ORDER = {0: 0, 2: 1, 4: 2, 6: 3, 23: 4, 7: 5, 16: 6, 17: 7}
SLOT_LABEL = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 7: "OP", 16: "D/ST", 17: "K", 20: "BE", 21: "IR"}


def lineup_of(s, week, tid):
    ent = (s.get("lineupsByWeek") or {}).get(str(week), {}).get(str(tid))
    if not ent: return None
    st, be = [], []
    for pid, slot, pts in ent:
        row = {"name": pname(s, pid), "pos": ppos(s, pid), "pts": pts or 0}
        if is_starter(slot):
            row["slot"] = SLOT_LABEL.get(slot, row["pos"]) if isinstance(slot, int) else row["pos"]
            row["_o"] = SLOT_ORDER.get(slot, 9) if isinstance(slot, int) else {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 7, "DEF": 6}.get(row["pos"], 4)
            st.append(row)
        else:
            row["slot"] = SLOT_LABEL.get(slot, "BE") if isinstance(slot, int) else ("TAXI" if slot == "TX" else "BE")
            be.append(row)
    st.sort(key=lambda r: (r.pop("_o"), -r["pts"]))
    be.sort(key=lambda r: -r["pts"])
    return {"starters": st, "bench": be, "startTotal": r2(sum(r["pts"] for r in st)), "benchTotal": r2(sum(r["pts"] for r in be if r["slot"] == "BE"))}


def championships(seasons, years):
    out = []
    for y in years:
        s = seasons[y]
        fg = [g for g in s["games"] if g.get("isFinal")]
        if not s.get("champion") or not fg: continue
        g = fg[0]; w, l = ("home", "away") if g["winner"] == "home" else ("away", "home")
        side = lambda k: {"manager": g[k]["manager"], "score": g[k]["score"], "team": team_of(s, g[k]["teamId"])["teamName"],
                          "seed": team_of(s, g[k]["teamId"]).get("seed"), "lineup": lineup_of(s, g["week"], g[k]["teamId"])}
        W, Lo = side(w), side(l)
        mvp = max(W["lineup"]["starters"], key=lambda r: r["pts"]) if W["lineup"] else None
        prev = belt_holder_before(y) if y >= BELT_YEAR else None
        out.append({"year": y, "week": g["week"], "winner": W, "loser": Lo, "margin": r2(W["score"] - Lo["score"]), "mvp": mvp,
                    "beltless": y < BELT_YEAR, "defense": prev == W["manager"], "wonFrom": prev if prev and prev != W["manager"] else None,
                    "reignNumber": next((e.get("reignNumber") for e in belt_lineage(seasons, years) if e["year"] == y), None)})
    return out


def notable(gs):
    reg = [g for g in gs if g["kind"] in ("regular", "playoff") and (g["home"]["score"] or g["away"]["score"])]
    if not reg: return {}
    def side(g, s): return {"manager": g[s]["manager"], "score": g[s]["score"], "team": g[s + "Team"]}
    rows = []
    for g in reg:
        if g["winner"] not in ("home", "away"): continue
        w, l = ("home", "away") if g["winner"] == "home" else ("away", "home")
        rows.append({"week": g["week"], "kind": g["kind"], "w": side(g, w), "l": side(g, l), "margin": r2(g[w]["score"] - g[l]["score"])})
    if not rows: return {}
    hs = max(rows, key=lambda r: r["w"]["score"])
    return {"highest": hs, "blowout": max(rows, key=lambda r: r["margin"]), "closest": min(rows, key=lambda r: r["margin"]),
            "worstLoss": max(rows, key=lambda r: r["l"]["score"]), "lowest": min(rows, key=lambda r: r["l"]["score"]),
            "luckiestWin": min(rows, key=lambda r: r["w"]["score"])}


def season_story(s, nb, awards, mvps, gs):
    """Data-grounded season recap paragraphs."""
    P = []
    y = s["year"]; teams = s["teams"]
    if s["platform"] == "Sleeper":
        lead = teams[0]
        P.append(f"Year one of the dynasty era. Through {s['completedWeeks']} completed weeks, {lead['teamName']} ({nm(lead['manager'])}) sits on top at {lead['officialW']}-{lead['officialL']} "
                 f"(head-to-head plus the weekly vs-the-median game), with {fmt(lead['pf'])} points scored.")
        hot = max(teams, key=lambda T: T["pf"]); cold = min(teams, key=lambda T: T["pf"])
        P.append(f"The scoring leader so far is {hot['teamName']} at {fmt(hot['pf'])}; {cold['teamName']} ({nm(cold['manager'])}) has the fewest points ({fmt(cold['pf'])}) and the {cold['officialW']}-{cold['officialL']} record to match. Long season, plenty of time.")
        if nb.get("highest"):
            h = nb["highest"]; P.append(f"Biggest week so far: {h['w']['team']} hung {fmt(h['w']['score'])} on {h['l']['team']} in week {h['week']}.")
        tr = [t for t in s["transactions"] if t["type"] == "TRADE"]
        if tr:
            P.append(f"The trade market opened fast: {len(tr)} trade{'s' if len(tr) != 1 else ''} completed so far, and {len(s.get('tradedPicks', []))} future pick{'s have' if len(s.get('tradedPicks', [])) != 1 else ' has'} already changed hands.")
        return P
    champ = next(T for T in teams if T["manager"] == s["champion"])
    ru = next((T for T in teams if T["manager"] == s["runnerUp"]), None)
    top_seed = min(teams, key=lambda T: T["seed"] or 99)
    pf = max(teams, key=lambda T: T["pf"])
    recs = f"{champ['w']}-{champ['l']}{'-'+str(champ['t']) if champ['t'] else ''}"
    if y >= BELT_YEAR:
        prev = belt_holder_before(y)
        how = ("successfully defended the Belt" if prev == s["champion"] else
               (f"took the Belt straight off the waist of the reigning champ, {nm(prev)}," if prev and ru and prev == ru["manager"] else "captured the Belt"))
        P.append(f"{nm(s['champion'])} {how} in {y} with {champ['teamName']}, going {recs} in the regular season as the #{champ['seed']} seed"
                 + (f" and pinning {nm(ru['manager'])} ({ru['teamName']}) in the title match." if ru else ".")
                 + (f" {nm(prev)} entered the playoffs as the reigning Belt holder." if prev and prev not in (s["champion"], ru and ru["manager"]) else ""))
    else:
        P.append(f"{nm(s['champion'])} won the {y} title with {champ['teamName']}, going {recs} in the regular season as the #{champ['seed']} seed"
                 + (f" and beating {nm(ru['manager'])} ({ru['teamName']}) in the final." if ru else ".")
                 + f" The Belt didn't exist until {BELT_YEAR}, so there was no Belt to hand him. The title is his outright.")
    for e in LORE.get("entries", []):
        if e.get("featured") and e.get("season") == y and e.get("category") == "game":
            P.append(f"📌 {e['title']}: see the callout below and the Lore page.")
    # title run
    run = [g for g in gs if g["kind"] == "playoff" and s["champion"] in (g["home"]["manager"], g["away"]["manager"])]
    bits = []
    for g in sorted(run, key=lambda g: g["week"]):
        me, op = ("home", "away") if g["home"]["manager"] == s["champion"] else ("away", "home")
        bits.append(f"week {g['week']}: {fmt(g[me]['score'])}-{fmt(g[op]['score'])} over {nm(g[op]['manager'])}")
    if bits:
        P.append("The title run: " + "; ".join(bits) + ".")
    if top_seed["manager"] != s["champion"]:
        out = None
        for g in sorted([g for g in gs if g["kind"] == "playoff"], key=lambda g: g["week"]):
            if top_seed["manager"] in (g["home"]["manager"], g["away"]["manager"]):
                me = "home" if g["home"]["manager"] == top_seed["manager"] else "away"
                if g["winner"] not in (me, None, "tie"): out = g; break
        line = f"The regular season belonged to {nm(top_seed['manager'])} ({top_seed['teamName']}), the #1 seed at {top_seed['w']}-{top_seed['l']}"
        if out:
            op = "away" if out["home"]["manager"] == top_seed["manager"] else "home"
            me = "home" if op == "away" else "away"
            line += f", but the run ended in week {out['week']} with a {fmt(out[me]['score'])}-{fmt(out[op]['score'])} loss to {nm(out[op]['manager'])}"
        P.append(line + ".")
    if pf["manager"] not in (s["champion"], top_seed["manager"]):
        P.append(f"{nm(pf['manager'])} led the league in points ({fmt(pf['pf'])}) and finished #{pf['finalRank']}" + (" despite missing the playoffs." if pf["seed"] > s["playoffTeams"] else "."))
    A = {a["key"]: a for a in awards}
    if "mvp" in A:
        P.append(f"Carrying the load: {A['mvp']['headline']} was the season's MVP for {' & '.join(nm(m) for m in A['mvp']['holderIds'])}. {A['mvp']['detail']}")
    if "steal" in A and "bust" in A:
        P.append(f"Draft room verdict: {A['steal']['headline']} was the steal of the draft for {' & '.join(nm(m) for m in A['steal']['holderIds'])} ({A['steal']['detail'].rstrip('.')}). "
                 f"On the other end, {' & '.join(nm(m) for m in A['bust']['holderIds'])} spent a top pick on {A['bust']['headline']}, who returned {A['bust']['detail'].split('→ ')[-1]}")
    if "waiver" in A:
        P.append(f"Wire hero: {' & '.join(nm(m) for m in A['waiver']['holderIds'])} found {A['waiver']['headline']}. {A['waiver']['detail']}")
    if "unlucky" in A and A["unlucky"]["value"] <= -1.5:
        P.append(f"Schedule victim of the year: {' & '.join(nm(m) for m in A['unlucky']['holderIds'])}. {A['unlucky']['detail']}")
    if "lucky" in A and A["lucky"]["value"] >= 1.5:
        P.append(f"And the horseshoe award goes to {' & '.join(nm(m) for m in A['lucky']['holderIds'])}: {A['lucky']['detail']}")
    last = max(teams, key=lambda T: T["finalRank"] or 0)
    P.append(f"Bringing up the rear: {nm(last['manager'])} ({last['teamName']}) finished last in the final standings at {last['w']}-{last['l']}.")
    tr = [t for t in s.get("transactions", []) if t["type"] == "TRADE"]
    if tr:
        P.append(f"Trade log: {len(tr)} trade{'s' if len(tr) != 1 else ''} recorded in the weekly archive (see the transactions section below).")
        for t in tr:
            got = collections.defaultdict(list)
            for it in t["items"]:
                if it["type"] == "TRADE" and it.get("toManager"): got[it["toManager"]].append(it["name"])
            if s["champion"] in got and len(got) == 2:
                other = next(m for m in got if m != s["champion"])
                P.append(f"Title-run trade (week {t['week']}): {nm(s['champion'])} acquired {', '.join(got[s['champion']])} from {nm(other)} for {', '.join(got[other])}."
                         + (" Yes, the same manager they beat in the final." if other == s["runnerUp"] else ""))
    return P


def manager_story(p, profiles, seasons):
    S = []
    n = p["name"].split()[0]
    rs = p["seasons"]; comp = [r for r in rs if r["complete"]]
    yrs = p["years"]
    span = f"{yrs[0]}" if len(yrs) == 1 else f"{yrs[0]}-{yrs[-1]}"
    S.append(f"{p['name']} has logged {len(yrs)} season{'s' if len(yrs) != 1 else ''} in the league ({span}), going {p['w']}-{p['l']}{'-'+str(p['t']) if p['t'] else ''} in the regular season "
             f"({p['pct']:.3f}) and averaging {fmt(p['ppg'])} points per game.")
    if p.get("loyalist"):
        S.append(f"A certified Loyalist: one of the original members, here every season since {yrs[0]} without ever leaving.")
    if p.get("inherited"):
        for i in p["inherited"]:
            S.append(f"Took over the team slot previously run by {i['fromName']} in {i['year']}; {i['fromName']}'s results stay on {i['fromName'].split()[0]}'s own page.")
    if p["titles"]:
        belt = [e for e in p.get("belt", []) if not e.get("beltless")]
        bl = [e for e in p.get("belt", []) if e.get("beltless")]
        bits = []
        if bl:
            bits.append(f"Won the {', '.join(str(e['year']) for e in bl)} title, the league's first title, won outright before the Belt arrived in {BELT_YEAR}")
        if belt:
            reigns = len([e for e in belt if not e.get("defense")])
            bits.append(f"{'Held' if bits == [] else 'held'} the Belt after the {', '.join(str(e['year']) for e in belt)} season{'s' if len(belt) > 1 else ''}" + (f" ({reigns} separate reigns)" if reigns > 1 else ""))
            for e in belt:
                if e.get("wonFrom") and e["wonFrom"] == e.get("runnerUp"):
                    bits.append(f"in {e['year']} took it directly from the reigning champ, {nm(e['wonFrom'])}, in the title match")
        S.append("; ".join(bits) + "." + (f" Also a runner-up in {', '.join(map(str, p['runnerUps']))}." if p["runnerUps"] else ""))
    elif p["runnerUps"]:
        S.append(f"{'Never held' if not p['active'] else 'Hasn' + chr(39) + 't held'} the Belt{'' if not p['active'] else ' yet'}, but {n} reached the title match in {', '.join(map(str, p['runnerUps']))}.")
    elif comp:
        S.append("Still chasing a first title (and a first turn with the Belt)." if p["active"] else "Never won a title or held the Belt.")
    for e in LORE.get("entries", []):
        if e.get("featured") and p["id"] in (e.get("managers") or []) and e.get("category") == "game":
            S.append(f"Forever part of league lore: {e['title']} ({e.get('season')}), see below.")
    if comp:
        best = min(comp, key=lambda r: (r["finalRank"], -r["pct"]))
        bestpf = max(comp, key=lambda r: r["pf"] / max(r["w"] + r["l"] + r["t"], 1))
        S.append(f"Signature season: {best['year']} ({best['teamName']}), {best['w']}-{best['l']} and a #{best['finalRank']} finish.")
        if bestpf["year"] != best["year"]:
            S.append(f"The best scoring team came in {bestpf['year']}, {fmt(bestpf['pf'])} regular-season points.")
        # droughts / streaks of playoff appearances
        app = [r["madePlayoffs"] for r in comp]
        run = mx = 0
        for a in app:
            run = run + 1 if a else 0; mx = max(mx, run)
        dr = dmx = 0
        for a in app:
            dr = dr + 1 if not a else 0; dmx = max(dmx, dr)
        if mx >= 3: S.append(f"Made the playoffs in {mx} straight seasons at one point.")
        if dmx >= 2: S.append(f"Also endured a {dmx}-season playoff drought.")
        S.append(f"Playoff appearances: {len(p['playoffApps'])} of {len(comp)} completed seasons; playoff record {p['playoffW']}-{p['playoffL']}.")
        # choke jobs: top-2 seed that lost its first playoff game
        for r in comp:
            if r["seed"] and r["seed"] <= 2 and not r["champion"]:
                s = seasons[r["year"]]
                pg = sorted([g for g in s["games"] if g["kind"] == "playoff" and g.get("away") and p["id"] in (g["home"]["manager"], g["away"]["manager"])], key=lambda g: g["week"])
                if pg:
                    g = pg[0]; me = "home" if g["home"]["manager"] == p["id"] else "away"; op = "away" if me == "home" else "home"
                    if g["winner"] == op:
                        S.append(f"Choke-job file: as the #{r['seed']} seed in {r['year']}, went one-and-done in the playoffs, falling {fmt(g[me]['score'])}-{fmt(g[op]['score'])} to {nm(g[op]['manager'])}.")
        if p["lastPlace"]:
            S.append(f"Finished dead last in {', '.join(map(str, p['lastPlace']))}.")
        luck = sum((r["luck"] or 0) for r in comp)
        if abs(luck) >= 2:
            S.append(f"Over their career the schedule has been {'kind' if luck > 0 else 'cruel'}: {fmt(abs(r2(luck)))} {'more' if luck > 0 else 'fewer'} wins than an all-play record would predict.")
    h = [x for x in p["h2h"] if x["games"] >= 4]
    if h:
        best = max(h, key=lambda x: (x["w"] + x["pw"] - x["l"] - x["pl"], x["games"]))
        worst = min(h, key=lambda x: (x["w"] + x["pw"] - x["l"] - x["pl"], -x["games"]))
        if best["w"] + best["pw"] > best["l"] + best["pl"]:
            S.append(f"Owns {best['oppName']}: {best['w'] + best['pw']}-{best['l'] + best['pl']} all-time (incl. playoffs).")
        if worst["opp"] != best["opp"] and worst["l"] + worst["pl"] > worst["w"] + worst["pw"]:
            S.append(f"Kryptonite: {worst['oppName']}, {worst['w'] + worst['pw']}-{worst['l'] + worst['pl']} against.")
    if p["favorites"]:
        f = p["favorites"][0]
        S.append(f"Most loyal relationship: {f['name']}, on the roster in {f['count']} different seasons ({', '.join(map(str, f['seasons']))}).")
    cur = [r for r in rs if not r["complete"]]
    if cur:
        c = cur[0]
        S.append(f"Dynasty era: running {c['teamName']} in {c['year']}, currently {c['officialRecord']} (incl. median games).")
    elif not p["active"]:
        S.append(f"Not part of the {max(max(x['years']) for x in profiles.values())} league." + (succ_line(p["succeededBy"][-1]) if p["succeededBy"] else ""))
    return S


def alltime(profiles):
    P = list(profiles.values())
    def top(key, rev=True, flt=lambda p: True):
        c = [p for p in P if flt(p)]
        return sorted(c, key=lambda p: p[key] if not callable(key) else key(p), reverse=rev)[0]["id"] if c else None
    vets = lambda p: p["games"] >= 28
    def tied(val, flt=lambda p: True):
        c = [p for p in P if flt(p)]
        if not c: return []
        b = max(val(p) for p in c)
        return [p["id"] for p in sorted(c, key=lambda p: -p["games"]) if _eq(val(p), b)]
    from fractions import Fraction
    frac = lambda p: Fraction(2 * p["w"] + p["t"], 2 * p["games"]) if p["games"] else Fraction(0)
    best_pct = [p["id"] for p in P if vets(p) and frac(p) == max(frac(q) for q in P if vets(q))]
    worst_pct = [p["id"] for p in P if vets(p) and frac(p) == min(frac(q) for q in P if vets(q))]
    return {
        "mostTitles": sorted([(len(p["titles"]), p["id"]) for p in P if p["titles"]], reverse=True),
        "bestPct": best_pct[0] if best_pct else None, "worstPct": worst_pct[0] if worst_pct else None,
        "bestPctAll": best_pct, "worstPctAll": worst_pct,
        "bestPctNext": next((p["id"] for p in sorted([p for p in P if vets(p) and p["id"] not in best_pct], key=lambda p: -frac(p))), None),
        "mostPF": top("pf"), "mostPFAll": tied(lambda p: p["pf"]),
        "mostPlayoffApps": max(P, key=lambda p: len(p["playoffApps"]))["id"],
        "mostPlayoffAppsAll": tied(lambda p: len(p["playoffApps"])),
    }


def league_story(seasons, champions, profiles, records, years):
    S = []
    e = [y for y in years if seasons[y]["platform"] == "ESPN"]
    S.append({"h": "The ESPN redraft years", "p": [
        f"The League of Extraordinary Gentlemen kicked off on ESPN in {e[0]}: ten teams, PPR scoring, and a fresh redraft every August. "
        f"In {BELT_YEAR} the league introduced its WWE-style championship Belt. "
        f"Over {len(e)} seasons ({e[0]}-{e[-1]}) {len(set(c['manager'] for c in champions))} different managers won the title, and {len([p for p in profiles.values() if any(r['platform']=='ESPN' for r in p['seasons'])])} different people ran a team."]})
    for c in champions:
        s = seasons[c["year"]]; T = next(t for t in s["teams"] if t["manager"] == c["manager"])
        ru = next((t for t in s["teams"] if t["manager"] == s["runnerUp"]), None)
        if c["year"] < BELT_YEAR:
            line = f"{c['year']}: {c['name']} ({c['team']}) won it all as the #{T['seed']} seed after {'an' if T['w'] in (8, 11, 18) else 'a'} {T['w']}-{T['l']} regular season" + (f", beating {nm(ru['manager'])} in the final" if ru else "") + f". The Belt didn't exist yet; the title is his outright."
        else:
            prev = belt_holder_before(c["year"])
            verb = "defended the Belt" if prev == c["manager"] else ("won the Belt" if not prev else "won the Belt")
            line = f"{c['year']}: {c['name']} ({c['team']}) {verb} as the #{T['seed']} seed after {'an' if T['w'] in (8, 11, 18) else 'a'} {T['w']}-{T['l']} regular season" + (f", pinning {nm(ru['manager'])} in the title match" if ru else "") + (f" and taking it from the reigning champ himself" if prev and ru and prev == ru["manager"] else "") + "."
            if c["year"] == BELT_YEAR:
                line += " First Belt holder in league history."
        S[-1]["p"].append(line)
    multi = [p for p in profiles.values() if len(p["titles"]) >= 2]
    for p in multi:
        S[-1]["p"].append(f"{p['name']} is the league's only multi-time champion and two-time Belt holder ({', '.join(map(str, p['titles']))})." if len(multi) == 1 else f"{p['name']} owns multiple titles ({', '.join(map(str, p['titles']))}).")
    hs = records["highScores"][0]; bl = records["blowouts"][0]; cl = records["closest"][0]
    S.append({"h": "Moments that live forever", "p": [
        f"The single-game scoring record belongs to {nm(hs['manager'])}: {fmt(hs['score'])} points in week {hs['week']} of {hs['year']} ({hs['team']}).",
        f"The most lopsided result: {nm(bl['winner'])} over {nm(bl['loser'])} by {fmt(bl['margin'])} ({fmt(bl['wScore'])}-{fmt(bl['lScore'])}) in {bl['year']}, week {bl['week']}.",
        f"The closest: {nm(cl['winner'])} edged {nm(cl['loser'])} {fmt(cl['wScore'])}-{fmt(cl['lScore'])} in {cl['year']}, week {cl['week']}, a margin of {fmt(cl['margin'])}."]})
    turnover = [p for p in profiles.values() if not p["active"]]
    ironmen = [p["name"] for p in profiles.values() if all(y in p["years"] for y in e)]
    S.append({"h": "Comings and goings", "p": [
        f"The iron men who played every ESPN season: {', '.join(ironmen)}. "
        f"{len(turnover)} former managers have passed through: {', '.join(p['name'] for p in turnover)}. Every stat stays with the person who earned it, so their numbers live on their own pages, and anyone who took over a team slot starts from zero."]})
    if years[-1] in seasons and seasons[years[-1]]["platform"] == "Sleeper":
        s = seasons[years[-1]]
        new = [p for p in profiles.values() if p["years"] == [years[-1]]]
        S.append({"h": f"{years[-1]}: the dynasty era begins", "p": [
            f"For {years[-1]} the league packed up and moved to Sleeper as a dynasty league: a {s['settings']['draft_rounds'] if False else len(s['drafts'][0]['picks']) // 10}-round startup draft, superflex lineups, a weekly game against the league median, {s['settings']['taxi_slots']} taxi slots, and tradeable future picks. "
            + (f"New blood arrived too: {', '.join(p['name'] for p in new)} joined the league. " if new else "")
            + f"Through {s['completedWeeks']} weeks, {s['teams'][0]['teamName']} ({nm(s['teams'][0]['manager'])}) leads the way."]})
    return S


def _rec(r):
    return f"{r['w']}-{r['l']}" + (f"-{r['t']}" if r.get("t") else "")


def _playoff_games(s, mid):
    return sorted([g for g in s["games"] if g["kind"] == "playoff" and g.get("away") and mid in (g["home"]["manager"], g["away"]["manager"])], key=lambda g: g["week"])


def _side(g, mid):
    me = "home" if g["home"]["manager"] == mid else "away"
    return me, ("away" if me == "home" else "home")


def season_label(r, s, belt_entry):
    if not r["complete"]:
        return "Dynasty year one (in progress)" if s["platform"] == "Sleeper" else "In progress"
    if r["champion"]:
        if belt_entry and belt_entry.get("beltless"): return "Champion (before the Belt)"
        if belt_entry and belt_entry.get("defense"): return "Defended the Belt"
        return "Took the Belt"
    if r["runnerUp"]: return "Lost in the title match"
    if r["finalRank"] == len(s["teams"]): return "Dead last"
    if r["madePlayoffs"]:
        return f"Playoffs as the #{r['seed']} seed"
    return "Missed the playoffs"


def manager_book(p, profiles, seasons, awards, team_mvps):
    mid = p["id"]; first_name = p["name"].split()[0]
    comp = [r for r in p["seasons"] if r["complete"]]
    belts = [e for e in p.get("belt", []) if not e.get("beltless")]
    beltless = [e for e in p.get("belt", []) if e.get("beltless")]
    best = min(comp, key=lambda r: (r["finalRank"], -r["pct"])) if comp else None
    # --- tagline (priority order, all from data)
    rec = f"{p['w']}-{p['l']}" + (f"-{p['t']}" if p["t"] else "")
    if len(belts) >= 2:
        tag = f"{len(belts)}-time Belt holder ({', '.join(str(e['year']) for e in belts)}) and a {rec} career record."
    elif belts and p["runnerUps"]:
        tag = f"Belt holder in {belts[0]['year']}, {len(p['titles']) + len(p['runnerUps'])} title-match trips, and a {p['pct']:.3f} win rate."
    elif belts:
        tag = f"Belt holder in {belts[0]['year']}" + (f" with a {_rec(next(r for r in comp if r['year'] == belts[0]['year']))} regular season." if comp else ".")
    elif beltless:
        tag = f"The league's first champion ({beltless[0]['year']}) won outright before the Belt existed."
    elif p["runnerUps"]:
        tag = f"Made the title match in {', '.join(map(str, p['runnerUps']))}; still waiting on the Belt."
    elif not comp:
        tag = f"New blood: {rec} through the first {p['games']} head-to-head games of the dynasty era."
    elif p["playoffApps"]:
        tag = f"{len(p['playoffApps'])} playoff trip{'s' if len(p['playoffApps']) != 1 else ''} in {len(comp)} season{'s' if len(comp) != 1 else ''}, no Belt yet. Career mark {rec}."
    else:
        tag = f"{len(comp)} season{'s' if len(comp) != 1 else ''}, {rec}, zero playoff trips. The search continues."
    if p.get("loyalist"):
        tag = "🛡️ " + tag
    # --- tale of the tape
    tape = [{"label": "Record", "value": rec, "sub": f"{p['pct']:.3f}"},
            {"label": "Belts", "value": str(len(belts)), "sub": (", ".join(str(e["year"]) for e in belts) + (" · " if belts and beltless else "") + ("Belt-less title " + ", ".join(str(e["year"]) for e in beltless) if beltless else "")) or "none yet"},
            {"label": "Playoff trips", "value": f"{len(p['playoffApps'])}/{len(comp)}" if comp else "-", "sub": f"{p['playoffW']}-{p['playoffL']} in playoff games"},
            {"label": "Best finish", "value": ordinal_s(best["finalRank"]) if best else "-", "sub": str(best["year"]) if best else "in progress"}]
    # --- chapters
    chapters = []
    belt_by_year = {e["year"]: e for e in p.get("belt", [])}
    for r in p["seasons"]:
        y = r["year"]; s = seasons[y]; lines = []
        head = f"{y} - {season_label(r, s, belt_by_year.get(y))}"
        T = next(t for t in s["teams"] if t["manager"] == mid)
        pf_rank = sorted([t["pf"] for t in s["teams"]], reverse=True).index(T["pf"]) + 1
        if r["complete"]:
            l1 = f"As **{r['teamName']}**: {_rec(r)}, {fmt(r['pf'])} points (#{pf_rank} in the league)"
            if r.get("tookOverFrom"): l1 += f", in the slot previously run by {nm(r['tookOverFrom'])}"
            lines.append(l1 + ".")
            pg = _playoff_games(s, mid)
            if pg:
                g = pg[-1]; me, op = _side(g, mid)
                won = g["winner"] == me
                if r["champion"]:
                    lines.append(f"Won the title match **{fmt(g[me]['score'])}-{fmt(g[op]['score'])} over {nm(g[op]['manager'])}**" + (" (the Hamlin game; see the callout)" if y == 2022 and any(e.get('featured') and e.get('season') == 2022 for e in LORE.get('entries', [])) else "") + ".")
                elif r["runnerUp"]:
                    lines.append(f"Fell in the title match **{fmt(g[me]['score'])}-{fmt(g[op]['score'])} to {nm(g[op]['manager'])}**.")
                elif not won:
                    lines.append(f"Bounced in week {g['week']}: **{fmt(g[me]['score'])}-{fmt(g[op]['score'])} vs {nm(g[op]['manager'])}**.")
            elif r["seed"] and r["seed"] <= s["playoffTeams"]:
                lines.append("Earned a first-round bye.")
            elif r["luck"] is not None and r["luck"] <= -1.5:
                lines.append(f"The schedule did them dirty: **{fmt(abs(r['luck']))} fewer wins** than their all-play record deserved.")
        else:
            lines.append(f"As **{r['teamName']}**: {_rec(r)} head-to-head (**{r['officialRecord']}** official, with median games), {fmt(r['pf'])} points through {s.get('completedWeeks')} weeks.")
        mv = team_mvps.get(y, {}).get(mid)
        aw = [dict(a, headline=next((h["headline"] for h in a["holders"] if h["manager"] == mid), a["headline"])) for a in awards.get(y, []) if mid in a["holderIds"] and a["key"] in ("steal", "bust", "waiver", "game", "mvp")]
        extra = None
        for a in aw:
            if a["key"] == "mvp": extra = f"Rode the season's MVP, **{a['headline']}** ({fmt(a['value'])} pts)."; break
            if a["key"] == "steal": extra = f"Draft steal of the year: **{a['headline']}** at pick {a.get('pick', '')}."; break
            if a["key"] == "waiver": extra = f"Best pickup in the league: **{a['headline']}** ({fmt(a['value'])} pts after the add)."; break
            if a["key"] == "bust": extra = f"Owned the draft bust of the year: **{a['headline']}**, taken at {a.get('pick', '')}."; break
        if not extra and mv:
            extra = f"Team MVP: **{mv['name']}** ({fmt(mv['points'])} pts)."
        if extra: lines.append(extra)
        chapters.append({"year": y, "h": head, "lines": lines[:3], "champion": r["champion"]})
    # --- signature moment callout
    sig = None
    lore_feat = [e for e in LORE.get("entries", []) if e.get("featured") and mid in (e.get("managers") or []) and e.get("category") == "game"]
    if comp:
        if p["titles"]:
            y = p["titles"][-1] if not belts else belts[-1]["year"]
            # prefer a title won directly over the reigning champ
            for e in belts:
                if e.get("wonFrom") and e["wonFrom"] == e.get("runnerUp"): y = e["year"]
            g = _playoff_games(seasons[y], mid)[-1]; me, op = _side(g, mid)
            text = f"{y}: **{fmt(g[me]['score'])}-{fmt(g[op]['score'])}** over {nm(g[op]['manager'])} in the title match"
            be = belt_by_year.get(y, {})
            if be.get("beltless"): text += ". The Belt didn't exist yet; the title is his outright."
            elif be.get("wonFrom") and be["wonFrom"] == be.get("runnerUp"): text += f", taking **the Belt straight off the reigning champ**."
            else: text += f" to claim **the Belt**."
            sig = {"title": "Signature moment", "text": text}
        else:
            r = best
            pg = _playoff_games(seasons[r["year"]], mid)
            wins = [g for g in pg if g["winner"] == _side(g, mid)[0]]
            if wins:
                g = max(wins, key=lambda g: g["week"]); me, op = _side(g, mid)
                sig = {"title": "Signature moment", "text": f"{r['year']} playoffs, week {g['week']}: **{fmt(g[me]['score'])}-{fmt(g[op]['score'])} over {nm(g[op]['manager'])}**, en route to a {ordinal_s(r['finalRank'])}-place finish."}
            else:
                hs = max((x for x in [{"score": g[_side(g, mid)[0]]["score"], "g": g, "y": yy} for yy in p["years"] for g in seasons[yy]["games"] if g.get("away") and mid in (g["home"]["manager"], g["away"]["manager"]) and g["kind"] == "regular"]), key=lambda x: x["score"], default=None)
                if hs:
                    g = hs["g"]; me, op = _side(g, mid)
                    sig = {"title": "Career-best game", "text": f"{hs['y']}, week {g['week']}: **{fmt(g[me]['score'])} points** vs {nm(g[op]['manager'])} ({fmt(g[op]['score'])})."}
    elif p["seasons"]:
        r = p["seasons"][-1]
        sig = {"title": "So far", "text": f"Opened the dynasty era **{r['officialRecord']}** with {fmt(r['pf'])} points through {seasons[r['year']].get('completedWeeks')} weeks."}
    if lore_feat:
        sig = sig or {"title": "Signature moment", "text": ""}
        sig["lore"] = [{"id": e["id"], "title": e["title"]} for e in lore_feat]
    # --- quick hits
    h = [x for x in p["h2h"] if x["games"] >= 3]
    score = lambda x: (x["w"] + x["pw"]) - (x["l"] + x["pl"])
    rivals = []
    if h:
        b = max(h, key=lambda x: (score(x), x["games"])); w = min(h, key=lambda x: (score(x), -x["games"]))
        if score(b) > 0: rivals.append(f"**Owns** {nm(b['opp'])}: {b['w'] + b['pw']}-{b['l'] + b['pl']}")
        if w["opp"] != b["opp"] and score(w) < 0: rivals.append(f"**Kryptonite:** {nm(w['opp'])}: {w['w'] + w['pw']}-{w['l'] + w['pl']}")
        most = max(h, key=lambda x: x["games"])
        rivals.append(f"**Most-played:** {nm(most['opp'])}, {most['games']} games ({most['w'] + most['pw']}-{most['l'] + most['pl']})")
    favs = [f"**{x['name']}** ({x['pos']}): {x['count']} seasons ({', '.join(map(str, x['seasons']))})" for x in p["favorites"][:3]]
    bestm, worstm = [], []
    for x in p["bestPicks"][:2]:
        bestm.append(f"{x['year']} draft: **{x['name']}** at {rp(x)} → {x['pos']}{x['posRank']}, {fmt(x['points'])} pts")
    for a in p["awards"]:
        if a["key"] == "waiver": bestm.append(f"{a['season']} pickup: **{next((h['headline'] for h in a['holders'] if h['manager'] == mid), a['headline'])}** ({fmt(a['value'])} pts)")
    for x in p["worstPicks"][:2]:
        worstm.append(f"{x['year']} draft: **{x['name']}** at {rp(x)} → {fmt(x['points'])} pts" + (f" ({x['pos']}{x['posRank']})" if x.get("posRank") else ""))
    notes = []
    if p.get("inherited"):
        notes += [f"Took over {i['fromName']}'s team slot in {i['year']} (no stats inherited)." for i in p["inherited"]]
    if p.get("succeededBy"):
        notes += [succ_line(s).strip() for s in p["succeededBy"]]
    if not p["active"]:
        notes.append(f"Not part of the {max(max(x['years']) for x in profiles.values())} league.")
    return {"tagline": tag, "tape": tape, "chapters": chapters, "signature": sig,
            "quick": {"rivalries": rivals, "favorites": favs, "bestMoves": bestm[:3], "worstMoves": worstm[:3]}, "notes": notes}


def memorial(profiles, records, seasons, years):
    """Tombstones for everyone with no season in the latest league year. Epitaphs are picked from real stats, each used once."""
    fallen = [p for p in profiles.values() if p.get("fallen")]
    fallen.sort(key=lambda p: (p["years"][-1], p["years"][0], p["name"]))
    used = set(); out = []
    hl = records["highLoss"][0] if records.get("highLoss") else None
    worst = records["worstRecords"][0] if records.get("worstRecords") else None
    max_adds = max(((r["transactions"].get("acquisitions", 0), r["year"], m) for m, p in profiles.items() for r in p["seasons"] if r.get("transactions")), default=None)
    for p in fallen:
        mid = p["id"]; comp = [r for r in p["seasons"] if r["complete"]]
        rec = f"{p['w']}-{p['l']}" + (f"-{p['t']}" if p["t"] else "")
        best = min(comp, key=lambda r: (r["finalRank"], -r["pct"])) if comp else None
        cands = []
        lore = [e for e in LORE.get("entries", []) if e.get("featured") and mid in (e.get("managers") or []) and e.get("category") == "game" and e.get("season") in p["runnerUps"]]
        if lore and p["runnerUps"]:
            cands.append(("lore", f"Reached the {lore[0]['season']} title match, the one that ran into the Hamlin game, and lost it. Nobody has had a stranger final." if lore[0]["id"].startswith("hamlin") else f"Lost the {lore[0]['season']} title match: {lore[0]['title']}."))
        if p["runnerUps"]:
            cands.append(("final", f"Made the {p['runnerUps'][-1]} title match. Lost it. Then left the league. Never saw the dynasty era."))
        if hl and hl["manager"] == mid:
            cands.append(("highloss", f"Scored {fmt(hl['score'])} in {hl['year']} and still lost. The highest losing score in league history; he never recovered."))
        if worst and worst["manager"] == mid:
            cands.append(("worst", f"Went {worst['w']}-{worst['l']} in {worst['year']}, the worst record the league has ever seen. Rest easy."))
        if len(comp) >= 3 and not p["playoffApps"]:
            cands.append(("noplayoffs", f"{len(comp)} seasons, {rec}, zero playoff trips. Finally at peace."))
        if max_adds and max_adds[2] == mid:
            cands.append(("adds", f"Made {max_adds[0]} adds in {max_adds[1]}, a league record. The waiver wire still wears black."))
        if p["lastPlace"]:
            cands.append(("last", f"Finished dead last in {', '.join(map(str, p['lastPlace']))}. Taught us all what rock bottom looks like."))
        if p["playoffApps"] and len(comp) == 1 and p["pct"] >= 0.5:
            cands.append(("onehit", f"One season, {rec}, one playoff trip. Burned bright, left fast."))
        if p["playoffApps"] and len(comp) == 1:
            cands.append(("sneak", f"Snuck into the playoffs at {rec} in his only season, then vanished. A ghost story we still tell."))
        cands.append(("default", f"{len(p['years'])} season{'s' if len(p['years']) != 1 else ''}, {rec}. Gone, but not forgotten."))
        ep = next((t for k, t in cands if k not in used or k == "default"), cands[-1][1])
        used.add(next(k for k, t in cands if t == ep))
        yrs = p["years"]
        out.append({"id": mid, "name": p["name"], "years": f"{yrs[0]}" if len(yrs) == 1 else f"{yrs[0]}-{yrs[-1]}",
                    "teamNames": list(dict.fromkeys(t["name"] for t in p["teamNames"])), "record": rec, "pct": p["pct"],
                    "bestFinish": f"{ordinal_s(best['finalRank'])} ({best['year']})" if best else "-",
                    "titles": p["titles"], "runnerUps": p["runnerUps"],
                    "signature": (p.get("book") or {}).get("signature"),
                    "successors": p.get("succeededBy", []), "epitaph": ep,
                    "leftAtMigration": yrs[-1] == max(y for y in years if seasons[y]["platform"] == seasons[yrs[-1]]["platform"]) and seasons[years[-1]]["platform"] != seasons[yrs[-1]]["platform"]})
    return out


def ordinal_s(n):
    if not n: return "-"
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def season_chapters(story):
    """Group the season story paragraphs into short titled chapters (2-3 sentences each), bolding scores."""
    ch = collections.OrderedDict()
    for n, p in enumerate(story):
        if p.startswith("📌"): continue
        if n == 0: k = "The champion" if not p.startswith("Year one") else "The state of play"
        elif p.startswith("The title run") or p.startswith("Title-run trade"): k = "The title run"
        elif "regular season belonged" in p or "led the league in points" in p or "scoring leader" in p or p.startswith("Biggest week"): k = "Regular season"
        elif p.startswith("Draft room"): k = "Draft room"
        elif p.startswith("Carrying the load") or p.startswith("Wire hero"): k = "Stars & the wire"
        elif p.startswith("Schedule victim") or p.startswith("And the horseshoe"): k = "Luck"
        elif p.startswith("Bringing up the rear"): k = "The basement"
        elif p.startswith("Trade log") or "trade market" in p: k = "Trades"
        else: k = "Moments"
        p = re.sub(r"(?<![\w.])(\d{1,3}(?:\.\d+)?-\d{1,3}(?:\.\d+)?)(?![\w.])", r"**\1**", p)
        ch.setdefault(k, []).append(p)
    out = []
    for k, v in ch.items():
        if k == "The title run" and len(v) > 3:
            out.append({"h": k, "lines": v[:2]}); out.append({"h": "Title-run trades", "lines": v[2:]})
        else:
            out.append({"h": k, "lines": v})
    return out

if __name__ == "__main__":
    build()
