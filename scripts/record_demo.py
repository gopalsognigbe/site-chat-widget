"""Record demo clips of the widget with Playwright (video only, no audio)."""
import asyncio, os, shutil
from playwright.async_api import async_playwright

BASE = "http://localhost:8000"
OUT = "loom_clips"
SCENES = [
    ("01_home", "/index.html", None),
    ("02_commission", "/index.html", "What is your commission to sell a house?"),
    ("03_listing", "/listings.html", "Tell me about LI-002"),
    ("04_french", "/fr/index.html", "Quels documents faut-il pour louer ?"),
    ("05_offtopic", "/index.html", "Do you sell cars?"),
]

async def type_question(page, q):
    await page.locator(".launcher").click()
    await page.wait_for_timeout(1200)
    box = page.locator(".input")
    await box.click()
    await box.press_sequentially(q, delay=70)
    await page.wait_for_timeout(500)
    async with page.expect_response(lambda r: "/chat" in r.url, timeout=90000):
        await box.press("Enter")
    await page.wait_for_timeout(5000)

async def scene(browser, name, path, q):
    ctx = await browser.new_context(viewport={"width": 1440, "height": 900},
                                    record_video_dir=f"{OUT}/tmp_{name}",
                                    record_video_size={"width": 1440, "height": 900})
    page = await ctx.new_page()
    await page.goto(BASE + path, wait_until="networkidle")
    await page.wait_for_timeout(2500)
    if q is None:
        for _ in range(6):
            await page.mouse.wheel(0, 450); await page.wait_for_timeout(900)
        await page.mouse.wheel(0, -5000); await page.wait_for_timeout(2000)
    else:
        await type_question(page, q)
        await page.screenshot(path=f"{OUT}/{name}.png")
    await ctx.close()
    vid = os.listdir(f"{OUT}/tmp_{name}")[0]
    shutil.move(f"{OUT}/tmp_{name}/{vid}", f"{OUT}/{name}.webm")
    os.rmdir(f"{OUT}/tmp_{name}")
    print("recorded", name)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for i, s in enumerate(SCENES):
            if i: await asyncio.sleep(3)
            await scene(browser, *s)
        await browser.close()

asyncio.run(main())
