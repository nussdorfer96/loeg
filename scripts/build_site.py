"""Render the static site from data/generated/*.json into dist/ (pure static HTML/CSS/JS)."""
import os, shutil, datetime, collections, re, html
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from common import *
import boxscores

SRC = os.path.join(ROOT, "src"); DIST = os.path.join(ROOT, "dist")


PR_COLORS = ["#e8b84a", "#6aa8ff", "#4cc38a", "#ef6b6b", "#c58cff", "#ff9f43", "#3fd0d4", "#f368e0", "#a3cb38", "#b0b8cc"]


def pr_chart(hist):
    """Phone-friendly SVG bump chart: rank 1 on top, one line per team, labels at the right end, current week highlighted."""
    weeks = [d["meta"]["week"] for d in hist]
    retro = {d["meta"]["week"] for d in hist if d["meta"].get("retro")}
    cur = hist[-1]
    n = len(cur["teams"])
    W, H, L0, R0, T0, B0 = 360, 300, 26, 92, 14, 34
    xs = {w: L0 + (W - L0 - R0) * (i / max(1, len(weeks) - 1)) for i, w in enumerate(weeks)}
    y = lambda r: T0 + (H - T0 - B0) * ((r - 1) / max(1, n - 1))
    firsts = collections.Counter(t["owner"].split()[0] for t in cur["teams"])
    def short(o):
        f = o.split()
        return f"{f[0]} {f[-1][0]}." if firsts[f[0]] > 1 or len(f[0]) > 8 else f[0]
    color = {t["roster_id"]: PR_COLORS[i % len(PR_COLORS)] for i, t in enumerate(sorted(cur["teams"], key=lambda t: t["roster_id"]))}
    out = [f'<svg class="pr-chart" viewBox="0 0 {W} {H}" role="img" aria-label="Power ranking by week, rank 1 at top">']
    cx = xs[weeks[-1]]
    out.append(f'<rect x="{cx-13:.1f}" y="{T0-10}" width="26" height="{H-T0-B0+20}" rx="8" class="pr-cur"/>')
    for r in range(1, n + 1):
        out.append(f'<line x1="{L0}" x2="{W-R0+6}" y1="{y(r):.1f}" y2="{y(r):.1f}" class="pr-grid"/><text x="{L0-8}" y="{y(r)+3.5:.1f}" class="pr-ax" text-anchor="end">{r}</text>')
    for w in weeks:
        out.append(f'<text x="{xs[w]:.1f}" y="{H-B0+18}" class="pr-ax{" pr-axcur" if w == weeks[-1] else ""}" text-anchor="middle">W{w}{"*" if w in retro else ""}</text>')
    for t in sorted(cur["teams"], key=lambda t: -t["rank"]):
        rid = t["roster_id"]; c = color[rid]
        pts = [(w, next((x["rank"] for x in d["teams"] if x["roster_id"] == rid), None)) for w, d in zip(weeks, hist)]
        pts = [(w, r) for w, r in pts if r]
        g = [f'<g class="pr-line" style="--c:{c}"><title>{escape(t["owner"])}: ' + " → ".join(f"W{w} #{r}" for w, r in pts) + '</title>']
        for (w1, r1), (w2, r2) in zip(pts, pts[1:]):
            dash = ' stroke-dasharray="4 4"' if (w1 in retro or w2 in retro) and w2 != weeks[-1] else ""
            g.append(f'<line x1="{xs[w1]:.1f}" y1="{y(r1):.1f}" x2="{xs[w2]:.1f}" y2="{y(r2):.1f}"{dash}/>')
        for w, r in pts:
            g.append(f'<circle cx="{xs[w]:.1f}" cy="{y(r):.1f}" r="{5 if w == weeks[-1] else 3.2}"/>')
        g.append(f'<text x="{cx+12:.1f}" y="{y(t["rank"])+4:.1f}" class="pr-lab">{t["rank"]} {escape(short(t["owner"]))}</text></g>')
        out.append("".join(g))
    out.append("</svg>")
    return Markup("".join(out))


def main():
    L = load(os.path.join(GEN, "league.json"))
    seasons = {int(y): load(os.path.join(GEN, "seasons", f"{y}.json")) for y in L["years"]}
    L["seasonMeta"] = {str(k): v for k, v in L["seasonMeta"].items()}
    MG = {m["id"]: m for m in load(os.path.join(DATA, "managers.json"))["managers"]}
    F = load(os.path.join(GEN, "features.json"))
    SITE = load(os.path.join(DATA, "site.json"), {"title": "LOEG History Book", "description": "", "url": ""})
    TR = {t["id"]: t for t in F["trades"]}
    BOXES = boxscores.build(seasons, L["lore"])
    BOXMAP = {(x["year"], x["week"], frozenset(s["manager"] for s in x["sides"])): x for x in BOXES}
    GLOG = collections.defaultdict(list)
    for x in BOXES:
        for s in x["sides"]: GLOG[s["manager"]].append(x)
    def box_of(y, wk, a, c): return BOXMAP.get((int(y), int(wk), frozenset([a, c])))
    def bx(y, wk, a, c):
        x = box_of(y, wk, a, c)
        return x["url"] if x else ""
    BYMW = {(x["year"], x["week"], s["manager"]): x for x in BOXES for s in x["sides"]}
    def box_for(y, wk, m):
        x = BYMW.get((int(y), int(wk), m))
        return x["url"] if x else ""
    def game_log(mid):
        out = collections.OrderedDict()
        for x in sorted(GLOG.get(mid, []), key=lambda x: (x["year"], x["week"])): out.setdefault(x["year"], []).append(x)
        return out
    PALETTE = ["#e8b84a", "#4ea1ff", "#ff6b6b", "#5bd18b", "#c38bff", "#ff9f43", "#3dd6d0", "#ff7ac6", "#a3b18a", "#f4f1de", "#8d99ae", "#b5838d"]

    def race_svg(rc):
        if not rc: return ""
        W, H, pl, pr, pt, pb = 360, 230, 26, 8, 10, 22
        wk = rc["weeks"]; n = len(wk)
        vals = [v for s in rc["series"].values() for v in s]
        lo, hi = min(vals + [0]), max(vals + [0])
        X = lambda i: pl + (W - pl - pr) * (i / max(1, n - 1))
        Y = lambda v: pt + (H - pt - pb) * ((hi - v) / max(1, hi - lo))
        out = [f'<svg viewBox="0 0 {W} {H}" class="race-svg" role="img" aria-label="Games over .500 by week">']
        for v in range(lo, hi + 1):
            if v % 2 == 0 or hi - lo <= 8:
                out.append(f'<line x1="{pl}" x2="{W-pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid{" zero" if v == 0 else ""}"/><text x="{pl-4}" y="{Y(v)+3:.1f}" class="ax" text-anchor="end">{"+" if v > 0 else ""}{v}</text>')
        for i, w in enumerate(wk):
            if n <= 10 or i % 2 == 0 or i == n - 1:
                out.append(f'<text x="{X(i):.1f}" y="{H-6}" class="ax" text-anchor="middle">{w}</text>')
        hl = {}
        if rc.get("collapse"): hl[rc["collapse"]["manager"]] = "collapse"
        if rc.get("surge"): hl[rc["surge"]["manager"]] = "surge"
        order = sorted(rc["series"], key=lambda m: rc["series"][m][-1])
        for k, m in enumerate(order):
            c = PALETTE[list(rc["series"]).index(m) % len(PALETTE)]
            pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(rc["series"][m]))
            out.append(f'<polyline points="{pts}" class="ln {hl.get(m, "")}" data-m="{m}" style="stroke:{c}"/>')
            out.append(f'<circle cx="{X(n-1):.1f}" cy="{Y(rc["series"][m][-1]):.1f}" r="2.6" class="dot" data-m="{m}" style="fill:{c}"/>')
        out.append("</svg>")
        leg = "".join(f'<button type="button" data-m="{m}" class="{hl.get(m, "")}"><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{escape(mname(m).split(" ")[0] if sum(1 for x in rc["series"] if mname(x).split(" ")[0] == mname(m).split(" ")[0]) == 1 else mname(m))}</button>' for i, m in enumerate(rc["series"]))
        return Markup(f'<div class="race">{"".join(out)}<div class="legend">{leg}</div></div>')

    def grade_cls(g): return {"A+": "ga", "A": "ga", "B": "gb", "C": "gc", "D": "gd", "F": "gf"}.get(g, "gi")
    def pair_id(a, b): return "--".join(sorted([a, b]))
    def riv(a, b): return F["rivalries"].get(pair_id(a, b))
    def sgn(x): return ("+" if x > 0 else "") + f(x)
    env = Environment(loader=FileSystemLoader(os.path.join(SRC, "templates")), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)

    def mname(mid): return MG.get(mid, {}).get("name", mid or "?")
    def f(x):
        if x is None: return "-"
        if isinstance(x, (int,)) and not isinstance(x, bool): return f"{x:,}"
        s = f"{float(x):,.2f}"
        return s.rstrip("0").rstrip(".") if "." in s else s
    def ordinal(n):
        if not n: return "-"
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
    def team_name(S, mid):
        return next((T["teamName"] for T in S["teams"] if T["manager"] == mid), "")
    def team_name_id(S, tid):
        return next((T["teamName"] for T in S["teams"] if T["teamId"] == tid), "")
    def seed_of(S, tid):
        return next((T.get("seed") for T in S["teams"] if T["teamId"] == tid), "")
    def playoff_rounds(S):
        by = collections.defaultdict(list)
        for g in S["games"]:
            if g["kind"] == "playoff": by[g["week"]].append(g)
        for wk in by: by[wk].sort(key=lambda g: (g.get("bye", False) is False, seed_of(S, g["home"]["teamId"]) or 99))
        return sorted(by.items())
    def weeks(S):
        by = collections.defaultdict(list)
        for g in S["games"]:
            if g.get("away") and (g["home"]["score"] or g["away"]["score"]): by[g["week"]].append(g)
        for wk in by: by[wk].sort(key=lambda g: {"playoff": 0, "regular": 0, "consolation": 1}[g["kind"]])
        return sorted(by.items())
    def draft_board(S, D=None):
        picks = (D or {}).get("picks") or S.get("draft") or []
        r1 = sorted([p for p in picks if p["round"] == 1], key=lambda p: p["overall"])
        cols = [p["teamId"] for p in r1]
        mgr = {T["teamId"]: T["manager"] for T in S["teams"]}
        grid = {(p["round"], p["teamId"]): p for p in picks}
        return {"cols": cols, "mgr": mgr, "grid": grid, "rounds": sorted(set(p["round"] for p in picks))}
    def top_players(S, n=15):
        out = []
        drafted = {str(p["playerId"]): p for p in S.get("draft") or []}
        owner = {}
        for tid, lst in (S.get("rosters") or {}).items():
            mg = next(T["manager"] for T in S["teams"] if str(T["teamId"]) == tid)
            for e in lst: owner[str(e["playerId"])] = mg
        if S["platform"] == "ESPN":
            pts = S.get("seasonPoints", {})
        else:
            pts = {pid: sum(w.values()) for pid, w in S.get("playerWeekly", {}).items()}
        for pid, v in sorted(pts.items(), key=lambda kv: -kv[1])[:n]:
            p = S["players"].get(pid, {"name": pid, "pos": "?"})
            d = drafted.get(pid)
            out.append({"pid": pid, "name": p["name"], "pos": p["pos"], "pts": round(v, 2), "drafted": d and d["manager"], "round": d and d["round"], "slot": d and rp(d), "owner": owner.get(pid)})
        return out
    def trade_sides(t):
        sides = collections.defaultdict(list)
        for it in t["items"]:
            if it["type"] == "TRADE" and it.get("toManager"): sides[it["toManager"]].append(f"{it['name']} ({it.get('pos','?')})")
        for pk in t.get("picks", []):
            if pk.get("toManager"):
                s = f"{pk['season']} round {pk['round']} pick"
                if pk.get("originalManager") and pk["originalManager"] != pk.get("fromManager"): s += f" (orig. {mname(pk['originalManager'])})"
                sides[pk["toManager"]].append(s)
        return list(sides.items())
    def awards_by_key(y):
        return {a["key"]: a for a in L["seasonMeta"][str(y)]["awards"]}
    def award_counts(mid):
        c = collections.Counter()
        for y in L["years"]:
            for a in L["seasonMeta"][str(y)]["awards"]:
                if mid in a.get("holderIds", [a["manager"]]): c[a["key"]] += 1
        return c
    def _kv(r, key):
        if key == "wl": return (r["w"], r["l"], r.get("t", 0))
        v = r.get(key)
        return v if v is not None else 0
    def _same(a, b):
        return a == b if isinstance(a, tuple) else abs(a - b) < 1e-6
    def rk(rows, key):
        """Rank labels with ties: identical values share a rank, shown as T1, T1, 3..."""
        vals = [_kv(r, key) for r in rows]; out = []
        for i, v in enumerate(vals):
            first = next(j for j in range(len(vals)) if _same(vals[j], v))
            n = sum(1 for x in vals if _same(x, v))
            out.append(("T" if n > 1 else "") + str(first + 1))
        return out
    def tied(rows, key):
        """All rows tied with the first one (exact value)."""
        if not rows: return []
        v0 = _kv(rows[0], key)
        return [r for r in rows if _same(_kv(r, key), v0)]
    def initials(mid):
        return "".join(w[0] for w in mname(mid).split())
    def ts(ms):
        if not ms: return ""
        return datetime.datetime.fromtimestamp(ms / 1000).strftime("%b %-d, %Y")
    def md(text):
        t = str(escape(text or "")).replace("\\*", "\x00")
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t); t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        t = re.sub(r"\[(.+?)\]\(((?:https?://|#)[^)\s]+|[\w./-]+\.html(?:#[\w-]+)?)\)", r'<a href="\2">\1</a>', t)
        t = t.replace("\x00", "*")
        def blk(p):
            ls = p.split("\n")
            if all(l.startswith("- ") for l in ls):
                return "<ul>" + "".join(f"<li>{l[2:]}</li>" for l in ls) + "</ul>"
            return f"<p>{p}</p>"
        return Markup("".join(blk(p) for p in t.split("\n\n")))
    def cat_icon(c):
        return {"trade": "🤝", "waiver": "🧲", "injury": "🚑", "game": "🏟️", "draft": "📋", "controversy": "🔥", "tradition": "🎩"}.get(c, "📌")

    def rp(p):
        return f"{p['round']}.{int(p['pick']):02d}" if p and p.get("pick") is not None else (f"R{p['round']}" if p else "")
    def rec(r):
        return f"{r['w']}-{r['l']}" + (f"-{r['t']}" if r.get('t') else '')
    built = datetime.datetime.now().strftime("%b %-d, %Y %-I:%M %p ET")
    G = dict(NOINDEX=bool(os.environ.get("LOEG_NOINDEX")), L=L, seasons=seasons, mname=mname, f=f, ordinal=ordinal, team_name=team_name, team_name_id=team_name_id, seed_of=seed_of,
             playoff_rounds=playoff_rounds, weeks=weeks, draft_board=draft_board, top_players=top_players, trade_sides=trade_sides,
             awards_by_key=awards_by_key, rec=rec, rp=rp, F=F, TR=TR, race_svg=race_svg, grade_cls=grade_cls, pair_id=pair_id, bx=bx, box_of=box_of, box_for=box_for, game_log=game_log, riv=riv, sgn=sgn, award_counts=award_counts, rk=rk, tied=tied, initials=initials, ts=ts, md=md, cat_icon=cat_icon, built=built)
    G["SITE"] = SITE
    env.globals.update(G)

    def pstat(year, pid=None, name=None):
        """Per-game line for a player-season: league points / games actually played (byes and inactive weeks excluded)."""
        S_ = seasons.get(int(year)) if year is not None else None
        if not S_: return None
        if pid is None and name:
            pid = next((p["playerId"] for p in (S_.get("draft") or []) if p.get("name") == name), None)
            if pid is None:
                pid = next((k for k, v in (S_.get("players") or {}).items() if v.get("name") == name), None)
        if pid is None: return None
        w = (S_.get("playerWeekly") or {}).get(str(pid))
        if not w: return None
        if S_["platform"] == "Sleeper":
            done = S_.get("completedWeeks") or 0
            pts = sum(v for k, v in w.items() if int(k) <= done)
            gp = (S_.get("gamesPlayed") or {}).get(str(pid), 0)
        else:
            pts = sum(w.values()); gp = len(w)
        if not gp: return {"ppg": None, "gp": 0, "pts": round(pts, 2)}
        return {"ppg": round(pts / gp, 1), "gp": gp, "pts": round(pts, 2)}

    def ppg(year, pid=None, name=None, fallback=None, short=False):
        st = pstat(year, pid, name)
        if not st or st["ppg"] is None:
            if st and st["gp"] == 0: return Markup('<span class="muted">0 GP</span>')
            return Markup(f"{f(fallback)} pts") if fallback is not None else Markup("-")
        if short: return Markup(f'{st["ppg"]:.1f} PPG')
        return Markup(f'{st["ppg"]:.1f} PPG <span class="muted small">· {st["gp"]} GP</span>')
    env.globals.update(pstat=pstat, ppg=ppg)
    # Power rankings: weekly JSONs saved by scripts/power_rankings.py in data/power_rankings_history (never recomputed here)
    import glob as _g, json as _pj
    PRH = [_pj.load(open(x)) for x in sorted(_g.glob(os.path.join(DATA, "power_rankings_history", f"{max(L['years'])}_w*.json")))]
    PRH.sort(key=lambda d: d["meta"]["week"])
    PR = PRH[-1] if PRH else None
    env.globals["PR"] = PR
    # Weekly roast: latest data/roasts/<season>_wNN.json for the current season (hand-written, committed)
    _ro = sorted(_g.glob(os.path.join(DATA, "roasts", f"{max(L['years'])}_w*.json")))
    env.globals["ROAST"] = _pj.load(open(_ro[-1])) if _ro else None
    env.globals["PR_CHART"] = pr_chart(PRH) if len(PRH) > 1 else None
    env.globals["PR_RETRO"] = [d["meta"]["week"] for d in PRH if d["meta"].get("retro")]
    env.filters["camelwbr"] = lambda t: Markup(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "<wbr>", str(escape(t))))

    def ml_factory(root):
        def ml(mid):
            if not mid: return Markup('<span class="muted">-</span>')
            return Markup(f'<a href="{root}managers/{escape(mid)}.html">{escape(mname(mid))}</a>')
        return ml

    if os.path.exists(DIST): shutil.rmtree(DIST)
    shutil.copytree(os.path.join(SRC, "static"), os.path.join(DIST, "static"))

    def collapse_sections(h):
        """Wrap each top-level <h2 id> section between the collapse markers in a closed <details class="lx psec">."""
        a = h.index("<!--collapse-start-->"); b = h.index("<!--collapse-end-->")
        mid = h[a + len("<!--collapse-start-->"):b]
        fav = '<div class="grid g2">\n<div><h2>Favorite Players'
        starts = [m.start() for m in re.finditer(r'<h2 id="[^"]+">', mid)] + ([mid.index(fav)] if fav in mid else [])
        starts = sorted(set(starts))
        if not starts: return h.replace("<!--collapse-start-->", "").replace("<!--collapse-end-->", "")
        out = [mid[:starts[0]]]
        for i, st in enumerate(starts):
            seg = mid[st:starts[i + 1] if i + 1 < len(starts) else len(mid)]
            m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', seg, re.S)
            if m:
                sid, title, body = m.group(1), m.group(2), seg[m.end():]
                out.append(f'<details class="lx psec" id="sec-{sid}"><summary class="lx-sum"><div><h2 id="{sid}">{title}</h2></div><span class="lx-chev" aria-hidden="true"></span></summary>{body}</details>\n')
            else:
                out.append(f'<details class="lx psec" id="sec-favorites"><summary class="lx-sum"><div><h2 id="favorites">❤️ Favorite players &amp; draft picks</h2></div><span class="lx-chev" aria-hidden="true"></span></summary>{seg}</details>\n')
        return h[:a] + "".join(out) + h[b + len("<!--collapse-end-->"):]

    def render(tpl, out, root, **ctx):
        env.globals["ml"] = ml_factory(root)
        h = env.get_template(tpl).render(root=root, page_path=out, **ctx)
        if "<!--collapse-start-->" in h: h = collapse_sections(h)
        p = os.path.join(DIST, out); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(h)

    render("index.html", "index.html", "", title="Home", nav="home")
    render("seasons_index.html", "seasons/index.html", "../", title="Seasons", nav="seasons")
    for y, S in seasons.items():
        render("season.html", f"seasons/{y}.html", "../", title=f"{y} Season", nav="seasons", S=S)
    render("draft_order.html", "seasons/draft-order.html", "../", title="Draft Order Games", nav="lore")
    render("managers_index.html", "managers/index.html", "../", title="Managers", nav="managers")
    for mid, P in L["profiles"].items():
        render("manager.html", f"managers/{mid}.html", "../", title=P["name"], nav="managers", P=P)
    render("records.html", "records.html", "", title="Record Book", nav="records", sub="records.html")
    dyn = [s for s in seasons.values() if s["platform"] == "Sleeper"]
    if dyn:
        render("dynasty.html", "dynasty.html", "", title="Dynasty Era", nav="dynasty", sub="dynasty.html", S=max(dyn, key=lambda s: s["year"]), PR=PR)
    lore = sorted(L["lore"], key=lambda e: (not e.get("featured"), -(e.get("season") or 0), e.get("week") or 0))
    cats = sorted(set(e["category"] for e in lore))
    render("lore.html", "lore.html", "", title="Lore", nav="lore", lore=lore, lore_cats=cats)
    render("memorial.html", "memoriam.html", "", title="In Memoriam", nav="memoriam")
    for tpl, out, title in [("luck.html", "luck.html", "Schedule Luck"), ("trades.html", "trades.html", "Trade Report Cards"),
                            ("regrets.html", "regrets.html", "The Ones That Got Away"), ("drafts.html", "drafts.html", "Draft Trends"),
                            ("projections.html", "projections.html", "Projection vs Reality")]:
        render(tpl, out, "", title=title, nav="records", sub=out)
    render("rivalries_index.html", "rivalries/index.html", "../", title="Rivalries", nav="records", sub="rivalries/index.html")
    for k, R in F["rivalries"].items():
        render("rivalry.html", f"rivalries/{k}.html", "../", title=f"{mname(R['a'])} vs {mname(R['b'])}", nav="records", sub="rivalries/index.html", R=R)
    if F.get("dynasty"):
        render("tracker.html", "tracker.html", "", title="Dynasty Tracker", nav="dynasty", sub="tracker.html", D=F["dynasty"])
        import json as _j
        ph = load(os.path.join(GEN, "players_history.json"), {})
        names = {m: mname(m) for m in MG}
        _idx_players = [[v["n"], v.get("p", ""), k] for k, v in sorted(ph.items())]
        open(os.path.join(DIST, "static", "players.js"), "w").write("window.PH=" + _j.dumps(ph, separators=(",", ":")) + ";window.PHM=" + _j.dumps(names, separators=(",", ":")) + ";")
    # Quick-jump search index (managers, seasons, players), loaded on demand by site.js
    import json as _j2
    idx = {"m": [[L["profiles"][m]["name"], f"managers/{m}.html", " ".join(sorted({t["name"] for t in L["profiles"][m]["teamNames"]} | ({L["profiles"][m]["nickname"]} if L["profiles"][m].get("nickname") else set()))), "Latest team: " + L["profiles"][m]["teamNames"][-1]["name"]] for m in L["managerOrder"]],
           "s": [[str(y), f"seasons/{y}.html", (f"Champion: {mname(seasons[y]['champion'])}" if seasons[y].get("champion") else "In progress")] for y in sorted(L["years"], reverse=True)]
                + ([["Dynasty overview", "dynasty.html", "Dynasty era"]] if dyn else []) + ([["Dynasty Tracker", "tracker.html", "Dynasty era"]] if F.get("dynasty") else []),
           "p": locals().get("_idx_players", [])}
    open(os.path.join(DIST, "static", "search.json"), "w").write(_j2.dumps(idx, separators=(",", ":"), ensure_ascii=False))
    # GitHub Pages serves 404.html at any depth, so it links from the site's absolute base path (from data/site.json url).
    from urllib.parse import urlparse
    for x in BOXES:
        render("box.html", x["url"], "../../", title=f"{x['year']} Week {x['week']}: {mname(x['sides'][0]['manager'])} vs {mname(x['sides'][1]['manager'])}", nav="seasons", B=x, S=seasons[x["year"]])
    for y in L["years"]:
        render("box_index.html", f"box/{y}/index.html", "../../", title=f"{y} All Games", nav="seasons", S=seasons[y],
               games=[x for x in BOXES if x["year"] == y])
    print("box scores:", len(BOXES))
    render("404.html", "404.html", (urlparse(SITE.get("url") or "").path or ""), title="Page not found", nav="")
    open(os.path.join(DIST, ".nojekyll"), "w").write("")
    print("site built ->", DIST, sum(len(fs) for _, _, fs in os.walk(DIST)), "files")


if __name__ == "__main__":
    main()
