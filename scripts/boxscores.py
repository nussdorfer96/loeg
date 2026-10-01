"""Box score data for every head-to-head game (ESPN weekly archive + Sleeper matchups)."""
import os, collections
from common import *

NFL = {0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC",
       13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
       25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
ESPN_SLOT = {0: "QB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE", 7: "OP", 16: "D/ST", 17: "K", 23: "FLEX"}
ESPN_ELIG = {0: {"QB"}, 2: {"RB"}, 3: {"RB", "WR"}, 4: {"WR"}, 5: {"WR", "TE"}, 6: {"TE"}, 7: {"QB", "RB", "WR", "TE"},
             16: {"D/ST"}, 17: {"K"}, 23: {"RB", "WR", "TE"}}
SLP_ELIG = {"QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"}, "FLEX": {"RB", "WR", "TE"},
            "SUPER_FLEX": {"QB", "RB", "WR", "TE"}, "REC_FLEX": {"WR", "TE"}, "WRRB_FLEX": {"WR", "RB"}, "IDP_FLEX": set()}
SLP_LABEL = {"SUPER_FLEX": "SF", "REC_FLEX": "W/T", "WRRB_FLEX": "W/R", "DEF": "DEF"}
ORDER = ["QB", "RB", "RB/WR", "WR", "WR/TE", "TE", "FLEX", "W/R", "W/T", "OP", "SF", "D/ST", "DEF", "K"]


def slug(y, wk, a, b):
    x, z = sorted([a, b])
    return f"box/{y}/w{wk:02d}-{x}-vs-{z}.html"


def optimal(pool, slots):
    """pool: [(pts, pos)], slots: [eligible-position sets]. Fill the most restrictive slots first (optimal for nested slot sets)."""
    left = sorted(pool, key=lambda x: -x[0]); total = 0.0
    for el in sorted(slots, key=len):
        i = next((k for k, p in enumerate(left) if p[1] in el), None)
        if i is not None: total += left.pop(i)[0]
    return round(total, 2)


def side_espn(S, wk, tid):
    ent = (S.get("lineupsByWeek") or {}).get(str(wk), {}).get(str(tid))
    if not ent: return None
    teams = (S.get("nflTeamByWeek") or {}).get(str(wk), {}); proj = (S.get("projByWeek") or {}).get(str(wk), {}).get(str(tid))
    st, be, pool = [], [], []
    for pid, slot, pts in ent:
        p = S["players"].get(str(pid), {"name": f"Player {pid}", "pos": "?"})
        row = {"name": p["name"], "pos": p["pos"], "nfl": NFL.get(teams.get(str(pid)) or p.get("proTeamId"), ""), "pts": pts or 0,
               "proj": (proj or {}).get(str(pid))}
        if slot in (20, 21, 24, 25):
            row["slot"] = "IR" if slot == 21 else "BE"; be.append(row)
        else:
            row["slot"] = ESPN_SLOT.get(slot, p["pos"]); st.append(row)
        if slot != 21: pool.append((pts or 0, p["pos"]))
    slots = [ESPN_ELIG[int(k)] for k, n in S["rosterSlots"].items() if int(k) in ESPN_ELIG for _ in range(n)]
    return finish(st, be, optimal(pool, slots), proj is not None)


def side_sleeper(S, wk, tid, pdb):
    ent = (S.get("lineupsByWeek") or {}).get(str(wk), {}).get(str(tid))
    if not ent: return None
    order = (S.get("startersByWeek") or {}).get(str(wk), {}).get(str(tid), [])
    pos_slots = [p for p in S["rosterPositions"] if p not in ("BN", "TAXI", "IR")]
    pts = {str(pid): v or 0 for pid, sl, v in ent}; kind = {str(pid): sl for pid, sl, v in ent}
    def info(pid):
        p = S["players"].get(pid) or {}
        d = pdb.get(pid) or {}
        name = p.get("name") or (f"{d.get('first_name', '')} {d.get('last_name', '')}".strip() if d else "") or pid
        return name, p.get("pos") or d.get("position") or ("DEF" if pid.isalpha() else "?"), p.get("team") or d.get("team") or (pid if pid.isalpha() else "")
    st, be, pool = [], [], []
    for i, pid in enumerate(order):
        lab = pos_slots[i] if i < len(pos_slots) else "FLEX"
        if not pid or pid == "0":
            st.append({"slot": SLP_LABEL.get(lab, lab), "name": "(empty)", "pos": "", "nfl": "", "pts": 0, "proj": None}); continue
        n, pos, tm = info(pid)
        st.append({"slot": SLP_LABEL.get(lab, lab), "name": n, "pos": pos, "nfl": tm, "pts": pts.get(pid, 0), "proj": None})
    for pid, sl in kind.items():
        n, pos, tm = info(pid)
        if sl != "ST":
            be.append({"slot": "TAXI" if sl == "TX" else ("IR" if sl == "IR" else "BE"), "name": n, "pos": pos, "nfl": tm, "pts": pts[pid], "proj": None})
        if sl not in ("TX", "IR"): pool.append((pts[pid], pos))
    return finish(st, be, optimal(pool, [SLP_ELIG.get(p, set()) for p in pos_slots]), False, keep_order=True)


def finish(st, be, opt, has_proj, keep_order=False):
    if not keep_order: st.sort(key=lambda r: ORDER.index(r["slot"]) if r["slot"] in ORDER else 99)
    be.sort(key=lambda r: (r["slot"] != "BE", -r["pts"]))
    total = round(sum(r["pts"] for r in st), 2)
    top = max(st, key=lambda r: r["pts"])["name"] if st else None
    projt = round(sum(r["proj"] or 0 for r in st), 2) if has_proj else None
    return {"starters": st, "bench": be, "startTotal": total, "benchTotal": round(sum(r["pts"] for r in be if r["slot"] == "BE"), 2),
            "optimal": max(opt, total), "efficiency": round(100 * total / opt, 1) if opt else None, "top": top, "proj": projt}


def round_name(S, g):
    if g["kind"] == "regular": return "Regular season"
    if g["kind"] == "consolation": return "Consolation"
    pw = sorted(set(x["week"] for x in S["games"] if x["kind"] == "playoff"))
    i = pw.index(g["week"]); n = len(pw)
    return "Championship" if g.get("isFinal") or i == n - 1 else "Semifinal" if i == n - 2 else "Quarterfinal" if i == n - 3 else f"Playoff round {i + 1}"


def build(seasons, lore_entries):
    pdb = load(os.path.join(RAW, "sleeper", "players_nfl.json"), {}) or {}
    boxes = []
    for y in sorted(seasons):
        S = seasons[y]
        done = S.get("completedWeeks") if S["platform"] == "Sleeper" else S.get("lastWeek")
        tname = {T["teamId"]: T["teamName"] for T in S["teams"]}
        for g in S["games"]:
            if not g.get("away") or g["week"] > (done or 99) or not (g["home"]["score"] or g["away"]["score"]): continue
            sides = []
            for k in ("home", "away"):
                t = g[k]
                lu = side_espn(S, g["week"], t["teamId"]) if S["platform"] == "ESPN" else side_sleeper(S, g["week"], t["teamId"], pdb)
                sides.append({"manager": t["manager"], "team": tname.get(t["teamId"], ""), "score": t["score"], "won": g["winner"] == k, "lineup": lu})
            sides.sort(key=lambda s: not s["won"])
            ms = {s["manager"] for s in sides}
            lore = [{"id": e["id"], "title": e["title"]} for e in lore_entries
                    if e.get("season") == y and e.get("week") == g["week"] and ms <= set(e.get("managers") or [])]
            boxes.append({"year": y, "week": g["week"], "kind": g["kind"], "round": round_name(S, g), "final": bool(g.get("isFinal")),
                          "platform": S["platform"], "sides": sides, "margin": round(abs(g["home"]["score"] - g["away"]["score"]), 2),
                          "url": slug(y, g["week"], g["home"]["manager"], g["away"]["manager"]), "lore": lore})
    # prev/next game for each manager
    bym = collections.defaultdict(list)
    for b in boxes:
        for s in b["sides"]: bym[s["manager"]].append(b)
    for m, lst in bym.items():
        lst.sort(key=lambda b: (b["year"], b["week"]))
        for i, b in enumerate(lst):
            b.setdefault("nav", {})[m] = {"prev": lst[i - 1]["url"] if i else None, "next": lst[i + 1]["url"] if i + 1 < len(lst) else None,
                                          "prevLabel": f"{lst[i-1]['year']} wk {lst[i-1]['week']}" if i else "", "nextLabel": f"{lst[i+1]['year']} wk {lst[i+1]['week']}" if i + 1 < len(lst) else ""}
    return boxes
