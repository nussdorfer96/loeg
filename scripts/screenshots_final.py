"""Phone screenshots: press-conference lore entry, Draft Order Games, Lore page, 404."""
import os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); D = os.path.join(ROOT, "dist"); O = os.path.join(ROOT, "screenshots")
u = lambda p: "file://" + os.path.join(D, p)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    pg.goto(u("lore.html")); pg.screenshot(path=os.path.join(O, "lore_mobile.png"))
    pg.evaluate("document.querySelector('.site').style.position='static'")
    pg.locator("#press-conferences").screenshot(path=os.path.join(O, "lore_press_conferences_mobile.png"))
    pg.goto(u("seasons/draft-order.html")); pg.screenshot(path=os.path.join(O, "draft_order_mobile.png"))
    pg.screenshot(path=os.path.join(O, "draft_order_full_mobile.png"), full_page=True)
    pg.goto(u("seasons/index.html")); pg.screenshot(path=os.path.join(O, "seasons_index_mobile.png"))
    pg.goto(u("404.html")); pg.screenshot(path=os.path.join(O, "404_mobile.png"))
    b.close()
print("ok")
