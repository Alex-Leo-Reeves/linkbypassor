"""sniff.py - lightweight network sniffer for linkshortx.in flow.
Captures the /links/gw/ gateway URL and the final telegram redirect.
Usage: python sniff.py [SHORT_URL]
"""
import asyncio
import sys
from playwright.async_api import async_playwright

SHORT = sys.argv[1] if len(sys.argv) > 1 else "https://linkshortx.in/C8Cr3lFG"

async def main():
    gw = None
    tg = None
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()

        async def on_resp(r):
            nonlocal gw, tg
            try:
                u = r.url
                if "/links/gw/" in u:
                    gw = u
                    print(f"[GATEWAY {r.status}] {u}")
                loc = r.headers.get("location", "")
                if loc and ("/links/gw/" in loc or "telegram" in loc):
                    print(f"[REDIRECT {r.status}] {u[:150]} -> {loc[:300]}")
                    if "/links/gw/" in loc:
                        gw = loc
                    if "telegram" in loc:
                        tg = loc
            except Exception as e:
                print("hook err", e)

        page.on("response", on_resp)
        page.on("framenavigated", lambda f: print(f"[NAV] {f.url[:250]}") if f == page.main_frame else None)
        await page.goto(SHORT, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(6)
        print("URL:", page.url)
        print(f"\nGATEWAY: {gw}\nTELEGRAM: {tg}")
        await b.close()

asyncio.run(main())
