/* LinkBypassor content script (Manifest V3). Same proven flow as bypass.user.js:
   dwell ~6s per step (server rejects faster submits), submit #fwd on steps 1-3,
   click #final on step 4, wait for a.get-link on the interstitial, follow
   gateway -> telegram. Reports the final link to History via plain fetch
   (content scripts are CORS-exempt for host-permissioned origins). */
(function () {
  'use strict';
  const API = 'https://linkbypassor.onrender.com';
  const DWELL = 6000;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let pill = null;
  function say(t) {
    try {
      if (!pill) {
        pill = document.createElement('div');
        pill.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#1a56db;color:#fff;font:700 14px/1.4 system-ui,Arial;padding:10px 18px;border-radius:999px;box-shadow:0 8px 24px rgba(0,0,0,.35)';
        document.body.appendChild(pill);
      }
      pill.textContent = '\u26A1 LinkBypassor: ' + t;
    } catch (e) {}
  }
  async function deviceId() {
    try {
      const got = await chrome.storage.local.get('lb_device_id');
      if (got.lb_device_id) return got.lb_device_id;
      const id = 'dev-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      await chrome.storage.local.set({ lb_device_id: id });
      return id;
    } catch (e) { return ''; }
  }
  async function report(shortUrl, telegram, gateway) {
    try {
      const did = await deviceId();
      await fetch(API + '/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': did || '' },
        body: JSON.stringify({ short_url: shortUrl, telegram, gateway, final_url: telegram || gateway })
      });
    } catch (e) {}
  }
  function shortOf() {
    const m = location.href.match(/https?:\/\/(www\.)?linkshortx\.in\/[A-Za-z0-9]+/);
    if (m) return m[0].replace('://www.', '://');
    try {
      const q = new URLSearchParams(location.search).get('id');
      if (q && q.includes('linkshortx.in/')) return q.match(/https?:\/\/[^&\s]+/)[0];
    } catch (e) {}
    return location.href;
  }
  async function waitFor(sel, timeout) {
    const t0 = Date.now();
    while (Date.now() - t0 < (timeout || 30000)) {
      let el = null;
      try { el = document.querySelector(sel); } catch (e) {}
      if (el) return el;
      await sleep(500);
    }
    return null;
  }
  function killGate() {
    try {
      const g = document.getElementById('hsg');
      if (g) g.remove();
      document.documentElement.style.overflow = '';
    } catch (e) {}
  }
  async function runStepPage() {
    const shortUrl = shortOf();
    const fwd = await waitFor('#fwd', 15000);
    const fin = fwd ? null : await waitFor('#final', 15000);
    if (!fwd && !fin) return;
    const m = document.body ? (document.body.innerText.match(/STEP\s+(\d)\s+OF\s+4/) || []) : [];
    const n = m[1] || (fin ? '4 (final)' : '?');
    say('step ' + n + ': holding...');
    killGate();
    await sleep(DWELL);
    if (fin) { say('final step: unlocking...'); document.getElementById('final').click(); }
    else { say('step ' + n + ': continuing...'); document.getElementById('fwd').submit(); }
  }
  async function runInterstitial() {
    const shortUrl = shortOf();
    say('almost there: waiting for Get Link...');
    const t0 = Date.now();
    let btn = null;
    while (Date.now() - t0 < 90000) {
      try {
        btn = document.querySelector('a.get-link');
        if (btn && !((btn.className || '').match(/(^|\s)disabled(\s|$)/))) break;
      } catch (e) {}
      btn = null;
      await sleep(1000);
    }
    if (!btn) { say('Get Link never enabled - reload and try again'); return; }
    say('opening your link...');
    let openedUrl = null;
    let origOpen = null;
    try {
      origOpen = window.open;
      window.open = function (url) {
        try { openedUrl = String(url || ''); } catch (e) {}
        return origOpen.apply(window, arguments);
      };
    } catch (e) {}
    try {
      btn.click();
      const t1 = Date.now();
      let gw = null, tg = null;
      while (Date.now() - t1 < 30000) {
        const u = location.href;
        if (u.includes('/links/gw/')) gw = u;
        if (/telegram\.me|t\.me\//.test(u)) { tg = u; break; }
        if (openedUrl) {
          if (openedUrl.includes('/links/gw/')) gw = openedUrl;
          if (/telegram\.me|t\.me\//.test(openedUrl)) { tg = openedUrl; break; }
        }
        try {
          for (const e of performance.getEntriesByType('resource') || []) {
            if ((e.name || '').includes('/links/gw/')) gw = e.name;
          }
        } catch (e) {}
        await sleep(1000);
      }
      if (tg || gw) {
        say('done!');
        await report(shortUrl, tg || gw, gw);
        const dest = tg || gw;
        if (dest && location.href !== dest) { await sleep(400); if (location.href !== dest) location.href = dest; }
      } else { say('link opened in a new tab - check your tabs!'); }
    } catch (e) { say('error: ' + (e && e.message || e)); }
    finally { try { if (origOpen) window.open = origOpen; } catch (e) {} }
  }
  function route() {
    const host = location.hostname.replace(/^www\./, '');
    const path = location.pathname || '';
    if (host === 'linkshortx.in') {
      if (/\/links\/gw\//.test(path)) return;
      if (/telegram\.me|t\.me/.test(location.href)) return;
      waitFor('#go-link', 8000).then((f) => { if (f) runInterstitial(); });
      return;
    }
    if (host === 'hindisink.com') {
      if (/q7m4vk29/.test(path)) return;
      runStepPage();
    }
  }
  route();
})();
