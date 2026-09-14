"""Bypass worker: fast path (~1 min). The 15-20s countdown + 5s hold per step
are pure client-side JS that only unhide buttons - the server can't see them.
The server enforces ONE thing: ~3s+ dwell per step page before submitting
(submit faster -> next page renders 'link expired'). 6s dwell passes cleanly."""
import asyncio
import os

from playwright.async_api import async_playwright

DWELL = 6  # seconds per step page; minimum proven ~3s, 6s = safe margin


async def _new_page(pw):
    launch_kw = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    # Browser launch: NO channel/executable overrides. Stock playwright resolves
    # its own binary (headless shell on Render) and launches it. Custom
    # overrides were the #1 source of 'Executable doesn't exist' crashes
    # across environments, so we launch exactly once, with no probing.
    print(f"[worker] playwright exe={pw.chromium.executable_path}", flush=True)
    # Optional residential proxy for datacenter-IP blocks.
    # Set PROXY_URL env var if the site serves Render IPs a block page.
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    ctx_kw = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 900},
        "locale": "en-US",
    }
    if proxy_url:
        print("[worker] using proxy", flush=True)
        ctx_kw["proxy"] = {"server": proxy_url}
    b = await pw.chromium.launch(**launch_kw)
    ctx = await b.new_context(**ctx_kw)
    await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = await ctx.new_page()
    # NOTE: no request-route blocking. An earlier version aborted gpt/ads.js
    # and images to save time, but the q7m4vk29 -> google -> article redirect
    # chain depends on them - blocking strands us on linkshortx.in.
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


async def _run_funnel_flow(page, prog, b):
    """Handle the HindiSink 'safety checker' funnel flow (NEW) co-existing with old steps.

    New flow (observed Sep 2026):
    1. short link -> 307 -> hindisink.com/link-checker/?f=1
    2. page shows #funnel-open ("Open link") button
    3. clicking it fires POST/GET link-checker/api.php
    4. api.php JSON contains input_url/final_url = telegram destination
    5. page UI does NOT navigate itself -> worker returns the API destination

    Old 4-step flow (#fwd x3 + #final + interstitial) is untouched in run_bypass.
    """
    result_data = {"telegram": None, "gateway": None, "final_url": None}

    async def on_api(r):
        try:
            if "api.php" not in r.url or r.status != 200:
                return
            try:
                body = await r.json()
            except Exception:
                return
            if not isinstance(body, dict) or not body.get("ok"):
                return
            dest = body.get("input_url") or body.get("final_url")
            if dest and str(dest).startswith("http"):
                result_data["telegram"] = dest
                result_data["final_url"] = dest
            for hop in body.get("redirect_chain", []) or []:
                hu = (hop or {}).get("url", "")
                if "/links/gw/" in hu:
                    result_data["gateway"] = hu
                if "telegram" in hu and not result_data.get("telegram"):
                    result_data["telegram"] = hu
        except Exception:
            pass

    page.on("response", on_api)

    prog("Clicking 'Open link' to start verification...")
    try:
        await page.wait_for_selector("#funnel-open", timeout=15000)
        await page.click("#funnel-open", timeout=10000)
    except Exception as e:
        raise RuntimeError(f"Funnel button click failed: {e}")

    prog("Verification in progress (scanning link safety)...")
    for _ in range(45):
        if result_data.get("telegram"):
            break
        await asyncio.sleep(1)

    if not result_data.get("telegram"):
        # fallback: destination may already be embedded in the page/boot state
        try:
            cand = await page.evaluate("""() => {
                const m = document.documentElement.outerHTML.match(/https:\/\/telegram\.me\/[^"'\\s<>]+/);
                return m ? m[0] : null;
            }""")
            if cand:
                result_data["telegram"] = cand
                result_data["final_url"] = cand
        except Exception:
            pass

    if not result_data.get("telegram"):
        raise RuntimeError("Funnel scan finished but no destination URL was returned")

    telegram = result_data["telegram"]
    gateway = result_data["gateway"]
    final = telegram or result_data["final_url"] or page.url

    await b.close()
    prog("Done!")
    return {"gateway": gateway, "telegram": telegram, "final_url": final}

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
    resp_chain = []  # last response statuses/urls: diagnoses stuck navigations
    async with async_playwright() as pw:
        b, page = await _new_page(pw)

        async def on_resp(r):
            nonlocal gw, tg
            try:
                u = r.url
                resp_chain.append((r.status, u[:120]))
                if len(resp_chain) > 20:
                    del resp_chain[: len(resp_chain) - 20]
                if "/links/gw/" in u:
                    gw = u
                loc = r.headers.get("location", "")
                if loc:
                    resp_chain.append((r.status, f"-> {loc[:120]}"))
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
        # wait for EITHER flow to render: old steps (#fwd/#go) or new funnel (#funnel-open).
        # Combined loop (old code checked steps for 30s THEN funnel once -> funnel jobs
        # wasted a minute and could mis-fire). Both flows co-exist; branch on sight.
        reached = None
        saw_funnel = False
        for _ in range(30):
            try:
                if await page.locator("#fwd").count() > 0 or await page.locator("#go").count() > 0:
                    reached = page.url
                    break
                if await page.locator("#funnel-open").count() > 0:
                    saw_funnel = True
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        if reached is None and saw_funnel:
            prog("New flow detected: safety checker funnel...")
            return await _run_funnel_flow(page, prog, b)
        if reached is None:

            try:
                html_len = await page.evaluate("document.documentElement.outerHTML.length")
                html_head = await page.evaluate("document.documentElement.outerHTML.slice(0, 600)")
                title = await page.title()
            except Exception:
                html_len = -1
                html_head = ""
                title = ""
            # Log the stuck page content server-side: distinguishes a bot-block
            # page (needs PROXY_URL) from an empty shell (browser problem).
            print(f"[worker] STUCK url={page.url[:160]} html_len={html_len} title={title[:120]}", flush=True)
            print(f"[worker] STUCK head={html_head[:500]!r} chain={resp_chain[-5:]!r}", flush=True)
            if "access denied" in title.lower() or "access denied" in (html_head or "").lower():
                # Last-resort free path: re-fetch the step chain server-side
                # through a residential-egress public proxy is out of scope;
                # mark clearly so the UI can route to on-device instead.
                raise RuntimeError("HTTP-403")
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
