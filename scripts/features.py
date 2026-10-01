"""Deep-dive features computed from normalized seasons (+ raw Sleeper):
race charts, schedule luck (all-play), ones that got away, trade report cards, rivalries,
draft habits, projection vs reality, dynasty tracker + player history. Writes data/generated/features.json."""
import os, re, collections, statistics, datetime
from common import *

MANAGERS = load(os.path.join(DATA, "managers.json"))
MGR = {m["id"]: m for m in MANAGERS["managers"]}
LORE = load(os.path.join(DATA, "lore.json"), {"entries": []})


def nm(m): return MGR.get(m, {}).get("name", m)
def first(m): return nm(m).split(" ")[0]
def fmt(x): return f"{x:,.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)
def started(slot): return slot not in (20, 21, "BE", "IR", "TX")


def load_seasons():
    L = load(os.path.join(GEN, "league.json"))
    return L, {y: load(os.path.join(GEN, "seasons", f"{y}.json")) for y in L["years"]}


def tid2m(S): return {str(T["teamId"]): T["manager"] for T in S["teams"]}
def tname(S, m): return next((T["teamName"] for T in S["teams"] if T["manager"] == m), "")
def pinfo(S, pid): return S.get("players", {}).get(str(pid), {"name": f"Player {pid}", "pos": "?"})


def reg_games(S):
    return [g for g in S["games"] if g["kind"] == "regular" and g.get("away") and (g["home"]["score"] or g["away"]["score"])]


def done_weeks(S):
    if S["platform"] == "Sleeper": return S.get("completedWeeks") or 0
    return S["lastWeek"]


def ownership(S):
    """week -> playerId -> (manager, slot, pts) from weekly box scores."""
    tm = tid2m(S); out = {}
    for wk, teams in (S.get("lineupsByWeek") or {}).items():
        if int(wk) > done_weeks(S): continue
        d = out.setdefault(int(wk), {})
        for tid, ent in teams.items():
            m = tm.get(tid)
            for pid, slot, pts in ent:
                d[str(pid)] = (m, slot, pts or 0)
    return out


# ---------------------------------------------------------------- 1. race charts
def race(S):
    gs = reg_games(S)
    if not gs: return None
    weeks = sorted(set(g["week"] for g in gs))
    mgrs = [T["manager"] for T in S["teams"]]
    w = collections.Counter(); l = collections.Counter(); pf = collections.Counter()
    series = {m: [] for m in mgrs}; ranks = {m: [] for m in mgrs}
    for wk in weeks:
        wg = [g for g in gs if g["week"] == wk]
        scores = {}
        for g in wg:
            for a, b in (("home", "away"), ("away", "home")):
                m = g[a]["manager"]; scores[m] = g[a]["score"]; pf[m] += g[a]["score"]
                if g["winner"] == a: w[m] += 1
                else: l[m] += 1
        if S.get("medianGame"):
            med = statistics.median(scores.values())
            for m, sc in scores.items():
                if sc > med: w[m] += 1
                else: l[m] += 1
        order = sorted(mgrs, key=lambda m: (-w[m], -pf[m]))
        for i, m in enumerate(order):
            series[m].append(w[m] - l[m]); ranks[m].append(i + 1)
    n = len(weeks); start = min(3, n - 1)
    collapse = surge = None
    for m in mgrs:
        r = ranks[m]
        if n < 4: break
        bi = min(range(start, n), key=lambda i: (r[i], i)); best = r[bi]
        wi = min(range(start, n), key=lambda i: (-r[i], i)); worst = r[wi]
        drop = r[-1] - min(r[start:]); rise = max(r[start:]) - r[-1]
        if drop > 0 and (not collapse or drop > collapse["places"]):
            collapse = {"manager": m, "peak": best, "peakWeek": weeks[bi], "final": r[-1], "places": drop}
        if rise > 0 and (not surge or rise > surge["places"]):
            surge = {"manager": m, "low": worst, "lowWeek": weeks[wi], "final": r[-1], "places": rise}
    return {"weeks": weeks, "series": series, "ranks": ranks, "collapse": collapse, "surge": surge,
            "teams": {m: tname(S, m) for m in mgrs}}


# ---------------------------------------------------------------- 2. schedule luck
def luck(S):
    gs = reg_games(S)
    rows = {}
    for wk in sorted(set(g["week"] for g in gs)):
        sc = {}
        for g in [g for g in gs if g["week"] == wk]:
            for a in ("home", "away"):
                sc[g[a]["manager"]] = g[a]["score"]
                r = rows.setdefault(g[a]["manager"], {"w": 0, "l": 0, "apW": 0, "apL": 0, "apT": 0, "gp": 0, "pf": 0.0})
                r["gp"] += 1; r["pf"] += g[a]["score"]
                if g["winner"] == a: r["w"] += 1
                else: r["l"] += 1
        for m, s in sc.items():
            for o, t in sc.items():
                if o == m: continue
                k = "apW" if s > t else "apL" if s < t else "apT"
                rows[m][k] += 1
    out = []
    for m, r in rows.items():
        ap = r["apW"] + r["apL"] + r["apT"]
        pct = (r["apW"] + .5 * r["apT"]) / ap if ap else 0
        exp = round(pct * r["gp"], 2)
        out.append(dict(r, manager=m, apPct=round(pct, 3), expW=exp, luck=round(r["w"] - exp, 2), pf=round(r["pf"], 2)))
    out.sort(key=lambda r: -r["luck"])
    return out


# ---------------------------------------------------------------- 3. ones that got away
def regrets(S, own):
    out = {}
    last = done_weeks(S)
    for t in S.get("transactions", []):
        for it in t["items"]:
            if it["type"] != "DROP" or not it.get("fromManager"): continue
            m = it["fromManager"]; pid = str(it["playerId"]); wk = t["week"] or 1
            pts_for = collections.Counter(); st_for = collections.Counter(); weeks = 0
            for w in range(max(1, wk), last + 1):
                o = own.get(w, {}).get(pid)
                if not o: continue
                if o[0] == m:
                    if w > wk: break      # re-acquired: the regret window closes
                    continue
                weeks += 1; pts_for[o[0]] += o[2]
                if started(o[1]): st_for[o[0]] += o[2]
            tot = sum(st_for.values())
            if tot <= 0: continue
            key = (m, pid)
            if key in out and out[key]["startedForOthers"] >= tot: continue
            beneficiary = st_for.most_common(1)[0][0]
            p = pinfo(S, pid)
            out[key] = {"year": S["year"], "week": wk, "manager": m, "playerId": pid, "name": it.get("name") or p["name"], "pos": it.get("pos") or p["pos"],
                        "startedForOthers": round(tot, 2), "rosteredPts": round(sum(pts_for.values()), 2), "weeks": weeks,
                        "beneficiary": beneficiary, "beneficiaryPts": round(st_for[beneficiary], 2),
                        "champBenefit": S.get("champion") == beneficiary}
    return sorted(out.values(), key=lambda r: -r["startedForOthers"])


# ---------------------------------------------------------------- 4. trade report cards
def grade(share):
    for g, cut in (("A+", .75), ("A", .65), ("B", .56), ("C", .44), ("D", .35)):
        if share >= cut: return g
    return "F"


def trades(S, own):
    out = []
    last = done_weeks(S); live = S["platform"] == "Sleeper" and S.get("status") != "complete"
    for t in S.get("transactions", []):
        if t["type"] != "TRADE": continue
        sides = collections.defaultdict(lambda: {"players": [], "picks": [], "started": 0.0, "total": 0.0})
        for it in t["items"]:
            if it["type"] != "TRADE" or not it.get("toManager"): continue
            pid = str(it["playerId"]); m = it["toManager"]
            st = tot = 0.0; ws = 0
            for w in range(max(1, t["week"] or 1), last + 1):
                o = own.get(w, {}).get(pid)
                if o and o[0] == m:
                    tot += o[2]
                    if started(o[1]): st += o[2]; ws += 1
            sides[m]["players"].append({"name": it["name"], "pos": it.get("pos", "?"), "from": it.get("fromManager"), "started": round(st, 2), "total": round(tot, 2), "starts": ws})
            sides[m]["started"] += st; sides[m]["total"] += tot
        for pk in t.get("picks", []) or []:
            if pk.get("toManager"):
                sides[pk["toManager"]]["picks"].append(f"{pk['season']} R{pk['round']}" + (f" (orig. {first(pk['originalManager'])})" if pk.get("originalManager") and pk["originalManager"] != pk.get("fromManager") else ""))
        if len(sides) < 2: continue
        total = sum(s["started"] for s in sides.values())
        res = []
        for m, s in sides.items():
            share = s["started"] / total if total else .5
            res.append({"manager": m, "players": s["players"], "picks": s["picks"], "started": round(s["started"], 2), "total": round(s["total"], 2),
                        "share": round(share, 3), "grade": grade(share) if total else "INC"})
        res.sort(key=lambda r: -r["started"])
        margin = round(res[0]["started"] - res[1]["started"], 2)
        out.append({"id": t["id"], "year": S["year"], "week": t["week"], "date": t.get("date"), "sides": res,
                    "winner": res[0]["manager"] if margin >= 5 else None, "margin": margin, "total": round(total, 2),
                    "hasPicks": any(r["picks"] for r in res), "live": live,
                    "note": ("Includes draft picks that can't be scored yet. " if any(r["picks"] for r in res) else "") +
                            ("Season in progress: grade is provisional." if live else "")})
    return out


# ---------------------------------------------------------------- 5. rivalries
def all_games(seasons):
    out = []
    for y, S in seasons.items():
        for g in S["games"]:
            if not g.get("away") or not (g["home"]["score"] or g["away"]["score"]): continue
            if S["platform"] == "Sleeper" and g["week"] > done_weeks(S): continue
            w = g["winner"]
            out.append({"year": y, "week": g["week"], "kind": g["kind"], "final": bool(g.get("isFinal")),
                        "a": g["home"]["manager"], "as": g["home"]["score"], "b": g["away"]["manager"], "bs": g["away"]["score"],
                        "w": g["home"]["manager"] if w == "home" else g["away"]["manager"]})
    return out


def pair_id(a, b): return "--".join(sorted([a, b]))


def rivalries(games):
    P = {}
    for g in games:
        if g["kind"] == "consolation": continue
        k = pair_id(g["a"], g["b"]); x, y = sorted([g["a"], g["b"]])
        r = P.setdefault(k, {"id": k, "a": x, "b": y, "games": [], "wins": collections.Counter(), "pts": collections.Counter()})
        r["games"].append(g); r["wins"][g["w"]] += 1
        r["pts"][g["a"]] += g["as"]; r["pts"][g["b"]] += g["bs"]
    out = {}
    for k, r in P.items():
        gs = sorted(r["games"], key=lambda g: (g["year"], g["week"]))
        a, b = r["a"], r["b"]
        margins = [abs(g["as"] - g["bs"]) for g in gs]
        po = [g for g in gs if g["kind"] == "playoff"]
        streak, cur = None, (None, 0)
        for g in gs:
            cur = (g["w"], cur[1] + 1) if cur[0] == g["w"] else (g["w"], 1)
            if not streak or cur[1] > streak[1]: streak = cur
        def side(g, m): return (g["as"], g["bs"]) if g["a"] == m else (g["bs"], g["as"])
        rows = [{"year": g["year"], "week": g["week"], "kind": g["kind"], "final": g["final"], "winner": g["w"],
                 "aScore": side(g, a)[0], "bScore": side(g, a)[1], "margin": round(abs(g["as"] - g["bs"]), 2), "combined": round(g["as"] + g["bs"], 2)} for g in gs]
        lore = [e["id"] for e in LORE.get("entries", []) if a in e.get("managers", []) and b in e.get("managers", [])]
        out[k] = {"id": k, "a": a, "b": b, "n": len(gs), "aW": r["wins"][a], "bW": r["wins"][b],
                  "aPts": round(r["pts"][a], 2), "bPts": round(r["pts"][b], 2), "avgMargin": round(sum(margins) / len(gs), 2),
                  "playoff": len(po), "finals": sum(1 for g in gs if g["final"]), "streak": {"manager": streak[0], "n": streak[1]},
                  "games": rows, "closest": sorted(rows, key=lambda g: g["margin"])[:3], "blowout": max(rows, key=lambda g: g["margin"]),
                  "shootout": max(rows, key=lambda g: g["combined"]), "lore": lore,
                  "years": sorted(set(g["year"] for g in gs))}
    # auto-pick headline rivalries
    picks = []
    def add(cands, tag, why):
        if isinstance(cands, str): cands = [cands]
        for k in cands:
            if k in out and k not in [p["id"] for p in picks]:
                out[k]["tag"] = tag; out[k]["why"] = why(out[k]); picks.append(out[k]); return
    R = list(out.values())
    big = [r for r in R if r["n"] >= 6]
    ids = lambda lst: [r["id"] for r in lst]
    saga = next((e for e in LORE.get("entries", []) if e.get("style") == "saga"), None)
    if saga:
        ms = [m for m in saga["managers"] if m in ("jacob-maddox", "ryan-nussdorfer")] or saga["managers"][:2]
        add(pair_id(*ms[:2]), "The Grudge", lambda r: f"{saga['title']}. Need we say more?")
    add(ids(sorted(R, key=lambda r: (-r["n"], -r["playoff"]))), "Most Played", lambda r: f"{r['n']} meetings")
    add(ids(sorted([r for r in R if r["playoff"]], key=lambda r: (-r["playoff"], -r["finals"], -r["n"]))), "Playoff Rivals", lambda r: f"{r['playoff']} playoff meetings")
    add(ids(sorted([r for r in R if r["finals"]], key=lambda r: (-r["finals"], -r["playoff"], -r["n"]))), "Title Fight", lambda r: f"{r['finals']} championship meeting" + ("s" if r["finals"] > 1 else ""))
    add(ids(sorted(big, key=lambda r: (abs(r["aW"] - r["bW"]), -r["n"], r["avgMargin"]))), "Dead Even", lambda r: f"{r['aW']}-{r['bW']} over {r['n']} games")
    add(ids(sorted(big, key=lambda r: r["avgMargin"])), "Knife Fights", lambda r: f"average margin {fmt(r['avgMargin'])} pts")
    add(ids(sorted(big, key=lambda r: -abs(r["aW"] - r["bW"]) / r["n"])), "Big Brother", lambda r: f"a {max(r['aW'], r['bW'])}-{min(r['aW'], r['bW'])} series")
    add(ids(sorted(R, key=lambda r: -r["streak"]["n"])), "The Streak", lambda r: f"{short(r['streak']['manager'], r)} won {r['streak']['n']} straight")
    for r in out.values(): r["blurb"] = rivalry_blurb(r)
    return out, [p["id"] for p in picks]


def short(m, r):
    """First name unless both rivals share it (Jacob vs Jacob)."""
    return nm(m) if first(r["a"]) == first(r["b"]) else first(m)


def rivalry_blurb(r):
    a, b = r["a"], r["b"]
    first = lambda m: short(m, r)
    lead, trail = (a, b) if r["aW"] >= r["bW"] else (b, a)
    lw, tw = max(r["aW"], r["bW"]), min(r["aW"], r["bW"])
    s = (f"{nm(a)} and {nm(b)} have met {r['n']} time{'s' if r['n'] != 1 else ''} ({r['years'][0]}" + (f"-{r['years'][-1]}" if len(r['years']) > 1 else "") + "). ")
    s += f"The series is dead even at {lw}-{tw}. " if lw == tw else f"{first(lead)} leads {lw}-{tw}. "
    s += f"Average margin: {fmt(r['avgMargin'])} points. "
    if r["playoff"]: s += f"They've met {r['playoff']} time{'s' if r['playoff'] > 1 else ''} in the playoffs" + (f", including {r['finals']} title game{'s' if r['finals'] > 1 else ''}" if r["finals"] else "") + ". "
    c = r["closest"][0]
    s += f"Closest call: {c['year']} week {c['week']}, decided by {fmt(c['margin'])}. "
    if r["streak"]["n"] >= 3: s += f"Longest streak: {first(r['streak']['manager'])}, {r['streak']['n']} in a row."
    return s.strip()


# ---------------------------------------------------------------- 6. draft habits
THRESH = {"QB": 12, "RB": 24, "WR": 30, "TE": 12, "K": 10, "D/ST": 10}
BUCKETS = [("R1", 1, 1), ("R2", 2, 2), ("R3-4", 3, 4), ("R5-8", 5, 8), ("R9+", 9, 99)]


def draft_habits(seasons):
    per = collections.defaultdict(lambda: {"picks": [], "years": set()})
    for y, S in seasons.items():
        if S["platform"] != "ESPN": continue
        adp = S.get("adp", {})
        for p in S["draft"]:
            q = dict(p, year=y)
            per[p["manager"]]["picks"].append(q); per[p["manager"]]["years"].add(y)
    allp = [p for d in per.values() for p in d["picks"] if "valueDelta" in p]
    rmean = {r: statistics.mean(p["valueDelta"] for p in allp if p["round"] == r) for r in set(p["round"] for p in allp)}
    out = {}
    for m, d in per.items():
        ps = d["picks"]
        mix = {b: collections.Counter() for b, _, _ in BUCKETS}
        for p in ps:
            for b, lo, hi in BUCKETS:
                if lo <= p["round"] <= hi: mix[b][p["pos"]] += 1
        r1 = [p for p in ps if p["round"] == 1]
        early = [p for p in ps if p["round"] <= 6 and p["pos"] in THRESH]
        hits = [p for p in early if p.get("posRank") and p["posRank"] <= THRESH[p["pos"]]]
        busts = [p for p in early if not p.get("posRank") or p["posRank"] > 2 * THRESH[p["pos"]]]
        val = [p for p in ps if "valueDelta" in p and p["round"] <= 8]
        skill = [p for p in ps if "valueDelta" in p]
        best = sorted([p for p in skill if p.get("valueRank", 999) <= 40], key=lambda p: -p["valueDelta"])[:3]
        worst = sorted([p for p in skill if p["round"] <= 5], key=lambda p: p["valueDelta"])[:3]
        slim = lambda p: {k: p.get(k) for k in ("year", "round", "pick", "overall", "name", "pos", "posRank", "points", "valueDelta")}
        out[m] = {"drafts": len(d["years"]), "n": len(ps),
                  "mix": {b: dict(c) for b, c in mix.items()},
                  "r1": [slim(p) for p in sorted(r1, key=lambda p: p["year"])],
                  "avgR1Slot": round(sum(p["pick"] for p in r1) / len(r1), 1) if r1 else None,
                  "r1Pos": dict(collections.Counter(p["pos"] for p in r1)),
                  "early": len(early), "hits": len(hits), "busts": len(busts),
                  "hitRate": round(len(hits) / len(early), 3) if early else None, "bustRate": round(len(busts) / len(early), 3) if early else None,
                  "avgValue": round(statistics.mean(p["valueDelta"] - rmean[p["round"]] for p in val), 1) if val else None,
                  "best": [slim(p) for p in best], "worst": [slim(p) for p in worst],
                  "firstQB": round(statistics.mean([min([p["round"] for p in ps if p["year"] == y and p["pos"] == "QB"] or [99]) for y in d["years"]]), 1),
                  "kdstAvg": round(statistics.mean([p["round"] for p in ps if p["pos"] in ("K", "D/ST")] or [0]), 1)}
    # league-wide trends
    trends = []
    for y, S in sorted(seasons.items()):
        if S["platform"] != "ESPN": continue
        dr = S["draft"]; r1 = [p for p in dr if p["round"] == 1]
        qb = sorted([p for p in dr if p["pos"] == "QB"], key=lambda p: p["overall"])
        te = sorted([p for p in dr if p["pos"] == "TE"], key=lambda p: p["overall"])
        trends.append({"year": y, "r1": dict(collections.Counter(p["pos"] for p in r1)),
                       "r12": dict(collections.Counter(p["pos"] for p in dr if p["round"] <= 2)),
                       "firstQB": qb[0] and {"overall": qb[0]["overall"], "name": qb[0]["name"], "manager": qb[0]["manager"]},
                       "firstTE": te[0] and {"overall": te[0]["overall"], "name": te[0]["name"], "manager": te[0]["manager"]},
                       "firstK": min([p["overall"] for p in dr if p["pos"] == "K"] or [None]),
                       "firstDST": min([p["overall"] for p in dr if p["pos"] == "D/ST"] or [None]),
                       "r1Hits": sum(1 for p in r1 if p.get("posRank") and p["posRank"] <= THRESH.get(p["pos"], 0)), "r1N": len(r1)})
    return out, trends


# ---------------------------------------------------------------- 7. projections
def projections(S):
    pj = S.get("projByWeek")
    if not pj: return None
    tm = tid2m(S); team_wk = {}; players = []
    for wk, teams in S.get("lineupsByWeek", {}).items():
        for tid, ent in teams.items():
            P = pj.get(wk, {}).get(tid)
            if P is None: continue
            proj = act = 0.0; missing = 0; rows = []
            for pid, slot, pts in ent:
                if not started(slot): continue
                if str(pid) not in P: missing += 1
                pp = P.get(str(pid), 0.0); proj += pp; act += pts or 0
                if S["year"] == 2022 and int(wk) == 17 and not pts: continue  # Bills-Bengals game cancelled (Hamlin)
                rows.append({"year": S["year"], "week": int(wk), "manager": tm[tid], "name": pinfo(S, pid)["name"], "pos": pinfo(S, pid)["pos"],
                                "proj": pp, "pts": pts or 0, "diff": round((pts or 0) - pp, 2)})
            if missing > 1 or proj < 50: continue   # projection feed incomplete for this team-week
            players += [r for r in rows if r["proj"] > 0]
            team_wk[(int(wk), tm[tid])] = (round(proj, 2), round(act, 2))
    per = collections.defaultdict(lambda: {"proj": 0.0, "act": 0.0, "n": 0, "beat": 0})
    games = []
    for g in S["games"]:
        if not g.get("away"): continue
        h, a = g["home"]["manager"], g["away"]["manager"]
        if (g["week"], h) not in team_wk or (g["week"], a) not in team_wk: continue
        ph, pa = team_wk[(g["week"], h)][0], team_wk[(g["week"], a)][0]
        for m, p, sc in ((h, ph, g["home"]["score"]), (a, pa, g["away"]["score"])):
            if g["kind"] == "regular":
                r = per[m]; r["proj"] += p; r["act"] += sc; r["n"] += 1; r["beat"] += sc > p
        fav, dog = (h, a) if ph >= pa else (a, h)
        fs, ds = (g["home"]["score"], g["away"]["score"]) if fav == h else (g["away"]["score"], g["home"]["score"])
        fp, dp = (ph, pa) if fav == h else (pa, ph)
        rec = {"year": S["year"], "week": g["week"], "kind": g["kind"], "final": bool(g.get("isFinal")), "fav": fav, "dog": dog,
               "favProj": fp, "dogProj": dp, "favScore": fs, "dogScore": ds, "projEdge": round(fp - dp, 2), "lostBy": round(ds - fs, 2)}
        games.append(rec)
    chokes = sorted([g for g in games if g["lostBy"] > 0 and g["projEdge"] >= 10], key=lambda g: -(g["projEdge"] + g["lostBy"]))
    rows = [{"manager": m, "games": r["n"], "proj": round(r["proj"], 2), "act": round(r["act"], 2), "diff": round(r["act"] - r["proj"], 2),
             "perGame": round((r["act"] - r["proj"]) / r["n"], 2) if r["n"] else 0, "beat": r["beat"]} for m, r in per.items()]
    rows.sort(key=lambda r: -r["perGame"])
    tw = [{"year": S["year"], "week": wk, "manager": m, "proj": p, "act": a, "diff": round(a - p, 2)} for (wk, m), (p, a) in team_wk.items()]
    return {"rows": rows, "chokes": chokes[:10], "upsets": len([g for g in games if g["lostBy"] > 0]), "nGames": len(games),
            "teamWeeks": tw, "players": players}


# ---------------------------------------------------------------- 8. dynasty tracker + player history
def norm(n):
    n = (n or "").lower().replace(".", "").replace("'", "").replace("’", "")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"[^a-z ]", "", n).split() and " ".join(re.sub(r"[^a-z ]", "", n).split())


def dynasty(seasons):
    dyn = [S for S in seasons.values() if S["platform"] == "Sleeper"]
    if not dyn: return None
    S = max(dyn, key=lambda s: s["year"])
    lg = load(os.path.join(RAW, "sleeper", "sleeper_league.json"), {})
    rounds = (lg.get("settings") or {}).get("draft_rounds") or 3
    tp = S.get("tradedPicks", [])
    yrs = sorted(set([str(S["year"] + i) for i in (1, 2, 3)] + [t["season"] for t in tp]))
    teams = sorted(S["teams"], key=lambda T: nm(T["manager"]))
    owner = {(y, r, T["teamId"]): T["manager"] for y in yrs for r in range(1, rounds + 1) for T in teams}
    for t in tp: owner[(t["season"], t["round"], t["originalRosterId"])] = t["ownerManager"]
    grid = []
    for T in teams:
        grid.append({"manager": T["manager"], "cells": {y: [{"round": r, "owner": owner[(y, r, T["teamId"])], "traded": owner[(y, r, T["teamId"])] != T["manager"]} for r in range(1, rounds + 1)] for y in yrs}})
    counts = collections.Counter(owner.values())
    # ages
    PDB = load(os.path.join(RAW, "sleeper", "players_nfl.json"), {})
    ages = []
    lw = max([int(k) for k in S.get("lineupsByWeek", {})] or [0])
    starters = {}
    if lw:
        tm = tid2m(S)
        for tid, ent in S["lineupsByWeek"][str(lw)].items():
            starters[tm[tid]] = {str(p) for p, sl, _ in ent if sl == "ST"}
    for T in teams:
        ros = S["rosters"].get(str(T["teamId"]), [])
        a = []
        for e in ros:
            p = PDB.get(str(e["playerId"]), {})
            age = p.get("age") or e.get("age")
            if age and e.get("pos") not in ("DEF",): a.append((age, e["name"], e.get("pos"), str(e["playerId"]) in starters.get(T["manager"], set())))
        if not a: continue
        buckets = collections.Counter("≤23" if x[0] <= 23 else "24-26" if x[0] <= 26 else "27-29" if x[0] <= 29 else "30+" for x in a)
        st = [x[0] for x in a if x[3]]
        ages.append({"manager": T["manager"], "team": T["teamName"], "avg": round(statistics.mean(x[0] for x in a), 1),
                     "starterAvg": round(statistics.mean(st), 1) if st else None, "n": len(a), "buckets": dict(buckets),
                     "youngest": min(a)[:3], "oldest": max(a)[:3]})
    ages.sort(key=lambda r: r["avg"])
    return {"year": S["year"], "years": yrs, "rounds": rounds, "grid": grid, "pickCounts": dict(counts), "ages": ages, "traded": len(tp)}


def player_history(seasons):
    H = {}
    for y, S in sorted(seasons.items()):
        own = ownership(S)
        drafted = {str(p["playerId"]): p for p in S.get("draft") or []}
        seen = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
        for wk, d in own.items():
            for pid, (m, slot, pts) in d.items():
                r = seen[pid][m]; r[0] += 1
                if started(slot): r[1] += pts
        for pid in set(seen) | set(drafted):
            p = pinfo(S, pid); key = norm(p["name"])
            if not key or p["name"].startswith("Player "): continue
            e = H.setdefault(key, {"n": p["name"], "p": p["pos"], "h": []})
            dp = drafted.get(pid)
            ms = set(seen[pid]) | ({dp["manager"]} if dp else set())
            for m in ms:
                wks, pts = seen[pid].get(m, [0, 0.0])
                row = [y, m, wks, round(pts, 1)]
                if dp and dp["manager"] == m: row.append(f"R{dp['round']}.{dp['pick']:02d}")
                e["h"].append(row)
    return H


# ---------------------------------------------------------------- main
def main():
    L, seasons = load_seasons()
    years = sorted(seasons)
    owns = {y: ownership(S) for y, S in seasons.items()}
    out = {"seasons": {}, "luckAll": [], "regrets": [], "trades": [], "projAll": None}
    allluck = collections.defaultdict(lambda: {"w": 0, "l": 0, "apW": 0, "apL": 0, "apT": 0, "gp": 0, "expW": 0.0, "seasons": 0})
    allproj = collections.defaultdict(lambda: {"proj": 0.0, "act": 0.0, "games": 0, "beat": 0})
    tw_all, pl_all, ch_all = [], [], []
    for y in years:
        S = seasons[y]
        rc, lk = race(S), luck(S)
        rg = regrets(S, owns[y]); tr = trades(S, owns[y]); pj = projections(S)
        for r in lk:
            a = allluck[r["manager"]]
            for k in ("w", "l", "apW", "apL", "apT", "gp"): a[k] += r[k]
            a["expW"] += r["expW"]; a["seasons"] += 1
        out["regrets"] += rg; out["trades"] += tr
        if pj:
            for r in pj["rows"]:
                a = allproj[r["manager"]]; a["proj"] += r["proj"]; a["act"] += r["act"]; a["games"] += r["games"]; a["beat"] += r["beat"]
            tw_all += pj["teamWeeks"]; pl_all += pj["players"]; ch_all += pj["chokes"]
            pjs = {"rows": pj["rows"], "chokes": pj["chokes"][:3], "nGames": pj["nGames"], "upsets": pj["upsets"],
                   "over": sorted(pj["teamWeeks"], key=lambda r: -r["diff"])[:3], "under": sorted(pj["teamWeeks"], key=lambda r: r["diff"])[:3]}
        else:
            pjs = None
        out["seasons"][str(y)] = {"race": rc, "luck": lk, "regrets": rg[:8], "trades": [t["id"] for t in tr], "proj": pjs}
    out["luckAll"] = sorted([dict(v, manager=m, expW=round(v["expW"], 2), luck=round(v["w"] - v["expW"], 2),
                                  apPct=round((v["apW"] + .5 * v["apT"]) / max(1, v["apW"] + v["apL"] + v["apT"]), 3)) for m, v in allluck.items()], key=lambda r: -r["luck"])
    allseason = [dict(r, year=int(y)) for y, d in out["seasons"].items() for r in d["luck"]]
    out["luckSeasons"] = {"lucky": sorted(allseason, key=lambda r: -r["luck"])[:5], "unlucky": sorted(allseason, key=lambda r: r["luck"])[:5]}
    out["regrets"].sort(key=lambda r: -r["startedForOthers"])
    out["regretsTop"] = out["regrets"][:20]
    # trade records
    trec = collections.defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "n": 0, "net": 0.0})
    for t in out["trades"]:
        for s in t["sides"]:
            r = trec[s["manager"]]; r["n"] += 1
            others = [o["started"] for o in t["sides"] if o is not s]
            r["net"] += s["started"] - (sum(others) / len(others))
            if not t["winner"]: r["t"] += 1
            elif t["winner"] == s["manager"]: r["w"] += 1
            else: r["l"] += 1
    out["tradeRecords"] = sorted([dict(v, manager=m, net=round(v["net"], 2)) for m, v in trec.items()], key=lambda r: (-r["w"] + r["l"], -r["net"]))
    out["trades"].sort(key=lambda t: (-t["year"], -(t["week"] or 0)))
    # rivalries
    games = all_games(seasons)
    riv, picks = rivalries(games)
    out["rivalries"] = riv; out["rivalryPicks"] = picks
    # draft
    out["draftHabits"], out["draftTrends"] = draft_habits(seasons)
    # projections all-time
    if tw_all:
        out["projAll"] = {"rows": sorted([dict(v, manager=m, proj=round(v["proj"], 2), act=round(v["act"], 2), diff=round(v["act"] - v["proj"], 2),
                                              perGame=round((v["act"] - v["proj"]) / v["games"], 2)) for m, v in allproj.items() if v["games"]], key=lambda r: -r["perGame"]),
                          "overTeam": sorted(tw_all, key=lambda r: -r["diff"])[:8], "underTeam": sorted(tw_all, key=lambda r: r["diff"])[:8],
                          "overPlayer": sorted(pl_all, key=lambda r: -r["diff"])[:8], "underPlayer": sorted(pl_all, key=lambda r: r["diff"])[:8],
                          "chokes": sorted(ch_all, key=lambda g: -(g["projEdge"] + g["lostBy"]))[:12],
                          "years": [y for y in years if seasons[y].get("projByWeek")]}
    # per-manager rollups
    pm = collections.defaultdict(dict)
    for m in L["profiles"]:
        pm[m]["luck"] = [dict(r, year=int(y)) for y, d in out["seasons"].items() for r in d["luck"] if r["manager"] == m]
        pm[m]["luckAll"] = next((r for r in out["luckAll"] if r["manager"] == m), None)
        pm[m]["regrets"] = [r for r in out["regrets"] if r["manager"] == m][:5]
        pm[m]["tradeRecord"] = next((r for r in out["tradeRecords"] if r["manager"] == m), None)
        pm[m]["trades"] = [t["id"] for t in out["trades"] if any(s["manager"] == m for s in t["sides"])]
        pm[m]["draft"] = out["draftHabits"].get(m)
        pm[m]["rivalries"] = sorted([k for k, r in riv.items() if m in (r["a"], r["b"])], key=lambda k: (-riv[k]["n"], -riv[k]["playoff"]))
        pm[m]["proj"] = next((r for r in (out["projAll"] or {}).get("rows", []) if r["manager"] == m), None)
    out["managers"] = pm
    out["dynasty"] = dynasty(seasons)
    save(os.path.join(GEN, "features.json"), out)
    ph = player_history(seasons)
    os.makedirs(os.path.join(GEN), exist_ok=True)
    import json
    with open(os.path.join(GEN, "players_history.json"), "w") as fh: json.dump(ph, fh, separators=(",", ":"))
    print("features: trades", len(out["trades"]), "regrets", len(out["regrets"]), "rivalries", len(riv), "players", len(ph))


if __name__ == "__main__":
    main()
