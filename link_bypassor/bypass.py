import asyncio
import sys
from playwright.async_api import async_playwright
SHORT = sys.argv[1] if len(sys.argv) > 1 else "https://linkshortx.in/C8Cr3lFG"
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", viewport={"width":1366,"height":900}, locale="en-US")
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        gw=None; tg=None
        page.on("framenavigated", lambda f: print(f"[NAV] {f.url[:300]}") if f==page.main_frame else None)
        async def on_resp(r):
            nonlocal gw, tg
            try:
                u=r.url
                if "/links/gw/" in u:
                    gw=u; print(f"[GATEWAY] {u}")
                loc=r.headers.get("location","")
                if loc:
                    print(f"[{r.status}] {u[:150]} -> {loc[:300]}")
                    if "/links/gw/" in loc: gw=loc
                    if "telegram" in loc: tg=loc; print(f"[TELEGRAM] {loc}")
                if "telegram.me" in u or "t.me/" in u:
                    tg=u; print(f"[TELEGRAM-URL] {u}")
            except Exception as e: print("hook err", e)
        page.on("response", on_resp)
        await page.goto(SHORT, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3)
        for i in [1,2,3,4]:
            print(f"--- step {i}: {page.url[:150]} ---")
            try: await page.locator("#go").click(timeout=4000)
            except: pass
            for _ in range(30):
                await asyncio.sleep(2)
                try:
                    if await page.locator("#pCont:not(.x)").count()>0: break
                except: pass
            try: await page.locator("#cont").click(timeout=4000)
            except: pass
            for _ in range(12):
                await asyncio.sleep(2)
                try:
                    if await page.locator("#pDone:not(.x)").count()>0: break
                except: pass
            await page.evaluate("document.getElementById('hsg')?.remove();document.documentElement.style.overflow='';document.querySelectorAll('.x').forEach(e=>e.classList.remove('x'));")
            await asyncio.sleep(1)
            if i<4:
                await page.evaluate("document.getElementById('fwd').submit()")
                try: await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except: pass
                await asyncio.sleep(2)
            else:
                print("FINAL HREF:", await page.locator("#final").get_attribute("href"))
                await page.evaluate("document.getElementById('final').click()")
                try: await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except: pass
                await asyncio.sleep(3)
        print("=== interstitial:", page.url)
        for _ in range(20):
            await asyncio.sleep(2)
            try:
                gl = page.locator("a.get-link")
                if await gl.count()>0:
                    cls = await gl.first.get_attribute("class")
                    txt = (await gl.first.text_content() or "")[:60]
                    print(f" get-link class='{cls}' text='{txt.strip()}' url={page.url[:120]}")
                    if cls and "disabled" not in cls:
                        break
            except: pass
        print("clicking Get Link...")
        try:
            await page.locator("a.get-link").first.click(timeout=10000)
        except Exception as e:
            print("get-link click err:", e)
            try:
                await page.evaluate("document.getElementById('go-submit').disabled=false; document.getElementById('go-link').submit()")
            except Exception as e2: print("submit err", e2)
        for _ in range(15):
            await asyncio.sleep(2)
            print(f"  wait url={page.url[:250]}")
            if tg or "telegram" in page.url or gw: break
        print("\n===== RESULT =====")
        print("GATEWAY:", gw)
        print("TELEGRAM:", tg)
        print("FINAL:", page.url)
        await b.close()
asyncio.run(main())
