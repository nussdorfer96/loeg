from playwright.sync_api import sync_playwright
B="https://nussdorfer96.github.io/loeg/"
with sync_playwright() as p:
    b=p.chromium.launch(); c=b.new_context(viewport={"width":390,"height":844},device_scale_factor=2,is_mobile=True,has_touch=True)
    pg=c.new_page()
    pg.goto(B+"box/2024/w17-brian-mulvihill-vs-nicholas-kasik.html"); pg.wait_for_timeout(800)
    pg.screenshot(path="screenshots/box_score_mobile.png")
    pg.goto(B+"records.html#games"); pg.wait_for_timeout(800)
    pg.screenshot(path="screenshots/records_links_mobile.png")
    pg.goto(B+"lore.html#the-heist"); pg.wait_for_timeout(800)
    pg.screenshot(path="screenshots/lore_heist_mobile.png")
    b.close()
