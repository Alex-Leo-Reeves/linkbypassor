# The Problem (and why the current method is not ideal)

> Status: **unsolved at the infrastructure level.** Everything below is the
> honest state of the project. The current UX works, but it is a workaround —
> not the product.

## 1. The core problem: the server's IP is banned

- `linkshortx.in` serves Render's datacenter IPs an **HTTP 403 "Access Denied"**
  page on the very first request. Proven in production logs:
  `chain=[(403, 'https://linkshortx.in/5kST8sz')]`, `title=Access Denied`,
  1430-byte block page — no redirect ever happens.
- The exact same code on a residential IP gets `307 → hindisink → google →
  article` and completes fine. So this is **not a code bug**. It is an
  **IP-reputation block** by the link shortener (via its Hostinger CDN layer).
- Consequence: **no server-side automation can work from Render's free tier**,
  no matter how good the Playwright script is. The browser launches correctly
  (full chromium, correct path), navigates correctly — and is refused at the
  door because of where the request comes from.

## 2. Why there is no free server-side fix

An IP address is stamped by *where code physically runs* — backend code can
never borrow the user's residential IP. The options that were evaluated:

| Option | Verdict |
|---|---|
| Residential proxy (`PROXY_URL` hook is already in `worker.py`) | ✅ Would fix it fully. Costs ~$3–5/mo. **No budget — parked.** |
| Tor / free proxy lists / Google-Translate wrappers | ❌ Blocked harder than datacenters, 3–5× slower, breaks the cookie/session chain. Worse than nothing. |
| Cloudflare Workers / Apps Script free tier | ❌ Still datacenter IPs. Same 403. |
| Headers / user-agent / flag tricks | ❌ An IP-level 403 ignores all of these. |

## 3. What the current method is (and why it is not ideal)

The live site does **server-tries-first, 1-click-fallback-on-BLOCKED**:

1. User pastes a link, hits Bypass. Server attempts the full Playwright run.
2. If the server is blocked, the row auto-flips into "1-click mode": copy a JS
   snippet, open the short link in a new tab, paste the snippet in the address
   bar (typing `javascript:` first) or console. The script then walks the
   steps on the user's IP and reports the result back to History.

Why this is **not ideal / not production worthy**:

- **Two-step UX for 100% of Render users.** The server path never succeeds
  from Render, so *every* user hits the fallback. The "automatic" primary
  path is dead weight — users always do manual work.
- **Pasting `javascript:` URLs is hostile UX.** Most users have never opened
  DevTools. Mobile browsers make this actively painful (address-bar JS is
  stripped, consoles don't exist). Expect massive drop-off.
- **A second tab breaks the magic.** Paste → spinner → "now go over there and
  do this" feels broken, even with numbered steps. The product promise is
  "paste link, get link" and we don't deliver it.
- **No batch story.** The old 5-link parallel design is UI-complete but
  pointless while the server can't run a single job.
- **Fragile coupling.** The snippet duplicates the step logic in a second
  codebase (`bookmarklet.js` vs `worker.py`) — every site change must be
  fixed twice.

## 4. What "ideal" actually looks like

- **If budget appears:** set `PROXY_URL` in Render env. Delete the fallback
  UI. Paste → spinner (~1 min) → result. Done. The hook is already coded.
- **If staying free:** a one-time-install **browser extension** (paste works
  forever after install), or accept the site as a **guided-manual tool**
  rather than an automation product.
- **Either way:** the server Playwright stack (`worker.py`, gunicorn threads,
  Chromium on 512MB RAM) should be revisited — it is heavy, slow, and
  currently serves only blocked requests.

---
*Written 2026-09-13. Revisit when proxy budget exists or the shortener lifts
the datacenter block.*
