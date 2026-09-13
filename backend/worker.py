"""Bypass worker: extracted from link_bypassor/bypass.py, reports progress via callback."""
import asyncio

from playwright.async_api import async_playwright


async def run_bypass(short_url: str, progress_cb=None):
    def prog(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    gw = None
    tg = None
    final = None
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()

        async def on_resp(r):
            nonlocal gw, tg
            try:
                u = r.url
                if "/links/gw/" in u:
                    gw = u
                loc = r.headers.get("location", "")
                if loc:
                    if "/links/gw/" in loc:
                        gw = loc
                    if "telegram" in loc:
                        tg = loc
                if "telegram.me" in u or "t.me/" in u:
                    tg = u
            except Exception:
                pass

        page.on("response", on_resp)
        prog("Opening short link...")
        await page.goto(short_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3)

        for i in [1, 2, 3, 4]:
            prog(f"Step {i} of 4: verifying... (~1 min each)")
            try:
                await page.locator("#go").click(timeout=4000)
            except Exception:
                pass
            for _ in range(30):
                await asyncio.sleep(2)
                try:
                    if await page.locator("#pCont:not(.x)").count() > 0:
                        break
                except Exception:
                    pass
            prog(f"Step {i} of 4: continuing...")
            try:
                await page.locator("#cont").click(timeout=4000)
            except Exception:
                pass
            for _ in range(12):
                await asyncio.sleep(2)
                try:
                    if await page.locator("#pDone:not(.x)").count() > 0:
                        break
                except Exception:
                    pass
            await page.evaluate("document.getElementById('hsg')?.remove();document.documentElement.style.overflow='';document.querySelectorAll('.x').forEach(e=>e.classList.remove('x'));")
            await asyncio.sleep(1)
            if i < 4:
                prog(f"Step {i} of 4 done, moving to step {i + 1}...")
                await page.evaluate("document.getElementById('fwd').submit()")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                await asyncio.sleep(2)
            else:
                prog("Final step: unlocking your link...")
                await page.evaluate("document.getElementById('final').click()")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                await asyncio.sleep(3)

        prog("Almost there: fetching your link...")
        for _ in range(20):
            await asyncio.sleep(2)
            try:
                gl = page.locator("a.get-link")
                if await gl.count() > 0:
                    cls = await gl.first.get_attribute("class")
                    if cls and "disabled" not in cls:
                        break
            except Exception:
                pass
        try:
            await page.locator("a.get-link").first.click(timeout=10000)
        except Exception:
            try:
                await page.evaluate("document.getElementById('go-submit').disabled=false; document.getElementById('go-link').submit()")
            except Exception:
                pass
        for _ in range(15):
            await asyncio.sleep(2)
            if tg or "telegram" in page.url or gw:
                break
        final = page.url
        await b.close()
    prog("Done!")
    return {"gateway": gw, "telegram": tg, "final_url": final}
