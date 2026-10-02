"""Shared helpers for the league data pipeline."""
import json, os, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
DATA = os.path.join(ROOT, "data")
GEN = os.path.join(DATA, "generated")
# Where the weekly ESPN archive may live (first match wins per file name).
ARCHIVE_DIRS = [os.path.join(RAW, "espn_archive"), "/home/box/Downloads/espn_archive", "/home/box/Downloads"]

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
POS_SLOT = {1: "0", 2: "2", 3: "4", 4: "6", 5: "17", 16: "16"}  # position -> lineup slot used for pointsOverrides
BENCH_SLOTS = {20, 21}  # BE, IR
# ESPN proTeamId -> NFL abbreviation (team for that season/week comes from the season's own data, never today's roster)
NFL_ABBR = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC",
            13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
            25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
SLOT_NAMES = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "BE", 21: "IR", 23: "FLEX", 7: "OP"}


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=False)


def r2(x):
    return None if x is None else round(float(x), 2)


def find_archive_files(year):
    """Return {week:int -> path} of weekly ESPN archive files for a season."""
    out = {}
    for d in ARCHIVE_DIRS:
        for p in glob.glob(os.path.join(d, f"espn_{year}_w*.json")):
            base = os.path.basename(p)
            try:
                wk = int(base.split("_w")[1].split(".")[0])
            except ValueError:
                continue
            out.setdefault(wk, p)
    return dict(sorted(out.items()))


def find_tx_files(year):
    """Standalone transaction dumps (espn_YYYY_tx*.json) in any archive dir."""
    seen, out = set(), []
    for d in ARCHIVE_DIRS:
        for p in sorted(glob.glob(os.path.join(d, f"espn_{year}_tx*.json"))):
            b = os.path.basename(p)
            if b not in seen:
                seen.add(b); out.append(p)
    return out
