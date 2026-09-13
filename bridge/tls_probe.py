"""TLS probe: run INSIDE GitHub Actions to learn whether Chrome-impersonated
TLS passes the linkshortx WAF from a datacenter IP.

Usage: python bridge/tls_probe.py [SHORT_URL]

Prints a verdict matrix for stock vs spoofed TLS across the entry chain:
  short link (expect 307) -> q7m4vk29 (expect 200+google URL) -> homepage.
A 403 on the FIRST request with chrome124 impersonation = hard IP block,
TLS tricks can't save the server path. A 307 = the door is open and the
pure-HTTP chain is viable server-side.
"""
import re
import sys


def probe(short_url: str):
    from curl_cffi import requests as cr

    print(f"PROBE target: {short_url}", flush=True)
    print("=" * 70, flush=True)

    results = {}

    # Test 1: stock requests-style TLS (baseline - expected 403 on datacenter)
    try:
        import urllib.request

        req = urllib.request.Request(
            short_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"},
            method="GET",
        )
        # manual: don't follow redirects, just read status
        import http.client
        from urllib.parse import urlparse

        p = urlparse(short_url)
        conn = http.client.HTTPSConnection(p.hostname, timeout=20)
        conn.request("GET", p.path or "/", headers={"User-Agent": "Mozilla/5.0", "Host": p.hostname})
        resp = conn.get_response()
        body = resp.read(2000)
        print(f"[stock-TLS] HTTP {resp.status} ({len(body)}b) {' <- BLOCKED' if resp.status == 403 else ''}", flush=True)
        results["stock"] = resp.status
        conn.close()
    except Exception as e:
        print(f"[stock-TLS] ERR {str(e)[:150]}", flush=True)
        results["stock"] = "ERR"

    # Tests 2-4: spoofed TLS fingerprints
    for imp in ["chrome124", "chrome120", "safari18_0"]:
        try:
            r = cr.get(short_url, impersonate=imp, timeout=20, allow_redirects=False)
            loc = (r.headers.get("location", "") or "")[:90]
            tag = " <- BLOCKED" if r.status_code == 403 else (" <- OPEN (307 redirect)" if r.status_code in (301, 302, 303, 307, 308) else "")
            print(f"[{imp}] HTTP {r.status_code} loc={loc!r}{tag}", flush=True)
            results[imp] = r.status_code
            if r.status_code in (301, 302, 303, 307, 308) and "q7m4vk29" in loc:
                # follow one hop: q7m4vk29 page should contain the google URL
                s = cr.Session(impersonate=imp)
                r2 = s.get(loc, timeout=20)
                has_g = "google.com/url" in r2.text
                print(f"[{imp}] q7m4vk29 -> HTTP {r2.status_code} ({len(r2.text)}b) google_url_present={has_g}", flush=True)
                results[imp + "+hop"] = (r2.status_code, has_g)
        except Exception as e:
            print(f"[{imp}] ERR {str(e)[:150]}", flush=True)
            results[imp] = "ERR"

    print("=" * 70, flush=True)
    spoofed_open = any(results.get(k) in (301, 302, 303, 307, 308) for k in ("chrome124", "chrome120", "safari18_0"))
    if spoofed_open:
        print("VERDICT: SPOOFED TLS PASSES - pure-HTTP server chain is viable", flush=True)
    else:
        print("VERDICT: HARD IP BLOCK - even Chrome TLS gets 403; server path is dead, on-device only", flush=True)
    return results


if __name__ == "__main__":
    probe(sys.argv[1] if len(sys.argv) > 1 else "https://linkshortx.in/5kST8sz")
