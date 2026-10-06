"""Bypass worker: fast path (~1 min). The 15-20s countdown + 5s hold per step
are pure client-side JS that only unhide buttons - the server can't see them.
The server enforces ONE thing: ~3s+ dwell per step page before submitting
(submit faster -> next page renders 'link expired'). 6s dwell passes cleanly."""
import asyncio
import os

from playwright.async_api import async_playwright

DWELL = 6  # seconds per step page; minimum proven ~3s, 6s = safe margin


ADHOSTS = ("yanvik", "doubleclick", "googlesyndication", "adtrafficquality", "sodar", "safeframe", "fundingchoices")


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
    # Headless tabs report visibilityState=hidden, which FREEZES the step
    # countdown/hold timers (the page checks `visible` every tick). Spoof the
    # tab as visible + focused so timers run in headless like a real tab.
    await ctx.add_init_script("Object.defineProperty(document,'visibilityState',{get:()=> 'visible',configurable:true}); Object.defineProperty(document,'hidden',{get:()=>false,configurable:true}); window.blurred=false; document.hasFocus=()=>true; document.addEventListener('visibilitychange',function(e){e.stopImmediatePropagation();},true);")
    # Ad-hijack guard: block off-site DOCUMENT navigations (the loan-ad domain
    # steals the main frame after form submits). Subresource loads are left
    # alone - the entry redirect chain needs its scripts. Only hindisink,
    # linkshortx and google document navigations are allowed through.
    async def _guard_nav(r):
        try:
            req = r.request
            u = (req.url or "").lower()
            if req.resource_type == "document" and req.is_navigation_request():
                if u.startswith("about:") or u.startswith("data:"):
                    await r.continue_()
                    return
                if "hindisink.com" in u or "linkshortx.in" in u or "google.com" in u:
                    await r.continue_()
                    return
                print(f"[worker] blocked off-site nav: {u[:150]}", flush=True)
                await r.abort()
                return
        except Exception:
            pass
        try:
            await r.continue_()
        except Exception:
            pass
    page = await ctx.new_page()
    try:
        await ctx.route("**/*", _guard_nav)
    except Exception:
        pass
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


async def _click_reveal(page, tag):
    """NEW step UI: click #go (verify) -> wait countdown -> click #cont -> wait hold.
    Returns True once #pDone is visible (i.e. #fwd may be submitted).
    Panels reveal in stages: pCont shows first, then pHold AFTER #cont click,
    then pDone AFTER the 5s hold. Never wait on pHold/pDone before clicking cont.
    NOTE: #go starts DISABLED ("Loading...") until ads render (~2.5s+). Always
    wait for it to enable before clicking - an early click is swallowed and the
    countdown never starts.
    """
    try:
        await page.wait_for_function("document.getElementById('go') && !document.getElementById('go').disabled", timeout=20000)
    except Exception:
        try:
            st = await page.evaluate("document.getElementById('go') ? document.getElementById('go').textContent : 'NO GO'")
        except Exception:
            st = "?"
        print("[worker] REVEAL go never enabled " + tag + " (" + str(st)[:40] + ")", flush=True)
        return False
    try:
        await page.click("#go", timeout=8000)
    except Exception:
        print("[worker] REVEAL fail go click " + tag, flush=True)
        return False
    # Stage 1: countdown finishes -> ONLY pCont visible. Click cont promptly
    # (the button may re-hide or the token may expire if left sitting).
    saw_cont = False
    for _ in range(60):
        await asyncio.sleep(1)
        try:
            vis = await page.evaluate("document.getElementById('pCont') ? !document.getElementById('pCont').classList.contains('x') : true")
            if vis:
                saw_cont = True
                break
        except Exception:
            pass
    if not saw_cont:
        print("[worker] REVEAL fail pCont " + tag, flush=True)
        return False
    # Click cont IMMEDIATELY in-page (same tick as detection). Playwright's
    # actionability checks (scroll/overlay wait) cost seconds during which the
    # button can re-hide; a direct DOM click fires the one-time listener now.
    try:
        await page.evaluate("document.getElementById('cont').click()")
    except Exception:
        try:
            await page.click("#cont", timeout=5000)
        except Exception:
            print("[worker] REVEAL fail cont click " + tag, flush=True)
            return False
    # Stage 2: 5s hold runs -> pDone visible. Wait ONLY for pDone now.
    for _ in range(25):
        await asyncio.sleep(1)
        try:
            vis = await page.evaluate("document.getElementById('pDone') ? !document.getElementById('pDone').classList.contains('x') : true")
            if vis:
                break
        except Exception:
            pass
    else:
        print("[worker] REVEAL fail pDone " + tag, flush=True)
        return False
    return True


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
            html = await page.content()
            idx = html.find("telegram.me")
            if idx > 0:
                s = html.rfind("https://", 0, idx)
                e = s
                while e < len(html) and html[e] not in ('"', chr(39), chr(60), chr(32)): e += 1
                cand = html[s:e]
                if cand.startswith("https://"):
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
        # NOTE: both hosts now front a JS challenge ("Checking your browser").
        # It self-solves in a real browser (~10-20s); NEVER treat its page as
        # a step page - wait it out, it navigates onward by itself.
        for _ in range(45):
            try:
                url = page.url
                ttl = await page.title()
                if "hindisink.com" in url and "q7m4vk29" not in url and "google.com" not in url:
                    if "checking your browser" not in (ttl or "").lower() and "just a moment" not in (ttl or "").lower():
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
            # NEW step UI: #fwd exists from page load but the server only accepts
            # the token AFTER the go->cont reveal (countdown + 5s hold). Clicking
            # through first is what makes the submit valid; zero extra dwell.
            # Never hard-fail on UI state: if the reveal stalls (backgrounded
            # tab, one-shot listeners), submit anyway and let the SERVER decide
            # (a bad token lands on a fresh step page = retried, not fatal).
            ok_reveal = await _click_reveal(page, f"step{i}")
            if not ok_reveal:
                print(f"[worker] step{i}: reveal stalled, submitting anyway (server decides)", flush=True)
            try:
                n = await page.locator("#fwd").count()
            except Exception:
                n = 0
            if not n:
                # reveal re-rendered the page (new token); re-wait for fresh #fwd
                if not await _wait_fwd(page, timeout=20):
                    raise RuntimeError(f"Step {i}: verification form not found (link may have expired)")
            await page.evaluate("document.getElementById('fwd').submit()")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(3)
            try:
                au = page.url
                at = await page.title()
                af = await page.locator("#fwd").count()
            except Exception:
                au = "?"; at = "?"; af = -1
            print(f"[worker] step{i} done -> url={au[:120]} title={at[:60]} fwd={af}", flush=True)
            # Vignette/ad guard: a submit sometimes lands on a google vignette
            # or ad overlay on the SAME page (no navigation captured) instead of
            # the next step. Detect + dismiss, then resubmit once.
            try:
                stuck_here = ("#google_vignette" in au) or (af > 0 and i < 3 and f"Step {i} of 4" in (at or ""))
            except Exception:
                stuck_here = False
            if stuck_here:
                print(f"[worker] step{i}: vignette/same-step landing, dismissing + resubmit", flush=True)
                try:
                    await page.evaluate("document.querySelectorAll('[id*=vignette], [class*=vignette], ins.adsbygoogle-noablate').forEach(function(e){e.remove();}); document.documentElement.style.overflow=''; document.body.style.overflow=''; window.scrollTo(0,0);")
                except Exception:
                    pass
                await asyncio.sleep(2)
                try:
                    if "google_vignette" in page.url:
                        await page.evaluate("window.history.back()")
                        await page.wait_for_load_state("domcontentloaded", timeout=20000)
                        await asyncio.sleep(3)
                except Exception:
                    pass
                try:
                    if await page.locator("#fwd").count() > 0:
                        if await _click_reveal(page, f"step{i}-retry2"):
                            await page.evaluate("document.getElementById('fwd').submit()")
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                            except Exception:
                                pass
                            await asyncio.sleep(3)
                            au = page.url
                            print(f"[worker] step{i} retry2 -> url={au[:120]}", flush=True)
                except Exception:
                    pass
            # Wrong-landing guard: ad scripts sometimes steal the post-submit
            # navigation (loan-ad domains). If we are not on a hindisink step
            # page, go back and resubmit once instead of continuing blindly.
            try:
                bad = ("hindisink.com" not in au) or ("google.com" in au) or ("q7m4vk29" in au)
            except Exception:
                bad = False
            if bad:
                print(f"[worker] step{i}: wrong landing ({au[:100]}), going back + resubmit", flush=True)
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
                await asyncio.sleep(3)
                try:
                    if await page.locator("#fwd").count() > 0:
                        await page.evaluate("document.getElementById('hsg')?.remove();document.documentElement.style.overflow='';")
                        if await _click_reveal(page, f"step{i}-retry"):
                            await page.evaluate("document.getElementById('fwd').submit()")
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                            except Exception:
                                pass
                            await asyncio.sleep(3)
                            au = page.url
                            print(f"[worker] step{i} retry -> url={au[:120]}", flush=True)
                except Exception:
                    pass
            prog(f"Step {i} of 4 done...")
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
        # Final page has TWO variants (observed):
        #  A) #final is an <a> whose href (?t=...) is assigned by the reveal
        #     -> navigate DIRECTLY to the href (skip google vignette).
        #  B) #final is a <button type=submit> inside #fwd -> POST to q7m4go.php
        #     -> submit #fwd after the reveal (4th form submit).
        ok_fin = await _click_reveal(page, "final")
        if not ok_fin:
            print("[worker] final: reveal stalled, trying submit anyway", flush=True)
        try:
            tag = await page.evaluate("document.getElementById('final') ? document.getElementById('final').tagName : ''")
            final_is_link = (tag or "").upper() == "A"
        except Exception:
            final_is_link = False
        # Resolve the final step. Two observed variants:
        #  A) #final is an <a> whose href (?t=...) is assigned by the reveal
        #     -> navigate DIRECTLY to the href (skip google vignette).
        #  B) #final is a <button type=submit> inside #fwd -> POST to q7m4go.php
        #     -> submit #fwd after the reveal (4th form submit).
        # Robust rule: if #final is an <a> WITH a valid http href -> navigate.
        # Otherwise (button, OR anchor without href) -> submit #fwd.
        final_href = None
        if final_is_link:
            try:
                final_href = await page.evaluate("document.getElementById('final').getAttribute('href')")
            except Exception:
                final_href = None
            if not final_href or not final_href.startswith("http"):
                try:
                    html = await page.content()
                    idx = html.find("linkshortx.in/")
                    if idx > 0:
                        s = html.rfind("https://", 0, idx)
                        e = s
                        while e < len(html) and html[e] not in ('"', "'", "<", " "):
                            e += 1
                        cand = html[s:e]
                        if cand.startswith("https://linkshortx.in/") and "?t=" in cand:
                            final_href = cand
                except Exception:
                    pass
        if final_href and final_href.startswith("http"):
            try:
                await page.goto(final_href, wait_until="commit", timeout=45000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(4)
        else:
            # Button variant (or anchor without href): submit #fwd.
            try:
                n = await page.locator("#fwd").count()
            except Exception:
                n = 0
            if not n:
                raise RuntimeError("Final step form missing (link may have expired)")
            await page.evaluate("document.getElementById('fwd').submit()")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(4)

        prog("Almost there: fetching your link...")
        # Interstitial: arm fires on page load; POLL for the reveal which
        # assigns a.get-link href=/links/gw/... directly. NEVER submit
        # #go-link: submitting POSTs again burns the one-shot token
        # (server answers Bad Request). Navigate to the gw href instead.
        gw_href = None
        for _ in range(20):
            await asyncio.sleep(1)
            try:
                cls = await page.evaluate("document.querySelector('a.get-link') ? document.querySelector('a.get-link').getAttribute('class') : ''")
                href = await page.evaluate("document.querySelector('a.get-link') ? document.querySelector('a.get-link').getAttribute('href') : ''")
                if cls and "disabled" not in cls and href and href != "javascript: void(0)":
                    gw_href = href
                    break
            except Exception:
                pass
        if gw_href:
            if gw_href.startswith("/"):
                gw_href = "https://linkshortx.in" + gw_href
            gw = gw_href
            try:
                await page.goto(gw_href, wait_until="commit", timeout=45000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(4)
        else:
            try:
                gl = page.locator("a.get-link")
                if await gl.count() > 0:
                    cls = await gl.first.get_attribute("class")
                    if cls and "disabled" not in cls:
                        await gl.first.click(timeout=8000)
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
