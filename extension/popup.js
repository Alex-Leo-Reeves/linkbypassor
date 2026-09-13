/* Popup: paste link -> open in new tab (content script auto-runs there on
   the user's residential IP) -> poll history until the result lands. */
const API = 'https://linkbypassor.onrender.com';
const $ = (id) => document.getElementById(id);
async function deviceId() {
  const got = await chrome.storage.local.get('lb_device_id');
  if (got.lb_device_id) return got.lb_device_id;
  const id = 'dev-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  await chrome.storage.local.set({ lb_device_id: id });
  return id;
}
function setStatus(t, cls) { const s = $('st'); s.className = 'status ' + (cls || ''); s.textContent = t; }
$('go').onclick = async () => {
  const url = $('url').value.trim();
  if (!url.startsWith('http')) { setStatus('Paste a valid http(s) link first.', 'failed'); return; }
  const btn = $('go'); btn.disabled = true;
  $('res').textContent = ''; $('acts').style.display = 'none';
  setStatus('\u23F3 Opening link... the bypass runs itself (~1 min).');
  await chrome.tabs.create({ url });
  setStatus('\u23F3 Bypass running in the new tab - hold on, result appears here...');
  const did = await deviceId();
  const t0 = Date.now();
  const timer = setInterval(async () => {
    if (Date.now() - t0 > 5 * 60 * 1000) { clearInterval(timer); setStatus('Still nothing after 5 min - check the tab or try again.', 'failed'); btn.disabled = false; return; }
    try {
      const r = await fetch(API + '/api/history', { headers: { 'X-Device-Id': did } });
      const d = await r.json();
      const hit = (d.jobs || []).find((j) => j.short_url === url && (j.telegram || j.final_url));
      if (hit) {
        clearInterval(timer);
        const dest = hit.telegram || hit.final_url;
        setStatus('\u2705 Done! Your link is ready:', 'done');
        const a = document.createElement('a'); a.href = dest; a.target = '_blank'; a.rel = 'noopener'; a.textContent = dest;
        $('res').appendChild(a);
        $('acts').style.display = 'flex';
        $('op').href = dest;
        $('cp').onclick = () => navigator.clipboard.writeText(dest).then(() => { $('cp').textContent = 'Copied \u2713'; });
        btn.disabled = false;
      }
    } catch (e) {}
  }, 5000);
};
