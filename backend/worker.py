"""Bypass worker: fast path (~1 min). The 15-20s countdown + 5s hold per step
are pure client-side JS that only unhide buttons - the server can't see them.
The server enforces ONE thing: ~3s+ dwell per step page before submitting
(submit faster -> next page renders 'link expired'). 6s dwell passes cleanly.
Heavy ad/tracker resources are blocked to speed page loads."""
import asyncio

from playwright.async_api import async_playwright

DWELL = 6  # seconds per step page; minimum proven ~3s, 6s = safe margin

BLOCKED = ("googlesyndication", "doubleclick", "google-analytics",
           "googletagmanager", "facebook.net")

_browsers_ready = False


def _ensure_browsers():
    """Self-heal: if the Playwright browser binary is missing (e.g. Render
    reused a cached build env and skipped the install step), install it at
    runtime on first job. No-op when browsers already exist."""
    global _browsers_ready
    if _browsers_ready:
        return
    import shutil
    import subprocess

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            exe = pw.chromium.executable_path
            import os

            if os.path.exists(exe):
                _browsers_ready = True
                return
    except Exception:
        pass
    if shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome"):
        _browsers_ready = True
        return
    subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=False, timeout=300)
    _browsers_ready = True


async def _new_page(pw):
    _ensure_browsers()
    launch_kw = {
        # channel="chromium" forces the FULL chromium build instead of the
        # headless-shell stub - headless shell cannot run the JS redirect
        # chain (strands on linkshortx.in with a 1430-byte shell, no nav).
        "channel": "chromium",
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    import shutil

    sys_chrome = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if sys_chrome:
        launch_kw["executable_path"] = sys_chrome
    b = await pw.chromium.launch(**launch_kw)
    ctx = await b.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 900},
        locale="en-US",
    )
    await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = await ctx.new_page()

    async def _route(r):
        try:
            url = r.request.url
            # NOTE: do NOT block gpt/ads.js/images - the q7m4vk29 -> google ->
            # article redirect chain depends on them; blocking strands us on
            # linkshortx.in with a 1430-byte shell. Only cut pure trackers.
            if r.request.resource_type == "font" or any(d in url for d in BLOCKED):
                await r.abort()
            else:
                await r.continue_()
        except Exception:
            pass

    await page.route("**/*", _route)
    return b, page


async def _wait_fwd(page, timeout=20):
    for _ in range(timeout):
        try:
            if await page.locator("#fwd").count() > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


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
        b, page = await _new_page(pw)

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
        try:
            # networkidle waits past the q7m4vk29 -> google -> article hop chain
            await page.goto(short_url, wait_until="commit", timeout=45000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass  # google interstitial / slow load - URL still lands, keep going
        # the short link bounces: linkshortx -> q7m4vk29.php -> google -> article.
        # wait until we reach a hindisink article (or timeout after ~30s).
        for _ in range(30):
            try:
                url = page.url
                if "hindisink.com" in url and "q7m4vk29" not in url and "google.com" not in url:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        # wait for the step page to actually render its form (slow free-tier loads)
        reached = None
        for _ in range(30):
            try:
                if await page.locator("#fwd").count() > 0 or await page.locator("#go").count() > 0:
                    reached = page.url
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        if reached is None:
            try:
                html_len = await page.evaluate("document.documentElement.outerHTML.length")
            except Exception:
                html_len = -1
            raise RuntimeError(f"Step 1: no form rendered (url={page.url[:120]}, html_len={html_len})")
        await asyncio.sleep(2)

        for i in [1, 2, 3]:
            prog(f"Step {i} of 4: verifying...")
            if not await _wait_fwd(page):
                # maybe still on a google/q7m4vk29 hop or slow render - wait longer
                await asyncio.sleep(10)
                if not await _wait_fwd(page, timeout=20):
                    raise RuntimeError(f"Step {i}: verification form not found (link may have expired)")
            await page.evaluate("document.getElementById('hsg')?.remove();document.documentElement.style.overflow='';")
            await asyncio.sleep(DWELL)
            await page.evaluate("document.getElementById('fwd').submit()")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(3)
            prog(f"Step {i} of 4 done...")

        prog("Final step: unlocking your link...")
        for _ in range(20):
            try:
                if await page.locator("#final").count() > 0:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        await page.evaluate("document.getElementById('hsg')?.remove();")
        await asyncio.sleep(DWELL)
        try:
            await page.evaluate("document.getElementById('final').click()")
        except Exception as e:
            raise RuntimeError(f"Final step button missing: {e}")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(4)

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
