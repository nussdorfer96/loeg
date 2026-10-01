"""Phone (390x844) screenshots of the deep-dive features."""
import os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "dist"); O = os.path.join(ROOT, "screenshots"); os.makedirs(O, exist_ok=True)
u = lambda p: "file://" + os.path.join(D, p)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    def section(url, start, end, name, prep=None):
        pg.goto(u(url)); pg.wait_for_timeout(150)
        if prep: prep()
        box = pg.evaluate(f"""() => {{const a=document.querySelector('{start}').getBoundingClientRect();const e=document.querySelector('{end}');
            const z=e?e.getBoundingClientRect().top:a.bottom+800; return [a.top+scrollY-8, z-a.top+8]}}""")
        pg.screenshot(path=os.path.join(O, name), full_page=True, clip={"x": 0, "y": box[0], "width": 390, "height": min(box[1], 2400)})
    def tap_legend():
        pg.locator(".race .legend button.collapse").first.tap()
    section("seasons/2025.html", "#race", "#luck", "race_2025_mobile.png", tap_legend)
    pg.goto(u("rivalries/jacob-maddox--ryan-nussdorfer.html")); pg.screenshot(path=os.path.join(O, "rivalry_mobile.png"))
    pg.screenshot(path=os.path.join(O, "rivalry_full_mobile.png"), full_page=True)
    pg.goto(u("trades.html")); pg.screenshot(path=os.path.join(O, "trades_mobile.png"))
    pg.screenshot(path=os.path.join(O, "trades_full_mobile.png"), full_page=True)
    pg.goto(u("tracker.html")); pg.fill("#ph-q", "Christian McCaffrey"); pg.wait_for_timeout(200)
    pg.screenshot(path=os.path.join(O, "tracker_mobile.png"))
    pg.screenshot(path=os.path.join(O, "tracker_full_mobile.png"), full_page=True)
    def open_info():
        pg.evaluate("document.querySelectorAll('details.info').forEach(d=>d.open=true)")
    section("managers/ryan-nussdorfer.html", "#luck", "#trades", "manager_luck_draft_mobile.png", open_info)
    section("seasons/2024.html", "#luck", "#regrets", "season_luck_explainer_mobile.png", open_info)
    pg.goto(u("memoriam.html")); pg.locator("#parker-williams").screenshot(path=os.path.join(O, "memoriam_parker_mobile.png"))
    b.close()
print("ok")
