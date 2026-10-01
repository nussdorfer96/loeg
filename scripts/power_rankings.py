#!/usr/bin/env python3
"""Weekly dynasty power rankings for the LOEG Sleeper league.

Usage:
  python3 scripts/power_rankings.py                 # current Sleeper week (run after Wednesday waivers)
  python3 scripts/power_rankings.py --week 5        # rank going into week 5 (uses weeks 1..4 results)
  python3 scripts/power_rankings.py --offline       # rebuild from cached API responses only
  python3 scripts/power_rankings.py --drafts        # also write drafts/ md + html mock + 390px screenshot
Weekly publish: bash scripts/publish_power_rankings.sh  (computes, then runs scripts/publish.sh).
scripts/publish.sh never recomputes rankings; build_site.py renders the latest saved JSON.

Inputs (all public, no auth):
  Sleeper v1 API: league, users, rosters, matchups/{w}, transactions/{w}, traded_picks, state; players/nfl (cached 7 days)
  Sleeper projections: https://api.sleeper.app/projections/nfl/{season}/{week} (weekly, scored with the league's own scoring_settings)
  Dynasty values: FantasyCalc API (primary; superflex/1QB, PPR and team count matched to league settings)
                  KeepTradeCut dynasty-rankings page (cross-check; superflex or 1QB values; name-matched)
Blurbs: auto-generated from the data (last week's result + top scorer, trades/waivers, injuries, rank movement).
  Hand-written overrides (tracked in git): data/power_rankings_blurbs/{season}_w{NN}.json  {"<manager-id>": "text", ...}
  (or --blurbs PATH). Any team missing from the override file gets the auto blurb.
Outputs: data/power_rankings_history/{season}_w{NN}.json (tracked in git; build_site.py renders the highest week
  of the current season plus the week-over-week movement chart from all weeks)
Retro (--retro --week N, N < current week): a back-dated ranking. Uses results through week N-1, the roster each team
  actually carried in week N (Sleeper matchup rosters), Sleeper's weekly projections for weeks N..end, and picks as
  owned then. Dynasty values are TODAY's (historic values aren't available). No blurbs; flagged meta.retro.
  With --drafts: drafts/power_rankings_w{week}.md / .html / .json and screenshots/power_rankings_w{week}.png
"""
import argparse, datetime as dt, html, json, os, re, statistics, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "raw", "sleeper", "power_rankings")
PLAYERS = os.path.join(ROOT, "raw", "sleeper", "players_nfl.json")
OUT = os.path.join(ROOT, "data", "power_rankings_history")
BLURBS = os.path.join(ROOT, "data", "power_rankings_blurbs")
BAD_INJ = {"Out", "IR", "Doubtful", "PUP", "Sus", "NFI"}
API = "https://api.sleeper.app/v1"
UA = {"User-Agent": "Mozilla/5.0 (LOEG power rankings script)"}

# ---- weights (edit here; printed into every output) ----
W_ACTUAL, W_PROJ = 0.5, 0.5             # inside Win-Now
W_ACT_PARTS = {"win_pct": 1/3, "pf": 1/3, "allplay": 1/3}
W_PROJ_PARTS = {"ros": 0.75, "next": 0.25}  # ROS optimal lineup vs this week's optimal lineup
W_WINNOW, W_DYNASTY = 0.5, 0.5          # overall blend
GAP = []                                # data gaps collected while running


def gap(msg):
    GAP.append(msg); print("GAP:", msg, file=sys.stderr)


def fetch(url, path=None, max_age=None, offline=False, raw=False):
    """GET url (JSON unless raw). Cache to path; reuse cache if younger than max_age seconds or offline."""
    if path and os.path.exists(path) and (offline or (max_age and time.time() - os.path.getmtime(path) < max_age)):
        with open(path) as f:
            return f.read() if raw else json.load(f)
    if offline:
        raise FileNotFoundError(path or url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8")
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
    return body if raw else json.loads(body)


def zs(vals):
    m = statistics.mean(vals); s = statistics.pstdev(vals) or 1.0
    return [(v - m) / s for v in vals]


def ranks(vals, reverse=True):
    order = sorted(range(len(vals)), key=lambda i: vals[i], reverse=reverse)
    out = [0] * len(vals)
    for r, i in enumerate(order, 1):
        out[i] = r
    return out


def age_on(bd, today):
    try:
        b = dt.date.fromisoformat(bd[:10])
    except Exception:
        return None
    return round((today - b).days / 365.25, 1)


def score(stats, sc):
    """Score a projection stat line with the league's scoring settings."""
    return sum(v * sc[k] for k, v in stats.items() if k in sc and isinstance(v, (int, float)))


def optimal_lineup(pids, pts, pos_of, slots):
    """Greedy optimal fill: fixed slots, then FLEX (RB/WR/TE), then SUPER_FLEX (QB/RB/WR/TE). Optimal for nested eligibility."""
    elig = {"QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
            "FLEX": {"RB", "WR", "TE"}, "WRRB_FLEX": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"},
            "SUPER_FLEX": {"QB", "RB", "WR", "TE"}}
    order = sorted([s for s in slots if s in elig], key=lambda s: len(elig[s]))
    avail = sorted(pids, key=lambda p: -pts.get(p, 0.0))
    used, lineup = set(), []
    for s in order:
        for p in avail:
            if p not in used and pos_of.get(p) in elig[s]:
                used.add(p); lineup.append((s, p, pts.get(p, 0.0))); break
        else:
            lineup.append((s, None, 0.0))
    return lineup


def ktc_values(sf, offline):
    h = fetch("https://keeptradecut.com/dynasty-rankings", os.path.join(CACHE, "ktc_dynasty_rankings.html"), 86400, offline, raw=True)
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        i = h.find("playersArray"); s = h.find("[", i)
        arr, _ = json.JSONDecoder().raw_decode(h[s:])
    else:
        arr = json.loads(m.group(1))
    key = "superflexValues" if sf else "oneQBValues"
    return {a["playerName"]: a[key]["value"] for a in arr}


def norm_name(n):
    n = re.sub(r"[^a-z ]", "", (n or "").lower().replace("-", " "))
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).strip().replace("  ", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default=None)
    ap.add_argument("--season", default="2026")
    ap.add_argument("--week", type=int, default=None, help="week being previewed; results use weeks < this")
    ap.add_argument("--offline", action="store_true", help="use cached files only")
    ap.add_argument("--no-screenshot", action="store_true", help="with --drafts: skip the PNG")
    ap.add_argument("--retro", action="store_true", help="back-dated ranking for a past --week (see docstring)")
    ap.add_argument("--drafts", action="store_true", help="also write drafts/ md + html mock (+ screenshot)")
    ap.add_argument("--blurbs", default=None, help="hand-written blurb override JSON (default data/power_rankings_blurbs/{season}_w{NN}.json)")
    a = ap.parse_args()
    today = dt.date.today()
    mgr_cfg = json.load(open(os.path.join(ROOT, "data", "managers.json")))
    sl = mgr_cfg.get("sleeper", {})
    L = a.league or sl.get("league_ids", {}).get(a.season)
    C = lambda name: os.path.join(CACHE, a.season, name)
    state = fetch(f"{API}/state/nfl", C("state.json"), 0, a.offline)
    week = a.week or int(state["display_week"])
    done = list(range(1, week))  # completed weeks
    league = fetch(f"{API}/league/{L}", C("league.json"), 0, a.offline)
    users = fetch(f"{API}/league/{L}/users", C("users.json"), 0, a.offline)
    rosters = fetch(f"{API}/league/{L}/rosters", C("rosters.json"), 0, a.offline)
    traded = fetch(f"{API}/league/{L}/traded_picks", C("traded_picks.json"), 0, a.offline)
    matchups = {w: fetch(f"{API}/league/{L}/matchups/{w}", C(f"matchups_{w}.json"), 0, a.offline) for w in done}
    if a.retro:
        if week >= int(state["display_week"]):
            sys.exit("--retro needs a --week before the current Sleeper week")
        retro_m = {m["roster_id"]: m for m in fetch(f"{API}/league/{L}/matchups/{week}", C(f"matchups_{week}.json"), 0, a.offline)}
    txs = []
    # transactions processed after week N-1's games (incl. Wednesday waivers) are filed under leg N-1, so a retro
    # ranking for week N includes legs < N; a live ranking includes everything through the current leg.
    for w in range(1, week if a.retro else week + 1):
        for t in fetch(f"{API}/league/{L}/transactions/{w}", C(f"transactions_{w}.json"), 0, a.offline):
            t["_week"] = w; txs.append(t)
    players = fetch(f"{API}/players/nfl", PLAYERS, 7 * 86400, a.offline)
    S, sc = league["settings"], league["scoring_settings"]
    slots = [s for s in league["roster_positions"] if s not in ("BN", "IR", "TAXI")]
    sf = "SUPER_FLEX" in slots or slots.count("QB") > 1
    ppr = sc.get("rec", 0)
    n_teams = int(S["num_teams"]); rounds = int(S.get("draft_rounds", 3))
    reg_end = int(S.get("playoff_week_start", 15)) - 1
    median_game = bool(S.get("league_average_match"))

    # ---- identities ----
    mgr_name = {m["id"]: m["name"] for m in mgr_cfg["managers"]}
    umap = sl.get("users", {})
    tn_over = sl.get("team_names", {}).get(a.season, {})
    U = {u["user_id"]: u for u in users}
    teams = {}
    for r in rosters:
        uid = r["owner_id"]; u = U.get(uid, {})
        mid = umap.get(uid, {}).get("manager")
        if not mid:
            gap(f"roster {r['roster_id']}: Sleeper user {uid} ({u.get('display_name')}) not in data/managers.json")
        teams[r["roster_id"]] = {
            "roster_id": r["roster_id"], "user_id": uid, "manager_id": mid,
            "owner": mgr_name.get(mid, u.get("display_name", "?")), "display_name": u.get("display_name"),
            "team": ((u.get("metadata") or {}).get("team_name") or tn_over.get(uid) or u.get("display_name") or "").strip(),
            "players": list(r.get("players") or []), "starters": list(r.get("starters") or []),
            "taxi": list(r.get("taxi") or []), "reserve": list(r.get("reserve") or []),
            "sleeper_record": f"{r['settings'].get('wins',0)}-{r['settings'].get('losses',0)}" + (f"-{r['settings']['ties']}" if r['settings'].get('ties') else ""),
        }
    if a.retro:
        # roster as actually carried in week N; undo pick trades from later legs
        for rid, T in teams.items():
            T["players"] = list(retro_m[rid].get("players") or [])
            T["taxi"] = [p for p in T["taxi"] if p in T["players"]]
        later = []
        for w in range(week, int(state["display_week"]) + 1):
            later += [t for t in fetch(f"{API}/league/{L}/transactions/{w}", C(f"transactions_{w}.json"), 0, a.offline)
                      if t.get("type") == "trade" and t.get("status") == "complete" and t.get("draft_picks")]
        for t in sorted(later, key=lambda t: -t.get("status_updated", 0)):
            for dp in t["draft_picks"]:
                for tp in traded:
                    if str(tp["season"]) == str(dp["season"]) and tp["round"] == dp["round"] and tp["roster_id"] == dp["roster_id"]:
                        tp["owner_id"] = dp["previous_owner_id"]
    rids = sorted(teams)
    pname = lambda p: (players.get(p, {}).get("full_name") or (p if not p.isdigit() else f"#{p}"))
    ppos = lambda p: players.get(p, {}).get("position") or ("DEF" if not p.isdigit() else None)

    # ---- actual results weeks 1..week-1 ----
    for t in teams.values():
        t.update(w=0, l=0, ti=0, pf=0.0, pa=0.0, ap_w=0, ap_l=0, ap_t=0, weekly=[], max_pf=0.0)
    for w, ms in matchups.items():
        pts = {m["roster_id"]: float(m.get("points") or 0) for m in ms}
        if not any(pts.values()):
            gap(f"week {w}: no points posted in matchups"); continue
        by_mid = {}
        for m in ms:
            by_mid.setdefault(m.get("matchup_id"), []).append(m["roster_id"])
        med = statistics.median(pts.values())
        for rid, p in pts.items():
            T = teams[rid]; T["pf"] += p; T["weekly"].append(round(p, 2))
            for o, q in pts.items():
                if o != rid:
                    T["ap_w"] += p > q; T["ap_l"] += p < q; T["ap_t"] += p == q
            if median_game:
                T["w"] += p > med; T["l"] += p < med; T["ti"] += p == med
        for rid, p in pts.items():
            teams[rid].setdefault("results", {})[w] = {"pts": p, "median": med, "rank": sorted(pts.values(), reverse=True).index(p) + 1}
        for m in ms:
            pp = m.get("players_points") or {}
            st = [x for x in (m.get("starters") or []) if x and x != "0"]
            if st:
                best = max(st, key=lambda x: pp.get(x, 0))
                teams[m["roster_id"]]["results"][w]["top"] = (pname(best), pp.get(best, 0))
        for mid_, pair in by_mid.items():
            if mid_ is None or len(pair) != 2:
                continue
            a_, b_ = pair
            teams[a_]["results"][w]["opp"] = b_; teams[b_]["results"][w]["opp"] = a_
            teams[a_]["pa"] += pts[b_]; teams[b_]["pa"] += pts[a_]
            if pts[a_] > pts[b_]: teams[a_]["w"] += 1; teams[b_]["l"] += 1
            elif pts[a_] < pts[b_]: teams[b_]["w"] += 1; teams[a_]["l"] += 1
            else: teams[a_]["ti"] += 1; teams[b_]["ti"] += 1
    for r in rosters:
        T = teams[r["roster_id"]]; s = r["settings"]
        T["max_pf"] = s.get("ppts", 0) + s.get("ppts_decimal", 0) / 100
        T["record"] = f"{T['w']}-{T['l']}" + (f"-{T['ti']}" if T["ti"] else "")
        if a.retro:
            T["max_pf"] = None
        elif T["record"] != T["sleeper_record"]:
            gap(f"{T['owner']}: computed record {T['record']} != Sleeper standings {T['sleeper_record']}")
        g = T["w"] + T["l"] + T["ti"]
        T["win_pct"] = (T["w"] + 0.5 * T["ti"]) / g if g else 0
        apg = T["ap_w"] + T["ap_l"] + T["ap_t"]
        T["allplay_pct"] = (T["ap_w"] + 0.5 * T["ap_t"]) / apg if apg else 0

    # ---- projections: this week + rest of regular season ----
    proj_pts = {}
    pos_q = "&".join(f"position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
    for w in range(week, reg_end + 1):
        try:
            rows = fetch(f"https://api.sleeper.app/projections/nfl/{a.season}/{w}?season_type=regular&{pos_q}",
                         C(f"proj_w{w}.json"), 6 * 3600, a.offline)
        except Exception as e:
            gap(f"projections week {w} unavailable ({e})"); continue
        d = {}
        for x in rows:
            st = x.get("stats") or {}
            if st:
                d[str(x["player_id"])] = round(score(st, sc), 2)
        if not d:
            gap(f"projections week {w} empty")
        proj_pts[w] = d
    for T in teams.values():
        pool = [p for p in T["players"] if p not in T["taxi"]]
        posmap = {p: ppos(p) for p in pool}
        T["proj_next"] = 0.0; T["proj_ros"] = 0.0; T["proj_weeks"] = 0
        for w, d in proj_pts.items():
            lu = optimal_lineup(pool, d, posmap, slots)
            tot = sum(x[2] for x in lu)
            T["proj_ros"] += tot; T["proj_weeks"] += 1
            if w == week:
                T["proj_next"] = tot
                T["proj_lineup"] = [(s, pname(p) if p else "(empty)", round(v, 1)) for s, p, v in lu]
        T["proj_ros_ppg"] = T["proj_ros"] / T["proj_weeks"] if T["proj_weeks"] else 0

    # ---- dynasty values ----
    fc_url = (f"https://api.fantasycalc.com/values/current?isDynasty=true&numQbs={2 if sf else 1}"
              f"&numTeams={n_teams}&ppr={ppr:g}")
    val, src = {}, None
    pick_val = {}
    try:
        fc = fetch(fc_url, os.path.join(CACHE, f"fantasycalc_{'sf' if sf else '1qb'}_{n_teams}_{ppr:g}.json"), 86400, a.offline)
        for x in fc:
            pl = x["player"]
            if pl.get("position") == "PICK":
                pick_val[pl["name"]] = x["value"]
            elif pl.get("sleeperId"):
                val[str(pl["sleeperId"])] = x["value"]
        src = f"FantasyCalc ({'superflex' if sf else '1QB'}, {n_teams} teams, PPR={ppr:g}) {fc_url}"
    except Exception as e:
        gap(f"FantasyCalc failed ({e}); falling back to KeepTradeCut")
    ktc = {}
    try:
        ktc = ktc_values(sf, a.offline)
    except Exception as e:
        gap(f"KeepTradeCut cross-check failed ({e})")
    ktc_n = {norm_name(k): v for k, v in ktc.items()}
    if not val and ktc:
        src = f"KeepTradeCut ({'superflex' if sf else '1QB'} values, name-matched)"
        for T in teams.values():
            for p in T["players"]:
                v = ktc_n.get(norm_name(pname(p)))
                if v: val[p] = v
        pick_val = {re.sub(r" Mid ", " ", k): v for k, v in ktc.items() if " Mid " in k}
    if not val:
        gap("no dynasty value source available; Dynasty score is 0 for everyone")

    # picks owned: own picks for next two drafts unless traded, plus acquired
    seasons = [str(int(a.season) + 1), str(int(a.season) + 2)]
    ordn = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
    owned = {rid: [] for rid in rids}
    for s_ in seasons:
        for rd in range(1, rounds + 1):
            for orig in rids:
                holder = orig
                for tp in traded:
                    if str(tp["season"]) == s_ and int(tp["round"]) == rd and tp["roster_id"] == orig:
                        holder = tp["owner_id"]
                owned[holder].append((s_, rd, orig))
    for rid in rids:
        T = teams[rid]
        T["picks"] = [{"season": s_, "round": rd, "from": orig, "from_owner": teams[orig]["owner"],
                       "value": pick_val.get(f"{s_} {ordn[rd]}", 0)} for s_, rd, orig in owned[rid]]
        T["pick_value"] = sum(p["value"] for p in T["picks"])
        pv = sorted(((val.get(p, 0), p) for p in T["players"]), reverse=True)
        T["player_value"] = sum(v for v, _ in pv)
        T["top_assets"] = [(pname(p), ppos(p), v, age_on(players.get(p, {}).get("birth_date") or "", today)) for v, p in pv[:5]]
        T["injuries"] = [] if a.retro else [(pname(p), players.get(p, {}).get("injury_status")) for v, p in pv[:12]
                                            if players.get(p, {}).get("injury_status") in BAD_INJ]
        T["dynasty_value"] = T["player_value"] + T["pick_value"]
        ages = [(val.get(p, 0), age_on(players.get(p, {}).get("birth_date") or "", today)) for p in T["players"]]
        ages = [(v, g) for v, g in ages if v and g]
        T["value_age"] = round(sum(v * g for v, g in ages) / sum(v for v, _ in ages), 1) if ages else None
        T["missing_value"] = [pname(p) for p in T["players"] if p not in val and ppos(p) in ("QB", "RB", "WR", "TE")]
        # KTC cross-check
        kv = sum(ktc_n.get(norm_name(pname(p)), 0) for p in T["players"])
        kp = sum(ktc.get(f"{p['season']} Mid {ordn[p['round']]}", 0) for p in T["picks"])
        T["ktc_value"] = kv + kp if ktc else None

    # ---- transactions ----
    for T in teams.values():
        T["moves"] = []
    for t in sorted(txs, key=lambda t: t.get("status_updated", 0)):
        if t.get("status") != "complete":
            continue
        adds, drops = t.get("adds") or {}, t.get("drops") or {}
        if t["type"] == "trade":
            for rid in t["roster_ids"]:
                got = [pname(p) for p, r in adds.items() if r == rid]
                gave = [pname(p) for p, r in drops.items() if r == rid]
                got += [f"{dp['season']} R{dp['round']} ({teams[dp['roster_id']]['owner'].split()[0]}'s)" for dp in t.get("draft_picks") or [] if dp["owner_id"] == rid]
                gave += [f"{dp['season']} R{dp['round']} ({teams[dp['roster_id']]['owner'].split()[0]}'s)" for dp in t.get("draft_picks") or [] if dp["previous_owner_id"] == rid]
                other = [teams[o]["owner"] for o in t["roster_ids"] if o != rid]
                teams[rid]["moves"].append({"week": t["_week"], "type": "trade", "with": other, "got": got, "gave": gave})
        else:
            for rid in t["roster_ids"]:
                teams[rid]["moves"].append({"week": t["_week"], "type": t["type"],
                                            "add": [pname(p) for p, r in adds.items() if r == rid],
                                            "add_skill": [pname(p) for p, r in adds.items() if r == rid and ppos(p) in ("QB", "RB", "WR", "TE")],
                                            "drop": [pname(p) for p, r in drops.items() if r == rid]})

    # ---- scores ----
    TT = [teams[r] for r in rids]
    zc = lambda k: zs([t[k] for t in TT])
    act = [W_ACT_PARTS["win_pct"] * a1 + W_ACT_PARTS["pf"] * a2 + W_ACT_PARTS["allplay"] * a3
           for a1, a2, a3 in zip(zc("win_pct"), zc("pf"), zc("allplay_pct"))]
    have_proj = any(t["proj_ros"] for t in TT)
    if have_proj:
        proj = [W_PROJ_PARTS["ros"] * a1 + W_PROJ_PARTS["next"] * a2 for a1, a2 in zip(zc("proj_ros"), zc("proj_next"))]
        wn = [W_ACTUAL * x + W_PROJ * y for x, y in zip(act, proj)]
    else:
        gap("no projections; Win-Now uses actual results only"); proj = [0] * len(TT); wn = act
    dyn = zc("dynasty_value") if val else [0] * len(TT)
    ov = [W_WINNOW * x + W_DYNASTY * y for x, y in zip(wn, dyn)]
    for t, a1, p1, w1, d1, o1 in zip(TT, act, proj, wn, dyn, ov):
        t.update(actual_z=round(a1, 3), proj_z=round(p1, 3), winnow_z=round(w1, 3), dynasty_z=round(d1, 3), overall_z=round(o1, 3))
    for k, rk in (("winnow_z", "winnow_rank"), ("dynasty_z", "dynasty_rank"), ("overall_z", "rank"),
                  ("proj_ros", "proj_rank"), ("pf", "pf_rank"), ("ktc_value", "ktc_rank")):
        if all(t.get(k) is not None for t in TT):
            for t, r_ in zip(TT, ranks([t[k] for t in TT])):
                t[rk] = r_
    playoff = int(S.get("playoff_teams", 6))
    # standings seed: win% then PF (Sleeper's default tiebreak)
    for i, t in enumerate(sorted(TT, key=lambda t: (-t["win_pct"], -t["pf"])), 1):
        t["seed"] = i
    for t in TT:
        # status rule: Contender = top-4 Win-Now; Rebuild = bottom-3 Win-Now AND outside the playoff line; else Middle
        if t["winnow_rank"] <= 4:
            t["status"] = "Contender"
        elif t["winnow_rank"] >= n_teams - 2 and t["seed"] > playoff:
            t["status"] = "Rebuild"
        else:
            t["status"] = "Middle"

    # ---- blurbs ----
    prev = None
    pp_ = os.path.join(OUT, f"{a.season}_w{week-1:02d}.json")
    if os.path.exists(pp_):
        prev = {t["roster_id"]: t for t in json.load(open(pp_))["teams"]}
    for t in TT:
        t["prev_rank"] = prev[t["roster_id"]]["rank"] if prev and t["roster_id"] in prev else None
    bpath = a.blurbs or os.path.join(BLURBS, f"{a.season}_w{week:02d}.json")
    blurbs = json.load(open(bpath)) if os.path.exists(bpath) else {}
    for t in TT:
        b = blurbs.get(t["manager_id"] or "") or blurbs.get(str(t["roster_id"]))
        t["blurb_source"] = None if a.retro else "hand-written" if b else "auto"
        t["blurb"] = None if a.retro else (b or auto_blurb(t, teams, week, median_game))

    TT.sort(key=lambda t: t["rank"])

    meta = {
        "league": league["name"], "league_id": L, "season": a.season, "week": week, "completed_weeks": done,
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "settings": {
            "lineup": slots, "superflex": sf, "ppr": ppr, "teams": n_teams, "median_game": median_game,
            "waivers": {0: "traditional/rolling", 1: "reverse standings", 2: "FAAB"}.get(S.get("waiver_type"), S.get("waiver_type")),
            "rookie_draft_rounds": rounds, "playoff_teams": playoff, "reg_season_end_week": reg_end},
        "weights": {"overall": {"win_now": W_WINNOW, "dynasty": W_DYNASTY}, "win_now": {"actual": W_ACTUAL, "projected": W_PROJ},
                    "actual_parts": W_ACT_PARTS, "projected_parts": W_PROJ_PARTS},
        "sources": {"values": src, "values_crosscheck": "KeepTradeCut dynasty-rankings (playersArray / ktc-players JSON, name-matched)" if ktc else None,
                    "projections": f"Sleeper weekly projections weeks {min(proj_pts) if proj_pts else '-'}-{max(proj_pts) if proj_pts else '-'}, re-scored with league scoring_settings",
                    "pick_values": "FantasyCalc generic '<year> <round>' pick values" if pick_val and src and src.startswith("FantasyCalc") else "KeepTradeCut 'Mid' pick values"},
        "gaps": GAP,
        "retro": bool(a.retro),
        "retro_note": (f"Retro ranking computed {today.isoformat()}: results through Week {week-1}, rosters as carried in Week {week}, "
                       f"Sleeper weekly projections for Weeks {week}-{reg_end}, but TODAY's dynasty values.") if a.retro else None,
    }
    keep = ["rank", "prev_rank", "roster_id", "owner", "team", "display_name", "record", "w", "l", "ti", "pf", "pa", "max_pf", "weekly", "ap_w", "ap_l",
            "win_pct", "allplay_pct", "proj_next", "proj_ros", "proj_ros_ppg", "proj_lineup", "player_value", "pick_value", "dynasty_value",
            "ktc_value", "ktc_rank", "value_age", "top_assets", "injuries", "picks", "moves", "missing_value", "actual_z", "proj_z", "winnow_z", "dynasty_z",
            "overall_z", "seed", "manager_id", "winnow_rank", "dynasty_rank", "pf_rank", "proj_rank", "status", "blurb", "blurb_source"]
    doc = {"meta": meta, "teams": [{k: t.get(k) for k in keep} for t in TT]}
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{a.season}_w{week:02d}.json")
    with open(out, "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print("wrote", out)
    if not a.drafts:
        return
    out_dir = os.path.join(ROOT, "drafts"); os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"power_rankings_w{week}")
    json.dump(doc, open(base + ".json", "w"), indent=1)
    open(base + ".md", "w").write(render_md(meta, TT))
    open(base + ".html", "w").write(render_html(meta, TT))
    print("wrote", base + ".md/.html/.json")
    if not a.no_screenshot:
        shot = os.path.join(ROOT, "screenshots", f"power_rankings_w{week}.png")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
                pg.goto("file://" + base + ".html", wait_until="load"); pg.screenshot(path=shot, full_page=True); b.close()
            print("wrote", shot)
        except Exception as e:
            gap(f"screenshot failed: {e}")


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def auto_blurb(t, teams, week, median_game):
    """Factual 1-3 sentence blurb built only from fetched data."""
    def first(rid):
        fn = teams[rid]["owner"].split()
        dup = sum(1 for x in teams.values() if x["owner"].split()[0] == fn[0]) > 1
        return f"{fn[0]} {fn[-1][0]}." if dup and len(fn) > 1 else fn[0]
    lw = week - 1
    parts = []
    r = (t.get("results") or {}).get(lw)
    if r:
        bits = []
        if "opp" in r:
            o = teams[r["opp"]]["results"][lw]["pts"]
            bits.append(("beat" if r["pts"] > o else "lost to" if r["pts"] < o else "tied") + f" {first(r['opp'])} ({r['pts']:.2f}-{o:.2f})")
        if median_game:
            bits.append("cleared the median" if r["pts"] > r["median"] else "missed the median")
        lead = f"Week {lw}: " + " and ".join(bits) + ({1: ", the week's top score", 2: ", the week's 2nd-best score", len(teams): ", the week's lowest score",
                                                       len(teams) - 1: ", the week's 2nd-lowest score"}.get(r.get("rank"), ""))
        if r.get("top") and r["top"][1] > 0:
            lead += f", led by {r['top'][0]} ({r['top'][1]:.1f})"
        parts.append(lead + ".")
    mv = ""
    if t.get("prev_rank"):
        d = t["prev_rank"] - t["rank"]
        mv = f"Up {d} from #{t['prev_rank']}. " if d > 0 else f"Down {-d} from #{t['prev_rank']}. " if d < 0 else f"Holds at #{t['rank']}. "
    parts.append(f"{mv}Now {t['record']} with {t['pf']:.1f} PF (#{t['pf_rank']}); Win-Now #{t['winnow_rank']}, Dynasty #{t['dynasty_rank']}.")
    recent = [m for m in t["moves"] if m["week"] >= lw]
    trades = [m for m in recent if m["type"] == "trade"]
    if trades:
        m = trades[-1]
        parts.append(f"Traded {', '.join(m['gave']) or 'nothing'} to {', '.join(x.split()[0] for x in m['with'])} for {', '.join(m['got']) or 'nothing'}.")
    adds = [(m, x) for m in recent if m["type"] != "trade" for x in m["add"]]
    skill = [(m, x) for m, x in adds if x in m.get("add_skill", [])]
    if skill:
        m, x = skill[-1]
        how = "claimed" if m["type"] == "waiver" else "added"
        parts.append(f"Latest pickup: {how} {x}" + (f" (dropped {', '.join(m['drop'])})" if m["drop"] else "") + ".")
    if t.get("injuries"):
        parts.append("Injury watch: " + ", ".join(f"{n} ({s})" for n, s in t["injuries"][:3]) + ".")
    return " ".join(parts)


def fmt_moves(t, limit=4):
    out = []
    for m in t["moves"]:
        if m["type"] == "trade":
            out.append(f"W{m['week']} trade w/ {', '.join(m['with'])}: got {', '.join(m['got']) or '-'}; gave {', '.join(m['gave']) or '-'}")
    adds = [x for m in t["moves"] if m["type"] != "trade" for x in m["add"]]
    if adds:
        out.append(f"Adds ({len(adds)}): " + ", ".join(adds[-limit:]) + (" ..." if len(adds) > limit else ""))
    return out


def render_md(meta, TT):
    W = meta["weights"]; s = meta["settings"]
    L = [f"# LOEG Dynasty Power Rankings: Week {meta['week']} (DRAFT)", "",
         f"_{meta['league']} · {meta['season']} · results through Week {max(meta['completed_weeks']) if meta['completed_weeks'] else 0} · generated {meta['generated']} ET · not published_", "",
         "| # | Owner | Team | Record | PF | Win-Now | Dynasty | Status |", "|---|---|---|---|---|---|---|---|"]
    for t in TT:
        L.append(f"| {t['rank']} | {t['owner']} | {t['team']} | {t['record']} | {t['pf']:.1f} | {t['winnow_rank']} | {t['dynasty_rank']} | {t['status']} |")
    L += ["", "## The Rankings", ""]
    for t in TT:
        L += [f"### {t['rank']}. {t['team']} ({t['owner']}): {t['record']}", "",
              f"**Win-Now #{t['winnow_rank']} · Dynasty #{t['dynasty_rank']} · {t['status']}**", "", t["blurb"], "",
              f"- Standings seed #{t['seed']}; PF {t['pf']:.2f} (#{t['pf_rank']}), PA {t['pa']:.2f}, all-play {t['ap_w']}-{t['ap_l']}, weekly {', '.join(f'{x:.2f}' for x in t['weekly'])}",
              f"- Projected optimal lineup: W{meta['week']} {t['proj_next']:.1f} pts; ROS {t['proj_ros_ppg']:.1f}/wk (#{t['proj_rank']})",
              f"- Dynasty value {t['dynasty_value']:,} (players {t['player_value']:,} + picks {t['pick_value']:,}); value-weighted age {t['value_age']}"
              + (f"; KTC cross-check #{t['ktc_rank']}" if t.get('ktc_rank') else ""),
              "- Top assets: " + ", ".join(f"{n} ({p}, {g}) {v:,}" for n, p, v, g in t["top_assets"]),
              f"- Picks ({len(t['picks'])}): " + ", ".join(f"{p['season']} R{p['round']}" + ("" if p['from_owner'] == t['owner'] else f" (from {p['from_owner']})") for p in t["picks"])]
        L += [f"- {m}" for m in fmt_moves(t)]
        L.append("")
    L += ["## Method & Weights", "",
          f"- **Overall** = {W['overall']['win_now']:.0%} Win-Now + {W['overall']['dynasty']:.0%} Dynasty (z-scores across the 10 teams).",
          f"- **Win-Now** = {W['win_now']['actual']:.0%} actual (win% incl. median game, points for, all-play win%, equal thirds) + {W['win_now']['projected']:.0%} projected "
          f"({W['projected_parts']['ros']:.0%} rest-of-regular-season optimal lineup through Week {s['reg_season_end_week']}, {W['projected_parts']['next']:.0%} Week {meta['week']} optimal lineup).",
          f"- Lineup: {', '.join(s['lineup'])}; superflex={s['superflex']}, PPR={s['ppr']:g}, median game={s['median_game']}. Taxi players excluded from projected lineups.",
          "- **Dynasty** = sum of every rostered player's dynasty value + the team's 2027/2028 rookie picks (own minus traded plus acquired).",
          f"- **Status**: Contender = top-4 Win-Now; Rebuild = bottom-3 Win-Now and outside the top-{s['playoff_teams']} playoff line (standings by win%, then PF); else Middle.", "",
          "## Sources", ""] + [f"- {k}: {v}" for k, v in meta["sources"].items() if v] + ["", "## Data gaps", ""] + ([f"- {g}" for g in meta["gaps"]] or ["- none detected"])
    return "\n".join(L) + "\n"


def render_html(meta, TT):
    css = open(os.path.join(ROOT, "src", "static", "style.css")).read()
    e = html.escape
    pill = {"Contender": "green", "Middle": "warn", "Rebuild": "red"}
    cards = []
    for t in TT:
        top = ", ".join(e(n) for n, *_ in t["top_assets"][:3])
        cards.append(f"""<article class="pr card{' first' if t['rank']==1 else ''}">
<div class="pr-head"><div class="pr-rank">{t['rank']}</div><div class="pr-id"><div class="pr-team">{e(t['team'])}</div>
<div class="pr-owner muted small">{e(t['owner'])} · <b class="rec">{t['record']}</b> · <span style="white-space:nowrap">{t['pf']:.1f} PF</span></div></div>
<span class="pill {pill[t['status']]}">{t['status']}</span></div>
<div class="pr-ranks"><span><span class="label">Win-Now</span> <b>#{t['winnow_rank']}</b></span><span><span class="label">Dynasty</span> <b>#{t['dynasty_rank']}</b></span><span><span class="label">Proj W{meta['week']}</span> <b>{t['proj_next']:.0f}</b></span></div>
<p class="pr-blurb">{e(t['blurb'])}</p>
<div class="muted small">Core: {top} · value age {t['value_age']}</div></article>""")
    W = meta["weights"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><title>Power Rankings Week {meta['week']} (DRAFT) · LOEG</title>
<style>{css}
.pr-wrap{{max-width:720px}}
.draft-flag{{display:inline-block;margin-top:8px;padding:2px 10px;border:1px dashed #8a7020;border-radius:999px;color:#ffe08a;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase}}
.pr{{margin:12px 0;padding:14px}}
.pr.first{{border-color:#7a6020;background:linear-gradient(180deg,#2a2412,#171a24)}}
.pr-head{{display:flex;gap:12px;align-items:center}}
.pr-rank{{flex:0 0 44px;height:44px;border-radius:12px;display:grid;place-items:center;font:700 1.45rem Georgia,serif;color:var(--gold);background:#2b2412;border:1px solid #6b5520}}
.pr-id{{flex:1;min-width:0}}
.pr-team{{font:700 1.08rem Georgia,serif;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.pr-owner .rec{{color:var(--ink)}}
.pr-ranks{{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0 4px;font-size:.9rem}}
.pr-ranks b{{color:var(--gold2)}}
.pr-blurb{{margin:.5em 0;font-size:.97rem}}
.method{{font-size:.84rem}}
</style></head><body>
<header class="site"><div class="wrap"><a class="brand" href="#">🎩 LOEG <span>History Book</span></a></div></header>
<main class="wrap pr-wrap">
<section class="hero" style="padding:26px 0 6px"><div class="kicker">{meta['season']} Dynasty · Week {meta['week']}</div>
<h1>Power Rankings</h1><p class="lead" style="font-size:.98rem">Through Week {max(meta['completed_weeks']) if meta['completed_weeks'] else 0}. Half how you're playing now, half what your roster's worth long-term.</p>
<span class="draft-flag">Draft · not published</span></section>
{''.join(cards)}
<section class="card method muted"><b style="color:var(--ink)">How this works</b><br>
Overall = {W['overall']['win_now']:.0%} Win-Now + {W['overall']['dynasty']:.0%} Dynasty. Win-Now = {W['win_now']['actual']:.0%} results (record incl. median game, PF, all-play) + {W['win_now']['projected']:.0%} projected optimal lineup (rest of season + this week, Sleeper projections in league scoring).
Dynasty = roster + 2027/28 pick value from {e((meta['sources']['values'] or 'n/a').split(' https')[0])}. Generated {meta['generated']} ET.</section>
</main>
<footer class="site"><div class="wrap">The League of Extraordinary Gentlemen · Draft mock, not part of the published site.</div></footer>
</body></html>"""


if __name__ == "__main__":
    main()
