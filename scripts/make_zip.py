"""Zip dist/ into league-site.zip (open index.html from the unzipped folder; no server needed)."""
import os, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(ROOT, "league-site.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for d, _, fs in os.walk(os.path.join(ROOT, "dist")):
        for f in fs:
            p = os.path.join(d, f); z.write(p, os.path.join("league-site", os.path.relpath(p, os.path.join(ROOT, "dist"))))
print("wrote", out, os.path.getsize(out), "bytes")
