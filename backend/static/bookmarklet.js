/* LinkBypassor bookmarklet - runs INSIDE the user's tab, so it uses the
   user's residential IP (Render datacenter IPs get HTTP 403). Paste it in
   the console on the short-link page, or save as a bookmarklet and click it. */
(function () {
  'use strict';
  var API = 'https://linkbypassor.onrender.com';
  var DWELL = 6000;
  /* floating status pill */
  var pill = document.createElement('div');
  pill.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#1a56db;color:#fff;font:700 14px/1.4 system-ui,Arial;padding:10px 18px;border-radius:999px;box-shadow:0 8px 24px rgba(0,0,0,.35)';
  document.body.appendChild(pill);
  function say(t) { pill.textContent = '\u26A1 LinkBypassor: ' + t; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function report(shortUrl, telegram, gateway) {
    try {
      var did = null;
      try { did = localStorage.getItem('lb_device_id'); } catch (e) {}
      fetch(API + '/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': did || '' },
        body: JSON.stringify({ short_url: shortUrl, telegram: telegram, gateway: gateway, final_url: telegram })
      }).catch(function () {});
    } catch (e) {}
  }
  function shortOf() {
    var m = location.href.match(/https?:\/\/linkshortx\.in\/[A-Za-z0-9]+/);
    return m ? m[0] : location.href;
  }
  async function waitFor(sel, timeout) {
    var t0 = Date.now();
    while (Date.now() - t0 < (timeout || 25000)) {
      var el = document.querySelector(sel);
      if (el) return el;
      await sleep(500);
    }
    return null;
  }
  async function run() {
    var shortUrl = shortOf();
    /* steps 1-3: dwell then submit #fwd */
    for (var i = 1; i <= 3; i++) {
      var fwd = await waitFor('#fwd', 30000);
      if (!fwd) { say('step ' + i + ': no form found - did the link expire?'); return; }
      say('step ' + i + ' of 4: holding...');
      var gate = document.getElementById('hsg');
      if (gate) gate.remove();
      document.documentElement.style.overflow = '';
      await sleep(DWELL);
      say('step ' + i + ' of 4: going...');
      document.getElementById('fwd').submit();
      await sleep(4000);
    }
    /* step 4: dwell then click #final */
    var fin = await waitFor('#final', 30000);
    if (!fin) { say('final step button missing - link may have expired'); return; }
    say('final step: unlocking...');
    var g2 = document.getElementById('hsg');
    if (g2) g2.remove();
    await sleep(DWELL);
    document.getElementById('final').click();
    await sleep(5000);
    /* interstitial: wait for Get Link to enable, then click */
    say('almost there: waiting for Get Link...');
    var t0 = Date.now();
    var btn = null;
    while (Date.now() - t0 < 60000) {
      btn = document.querySelector('a.get-link');
      if (btn && !(btn.className || '').match(/disabled/)) break;
      btn = null;
      await sleep(1000);
    }
    if (!btn) { say('Get Link never enabled - try reloading and clicking again'); return; }
    say('opening your link...');
    btn.click();
    /* watch for the gateway/telegram redirect */
    t0 = Date.now();
    var gw = null, tg = null;
    while (Date.now() - t0 < 30000) {
      var u = location.href;
      if (u.indexOf('/links/gw/') > -1) gw = u;
      if (/telegram\.me|t\.me\//.test(u)) { tg = u; break; }
      await sleep(1000);
    }
    if (tg || gw) {
      say('done! taking you there...');
      report(shortUrl, tg || gw, gw);
      await sleep(800);
      location.href = tg || gw;
    } else {
      say('hmm - no redirect seen. The link may have opened in a new tab.');
    }
  }
  run().catch(function (e) { say('error: ' + (e && e.message || e)); });
})();
