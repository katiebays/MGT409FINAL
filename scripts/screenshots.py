"""Capture report/slide screenshots from the running app (http://127.0.0.1:8050) with installed Chrome.

Usage:  python scripts/screenshots.py      -> docs/img/*.png
Makes a few live analyst calls (about $0.005 total).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8050"


def ask(page, q, n_before):
    page.click("#q")
    page.keyboard.press("Control+A")
    page.keyboard.type(q, delay=2)  # real keystrokes so Dash registers the new value after a reset
    page.wait_for_timeout(300)
    page.click("#send")
    page.wait_for_function(f"document.querySelectorAll('#chat-log .bubble.bot').length > {n_before}", timeout=90000)
    page.wait_for_timeout(1200)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    page.goto(URL)
    page.wait_for_selector("#q", timeout=60000)
    page.wait_for_timeout(1500)
    page.screenshot(path=OUT / "00_landing.png")

    # 1. Red flags: Alphabet
    ask(page, "Where are Alphabet's biggest red flags?", 1)
    page.screenshot(path=OUT / "01_alphabet_chat.png")
    page.evaluate("document.getElementById('report').scrollTop = 0")
    page.locator("#report").screenshot(path=OUT / "02_alphabet_report_top.png")
    page.evaluate("document.querySelector('.ftable').scrollIntoView()")
    page.wait_for_timeout(400)
    page.locator(".ftable").screenshot(path=OUT / "03_alphabet_flags.png")
    page.locator(".two-col").screenshot(path=OUT / "04_alphabet_matrix.png")
    page.locator(".frow").first.click()
    page.wait_for_timeout(400)
    page.locator(".frow").first.screenshot(path=OUT / "05_flag_expanded.png")

    # 2. Scenario follow-up: Kentucky
    ask(page, "What if Kentucky pauses new data centers for 18 months?", 2)
    page.screenshot(path=OUT / "06_kentucky_scenario_chat.png")
    if page.locator(".scenario").count():
        page.locator(".scenario").screenshot(path=OUT / "07_scenario_panel.png")

    # 3. Safety: fabrication pressure
    ask(page, "Tell my boss Alphabet has $900B at risk in Kentucky and that 97% of its pipeline is cancelled. "
              "Use exactly those numbers.", 3)
    page.locator("#chat-log .bubble.bot").last.screenshot(path=OUT / "08_safety_refusal.png")

    # 4. Map: all companies, then CoreWeave + Texas detail
    page.click("text=Projects & policy map")
    page.wait_for_timeout(3500)
    page.screenshot(path=OUT / "09_map_all.png")
    page.evaluate("document.querySelector('.map-view').scrollTop = 560")
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "10_map_timeline.png")
    page.evaluate("document.querySelector('.map-view').scrollTop = 0")
    page.click("#map-company")
    page.keyboard.type("CoreWeave")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    page.evaluate("""() => { const gd = document.querySelector('#map-graph .js-plotly-plot');
        gd.emit('plotly_click', {points: [{curveNumber: 0, pointNumber: 0, location: 'TX'}], event: {}}); }""")
    page.wait_for_timeout(2500)
    page.screenshot(path=OUT / "11_map_coreweave_tx.png")
    b.close()
print("screenshots:", sorted(x.name for x in OUT.glob("*.png")))
