"""Render favicon PNGs and the 1200x630 Open Graph share image into src/static (run once; outputs are committed)."""
import os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ST = os.path.join(ROOT, "src", "static")
svg = open(os.path.join(ST, "favicon.svg")).read()
og = """<html><body style="margin:0;width:1200px;height:630px;background:radial-gradient(900px 400px at 50%% 0,#3a2a0d,transparent 70%%),#0e1320;
color:#f3e9d2;font-family:Georgia,serif;display:flex;align-items:center;justify-content:center;text-align:center">
<div><div style="width:150px;height:150px;margin:0 auto 18px">%s</div>
<div style="letter-spacing:.3em;color:#e8b84a;font:700 26px system-ui,sans-serif;text-transform:uppercase">The League of Extraordinary Gentlemen</div>
<div style="font-size:92px;font-weight:800;margin:10px 0">LOEG History Book</div>
<div style="font:30px system-ui,sans-serif;color:#b8bccb">Champions · The Belt · Records · Rivalries · Lore · 2020-today</div></div></body></html>""" % svg
with sync_playwright() as p:
    b = p.chromium.launch()
    for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png")):
        pg = b.new_page(viewport={"width": size, "height": size})
        pg.set_content(f'<html><body style="margin:0">{svg.replace("<svg ", f"<svg width={size} height={size} ")}</body></html>')
        pg.screenshot(path=os.path.join(ST, name), omit_background=True)
    pg = b.new_page(viewport={"width": 1200, "height": 630}); pg.set_content(og)
    pg.screenshot(path=os.path.join(ST, "og-image.png"))
    b.close()
print("icons ok")
