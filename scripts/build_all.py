"""One command to rebuild everything: process raw data -> aggregate -> render site.
Usage: python3 scripts/build_all.py            (all seasons)
       python3 scripts/build_all.py --fetch    (also refresh live Sleeper data first)
"""
import os, sys, subprocess, glob, re
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.chdir(HERE)
if "--fetch" in sys.argv:
    subprocess.run(["bash", os.path.join(HERE, "fetch_sleeper.sh")], check=True)
import process_espn, process_sleeper, aggregate, features, build_site
espn_years = sorted(int(re.findall(r"(\d{4})", os.path.basename(p))[0]) for p in glob.glob(os.path.join(ROOT, "raw", "espn", "espn_*_core.json")))
for y in espn_years:
    process_espn.process(y)
process_sleeper.process(2026)
for d in sorted(glob.glob(os.path.join(ROOT, "raw", "sleeper", "20[0-9][0-9]"))):
    process_sleeper.process(int(os.path.basename(d)))
aggregate.build()
features.main()
build_site.main()
import make_zip  # also refresh league-site.zip
