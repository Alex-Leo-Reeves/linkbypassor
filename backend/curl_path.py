"""curl_cffi fast path: resolves the hindisink step chain with pure HTTP.

Key findings from live probing:
- linkshortx.in serves 307 (not 403) to chrome-impersonated TLS: the block
  keys partly on TLS/JA3 fingerprint, so curl_cffi chrome124 passes where
  stock requests/Playwright-headless-shell fail.
- The #fwd form + token are already in the step page HTML: no JS needed.
- Server enforces ~3s+ dwell per step page: 6s sleep between POSTs.
- Cookie jar: GET the fwd action URL first (plants session cookies), then
  POST the token with Referer=<action URL>.

Returns dict(gateway, telegram, final_url) or raises RuntimeError.
"""
import re
import time

DWELL = 6


def _fwd_form(html: str):
    m = re.search(
        r'<form id="fwd" action="([^"]+)"[^>]*>.*?<input[^>]*name="([^"]+)" value="([^"]+)"',
        html,
        re.S,
    )
    return (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)


def _final_href(html: str):
    m = re.search(r'<a[^>]*id="final"[^>]*href="([^"]+)"', html)
    return m.group(1) if m else None


def run_curl_bypass(short_url: str, progress_cb=None):
    try:
        from curl_cffi import requests as cr
    except ImportError as e:
        raise RuntimeError("curl_cffi not installed") from e

    def prog(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    s = cr.Session(impersonate="chrome124")
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    # 1. short link: expect 307 to q7m4vk29 (403 here = hard IP block, abort fast)
    prog("Opening short link...")
    r1 = s.get(short_url, allow_redirects=False, timeout=20)
    if r1.status_code == 403:
        raise RuntimeError(
            "BLOCKED: linkshortx served this server HTTP 403 "
            "(datacenter IP + TLS fingerprint both rejected). "
            "Use the Actions worker or 1-click on-device bypass instead."
        )
    if r1.status_code not in (301, 302, 303, 307, 308) or "q7m4vk29" not in (r1.headers.get("location", "")):
        raise RuntimeError(f"Unexpected short-link response HTTP {r1.status_code}")

    # 2. q7m4vk29 page: extract google interstitial URL from inline JS
    r2 = s.get(r1.headers["location"], timeout=20)
    m = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', r2.text)
    if not m:
        raise RuntimeError("q7m4vk29 page has no redirect target")
    google_url = m.group(1)

    # 3. google notice page -> /goto link; follow it to land on step 1.
    # The notice page links hindisink via a /goto?url=... href.
    prog("Resolving redirect chain...")
    r3 = s.get(google_url, timeout=20)
    m3 = re.search(r'href="([^"]*hindisink\.com/[^"]*)"', r3.text)
    goto = None
    if m3:
        goto = m3.group(1)
        if goto.startswith("/"):
            goto = "https://www.google.com" + goto
    if goto:
        r4 = s.get(goto, timeout=25, allow_redirects=True)
        html = r4.text
    else:
        # Fallback: homepage won't have a step form; fail with clear message.
        raise RuntimeError("Google interstitial gave no hindisink target")

    if 'id="fwd"' not in html and 'id="go"' not in html:
        # The google hop lands on the homepage, not a step page; the step-1
        # context is minted by the q7m4vk29 JS chain in a real browser. Without
        # it, prime cookies on whatever step target we can find is impossible -
        # abort with a clear message so the caller falls through to Playwright.
        raise RuntimeError("Landed on homepage, not a step page (need browser for entry hop)")

    # 4-6. steps 1-3: prime cookies on the fwd target, dwell, POST token.
    for i in [1, 2, 3]:
        prog(f"Step {i} of 4: verifying...")
        action, field, token = _fwd_form(html)
        if not action:
            raise RuntimeError(f"Step {i}: no fwd form in page")
        s.get(action, timeout=25)  # plant session cookies like a landing browser
        time.sleep(DWELL)
        r = s.post(
            action,
            data={field: token},
            headers={"Referer": action, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
        html = r.text
        if "expired" in html[:3000].lower() and 'id="fwd"' not in html:
            raise RuntimeError(f"Step {i}: link expired (dwell too short or bad token)")
        prog(f"Step {i} of 4 done...")

    # 7. step 4: follow #final back to the linkshortx interstitial. The final
    # href loops to linkshortx.in/<code>; the interstitial + Get Link need a
    # real browser (arm/go XHR + 5s countdown), so hand back the URL for the
    # caller to finish with Playwright.
    prog("Final step: handing to browser for interstitial...")
    final_href = _final_href(html)
    return {"step4_html": html, "final_href": final_href, "gateway": None, "telegram": None, "final_url": None}
