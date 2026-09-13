"""curl_cffi HTTP path: resolves the hindisink step chain with pure HTTP.

Strategy: cheaper than Playwright (no browser), TLS-spoofed (chrome131)
so the WAF sees a real-browser handshake. Proven locally step-by-step:
  - short link -> 307 (not 403) with impersonated TLS
  - q7m4vk29 page carries the google interstitial URL in inline JS
  - step pages carry the #fwd form + token in raw HTML
  - priming cookies (GET the fwd action target first) + 6s dwell lets the
    token POST advance a step
Open question: whether the google-hop entry lands on a real step page or
the homepage from a datacenter IP (the step-1 context is minted by the
q7m4vk29 JS chain in a real browser). If entry fails, the caller falls
through to Playwright. If steps POST but lose context mid-chain, raises
with a clear message.

Returns dict(step4_html, final_href, gateway, telegram, final_url) —
the interstitial (#final -> Get Link) still needs a browser handoff.
"""
import re
import time

DWELL = 6
IMP = "chrome131"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"


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

    s = cr.Session(impersonate=IMP)
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    # 1. short link: expect 307 to q7m4vk29 (403 here = hard IP block, abort fast)
    prog("Opening short link (HTTP fast path)...")
    r1 = s.get(short_url, allow_redirects=False, timeout=20)
    if r1.status_code == 403:
        raise RuntimeError("HTTP-403")
    if r1.status_code not in (301, 302, 303, 307, 308) or "q7m4vk29" not in (r1.headers.get("location", "")):
        raise RuntimeError(f"HTTP-ENTRY-{r1.status_code}")

    # 2. q7m4vk29 page: extract google interstitial URL from inline JS
    r2 = s.get(r1.headers["location"], timeout=20)
    m = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', r2.text)
    if not m:
        raise RuntimeError("HTTP-NO-REDIRECT-TARGET")
    google_url = m.group(1)

    # 3. google notice page -> first hindisink href; follow it to step 1.
    prog("Resolving redirect chain (HTTP fast path)...")
    r3 = s.get(google_url, timeout=20)
    m3 = re.search(r'href="([^"]*hindisink\.com/[^"]*)"', r3.text)
    goto = None
    if m3:
        goto = m3.group(1)
        if goto.startswith("/"):
            goto = "https://www.google.com" + goto
    if not goto:
        raise RuntimeError("HTTP-NO-HINDI-TARGET")
    r4 = s.get(goto, timeout=25, allow_redirects=True)
    html = r4.text

    if 'id="fwd"' not in html and 'id="go"' not in html:
        raise RuntimeError("HTTP-HOMEPAGE-NOT-STEP")

    # 4-6. steps 1-3: prime cookies on the fwd target, dwell, POST token.
    # The fwd field name rotates (newwpsafelink/rtgsafelink/...): parsed live.
    # Referer = previous step page, tracked as we advance.
    referer = r4.url
    for i in [1, 2, 3]:
        prog(f"Step {i} of 4: verifying (HTTP fast path)...")
        action, field, token = _fwd_form(html)
        if not action:
            raise RuntimeError(f"HTTP-NO-FWD-{i}")
        s.get(action, timeout=25)  # plant session cookies like a landing browser
        time.sleep(DWELL)
        r = s.post(
            action,
            data={field: token},
            headers={"Referer": referer, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=25,
        )
        html = r.text
        referer = action
        if "expired" in html[:3000].lower() and 'id="fwd"' not in html:
            raise RuntimeError(f"HTTP-EXPIRED-{i}")
        if 'id="fwd"' not in html and 'id="final"' not in html:
            raise RuntimeError(f"HTTP-LOST-CONTEXT-{i}")
        prog(f"Step {i} of 4 done (HTTP fast path)...")

    # 7. step 4: follow #final back to the linkshortx interstitial. The final
    # href loops to linkshortx.in/<code>; the interstitial + Get Link need a
    # real browser (arm/go XHR + 5s countdown), so hand back the URL for the
    # caller to finish with Playwright.
    prog("Final step: handing to browser for interstitial...")
    final_href = _final_href(html)
    return {"step4_html": html, "final_href": final_href, "gateway": None, "telegram": None, "final_url": None}
