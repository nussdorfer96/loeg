"""Check every local href/src in dist/ resolves to a file (and #anchor exists)."""
import os, re, sys, json, html
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist")
ids_cache = {}
def ids(p):
    if p not in ids_cache:
        t = open(p, encoding="utf-8").read()
        ids_cache[p] = set(re.findall(r'\bid="([^"]+)"', t))
    return ids_cache[p]
from urllib.parse import urlparse
SITE = json.load(open(os.path.join(os.path.dirname(DIST), "data", "site.json")))
BASE = urlparse(SITE.get("url") or "").path or None   # e.g. /loeg/ (used by 404.html)
bad = []; n = 0
for root, _, fs in os.walk(DIST):
    for fn in fs:
        if not fn.endswith(".html"): continue
        p = os.path.join(root, fn); t = open(p, encoding="utf-8").read()
        t = re.sub(r"<script>.*?</script>", "", t, flags=re.S)
        for u in re.findall(r'(?:href|src)="([^"]+)"', t):
            u = html.unescape(u)
            if re.match(r"^(https?:|mailto:|data:|javascript:)", u): continue
            n += 1
            path, _, frag = u.partition("#")
            if BASE and path.startswith(BASE): tgt = os.path.normpath(os.path.join(DIST, path[len(BASE):]))
            elif path.startswith("/"): bad.append((os.path.relpath(p, DIST), u + " (absolute path)")); continue
            else: tgt = os.path.normpath(os.path.join(root, path)) if path else p
            if not os.path.isfile(tgt): bad.append((os.path.relpath(p, DIST), u)); continue
            if frag and tgt.endswith(".html") and frag not in ids(tgt): bad.append((os.path.relpath(p, DIST), u + " (missing anchor)"))
# links generated client-side by the player lookup
ph = os.path.join(DIST, "static", "players.js")
if os.path.exists(ph):
    s = open(ph).read(); PH = json.loads(s[s.index("=") + 1:s.index(";window.PHM")])
    for k, v in PH.items():
        for r in v["h"]:
            n += 1
            if not os.path.isfile(os.path.join(DIST, "managers", r[1] + ".html")): bad.append(("players.js", r[1]))
print(f"checked {n} links, {len(bad)} broken")
for b in bad[:40]: print("  ", b)
sys.exit(1 if bad else 0)
