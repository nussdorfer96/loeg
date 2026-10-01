"""PNG screenshots of key pages (desktop 1366x900 and phone 390x844) with headless Chromium.
Usage: python3 scripts/screenshots.py [base_url]   (default: file:// URLs into dist/, no server needed)"""
import sys, os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = sys.argv[1] if len(sys.argv) > 1 else "file://" + os.path.join(ROOT, "dist") + "/"
OUT = os.path.join(ROOT, "screenshots"); os.makedirs(OUT, exist_ok=True)
PAGES = [("home", "index.html"), ("manager_ryan-nussdorfer", "managers/ryan-nussdorfer.html"), ("season_2024", "seasons/2024.html"), ("manager_nicholas-kasik", "managers/nicholas-kasik.html"),
         ("records", "records.html"), ("dynasty", "dynasty.html"), ("memoriam", "memoriam.html"), ("lore", "lore.html")]
MOBILE = ["home", "manager_ryan-nussdorfer", "season_2024", "memoriam", "manager_nicholas-kasik", "lore"]
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, path in PAGES:
        pg = b.new_page(viewport={"width": 1366, "height": 900})
        pg.goto(BASE + path, wait_until="load"); pg.screenshot(path=os.path.join(OUT, f"{name}_desktop.png")); pg.close()
        if name in MOBILE:
            pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
            pg.goto(BASE + path, wait_until="load"); pg.screenshot(path=os.path.join(OUT, f"{name}_mobile.png")); pg.close()
        print("saved", name)
    b.close()
