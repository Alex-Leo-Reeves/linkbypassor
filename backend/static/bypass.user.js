// ==UserScript==
// @name         LinkBypassor - LinkShortX Auto Bypass
// @namespace    https://linkbypassor.onrender.com
// @version      1.0.0
// @description  Automatically walks LinkShortX verification steps and lands you on the final Telegram link. Runs on your own internet, so no block pages.
// @author       Ozegbe Mike Isioma
// @match        *://linkshortx.in/*
// @match        *://www.linkshortx.in/*
// @match        *://hindisink.com/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @connect      linkbypassor.onrender.com
// ==/UserScript==
/* LinkBypassor userscript. Proven flow from automation testing: dwell ~6s per
   step page (server rejects faster submits with 'link expired'), submit #fwd
   natively on steps 1-3, click #final on step 4, wait for a.get-link to enable
   on the interstitial, click it, follow gateway -> telegram. Reports the final
   link back to History via /api/report. */
(function () {
  'use strict';
  var API = 'https://linkbypassor.onrender.com';
  var DWELL = 6000;
  var DEBUG = false;
  function log() { if (DEBUG) console.log.apply(console, ['[LinkBypassor]'].concat([].slice.call(arguments))); }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  /* small floating status pill, auto-removed on final redirect */
  var pill = null;
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
  function report(shortUrl, telegram, gateway) {
    var payload = { short_url: shortUrl, telegram: telegram, gateway: gateway, final_url: telegram || gateway };
    var did = null;
    try { did = localStorage.getItem('lb_device_id'); } catch (e) {}
    /* Belt (CORS-proof): GM_xmlhttpRequest runs in TM's privileged context
       and bypasses page CORS entirely. */
    try {
      if (typeof GM_xmlhttpRequest === 'function') {
        GM_xmlhttpRequest({
          method: 'POST',
          url: API + '/api/report',
          headers: { 'Content-Type': 'application/json', 'X-Device-Id': did || '' },
          data: JSON.stringify(payload),
          timeout: 15000,
          onload: function () { log('history reported via GM_xhr'); },
          onerror: function () { log('GM_xhr failed, trying fetch'); fallbackFetch(); },
          ontimeout: function () { log('GM_xhr timeout, trying fetch'); fallbackFetch(); }
        });
        return;
      }
    } catch (e) { log('GM_xhr threw, trying fetch'); }
    fallbackFetch();
    /* Suspenders: plain fetch works once Flask sends CORS headers
       (see @app.after_request in app.py). */
    function fallbackFetch() {
      try {
        fetch(API + '/api/report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Device-Id': did || '' },
          body: JSON.stringify(payload)
        }).catch(function () {});
      } catch (e) {}
    }
  }
  function shortOf() {
    var m = location.href.match(/https?:\/\/(www\.)?linkshortx\.in\/[A-Za-z0-9]+/);
    if (m) return m[0].replace('://www.', '://');
    try {
      var q = new URLSearchParams(location.search).get('id');
      if (q && q.indexOf('linkshortx.in/') > -1) return q.match(/https?:\/\/[^&\s]+/)[0];
    } catch (e) {}
    return location.href;
  }
  async function waitFor(sel, timeout) {
    var t0 = Date.now();
    while (Date.now() - t0 < (timeout || 30000)) {
      var el = null;
      try { el = document.querySelector(sel); } catch (e) {}
      if (el) return el;
      await sleep(500);
    }
    return null;
  }
  function killGate() {
    try {
      var g = document.getElementById('hsg');
      if (g) g.remove();
      document.documentElement.style.overflow = '';
    } catch (e) {}
  }
  /* ---- hindisink step pages (steps 1-4) ---- */
  async function runStepPage() {
    var shortUrl = shortOf();
    var fwd = await waitFor('#fwd', 15000);
    var fin = fwd ? null : await waitFor('#final', 15000);
    if (!fwd && !fin) { log('no step form found, leaving page alone'); return; }
    var m = document.body ? (document.body.innerText.match(/STEP\s+(\d)\s+OF\s+4/) || []) : [];
    var n = m[1] || (fin ? '4 (final)' : '?');
    say('step ' + n + ': holding...');
    killGate();
    await sleep(DWELL);
    if (fin) {
      say('final step: unlocking...');
      document.getElementById('final').click();
    } else {
      say('step ' + n + ': continuing...');
      document.getElementById('fwd').submit();
    }
  }
  /* ---- linkshortx interstitial (countdown -> Get Link) ---- */
  async function runInterstitial() {
    var shortUrl = shortOf();
    say('almost there: waiting for Get Link...');
    var t0 = Date.now();
    var btn = null;
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
    /* Hardened gateway capture: hook window.open BEFORE clicking, since the
       interstitial may open the gateway in a new tab (target=_blank). In that
       case location.href never changes here, so without the hook the result
       would never reach History. */
    var openedUrl = null;
    var origOpen = null;
    try {
      origOpen = window.open;
      window.open = function (url) {
        try { openedUrl = String(url || ''); } catch (e) {}
        return origOpen.apply(window, arguments);
      };
    } catch (e) {}
    try {
      btn.click();
      var t1 = Date.now();
      var gw = null, tg = null;
      while (Date.now() - t1 < 30000) {
        var u = location.href;
        if (u.indexOf('/links/gw/') > -1) gw = u;
        if (/telegram\.me|t\.me\//.test(u)) { tg = u; break; }
        /* new-tab case: gateway/telegram URL captured via the open hook */
        if (openedUrl) {
          if (openedUrl.indexOf('/links/gw/') > -1) gw = openedUrl;
          if (/telegram\.me|t\.me\//.test(openedUrl)) { tg = openedUrl; break; }
        }
        try {
          var entries = performance.getEntriesByType('resource') || [];
          for (var i = 0; i < entries.length; i++) {
            if ((entries[i].name || '').indexOf('/links/gw/') > -1) gw = entries[i].name;
          }
        } catch (e) {}
        await sleep(1000);
      }
      if (tg || gw) {
        say('done!');
        report(shortUrl, tg || gw, gw);
        /* same-tab click that didn't navigate us yet (or hook-only capture):
           take this tab there ourselves so the user isn't stranded. */
        var dest = tg || gw;
        if (dest && location.href !== dest) {
          await sleep(400);
          if (location.href !== dest) location.href = dest;
        }
      } else {
        say('link opened in a new tab - check your tabs!');
      }
    } catch (e) { say('error: ' + (e && e.message || e)); }
    finally {
      try { if (origOpen) window.open = origOpen; } catch (e) {}
    }
  }
  function route() {
    var host = location.hostname.replace(/^www\./, '');
    var path = location.pathname || '';
    log('route', host + path);
    if (host === 'linkshortx.in') {
      /* short code page (307s away) or interstitial (/XXXXXX after step 4) */
      if (/\/links\/gw\//.test(path)) return; /* gateway - let it ride to telegram */
      if (/telegram\.me|t\.me/.test(location.href)) return;
      /* interstitial has #go-link form; step pages live on hindisink */
      waitFor('#go-link', 8000).then(function (f) { if (f) runInterstitial(); });
      return;
    }
    if (host === 'hindisink.com') {
      if (/q7m4vk29/.test(path)) return; /* redirect hop, let it ride */
      runStepPage();
      return;
    }
  }
  if (document.readyState === 'complete') route();
  else window.addEventListener('load', route);
})();
