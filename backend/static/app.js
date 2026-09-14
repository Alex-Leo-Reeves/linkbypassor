/* Paste-link UX. Server tries first; if the network blocks the server
   (BLOCKED error), the row auto-switches to 1-click on-device mode. */
const API = window.LB_API_BASE || "";
const MAX_ROWS = 5;
const POLL_MS = 4000;
function deviceId() {
  let id = null;
  try { id = localStorage.getItem("lb_device_id"); } catch (e) {}
  if (!id) { id = "dev-" + Math.random().toString(36).slice(2,10) + Date.now().toString(36); try { localStorage.setItem("lb_device_id", id); } catch (e) {} }
  return id;
}
function headers(extra) { return Object.assign({"Content-Type":"application/json","X-Device-Id":deviceId()}, extra||{}); }
function rememberJob(job) {
  try { const ids = JSON.parse(localStorage.getItem("lb_jobs")||"[]"); if (!ids.includes(job.id)) ids.unshift(job.id); localStorage.setItem("lb_jobs", JSON.stringify(ids.slice(0,100))); } catch(e){}
}
function fmtTime(ts) { return ts ? new Date(ts*1000).toLocaleString() : ""; }
function esc(s) { return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;"); }
function copyText(t, btn) { navigator.clipboard.writeText(t).then(()=>{ const o=btn.textContent; btn.textContent="Copied \u2713"; setTimeout(()=>btn.textContent=o,1500); }); }
const rowsEl = document.getElementById("rows");
let pollers = {};
let bmCode = null;
fetch("bookmarklet.js", { cache: "no-store" }).then(function (r) { return r.text(); }).then(function (c) {
  bmCode = c;
  const b2 = document.getElementById("copyBm2");
  if (b2) b2.onclick = function () { copyText(bmCode, b2); };
}).catch(function () {});
function addRow(prefill) {
  if (rowsEl.children.length >= MAX_ROWS) { alert("Max "+MAX_ROWS+" links. Hit Bypass all to run them together."); return; }
  const div = document.createElement("div");
  div.className = "link-row";
  const inp = document.createElement("input");
  inp.type = "url"; inp.placeholder = "https://linkshortx.in/XXXXXX"; inp.value = prefill||"";
  const go = document.createElement("button");
  go.className = "btn btn-blue proceed"; go.textContent = "Bypass";
  const del = document.createElement("button");
  del.className = "remove-row"; del.title = "Remove"; del.textContent = "\u2715";
  const top = document.createElement("div"); top.className = "row-top";
  top.appendChild(inp); top.appendChild(go); top.appendChild(del);
  const st = document.createElement("p"); st.className = "status"; st.textContent = "Idle \u2014 paste a link and hit Bypass.";
  div.appendChild(top); div.appendChild(st);
  del.onclick = () => { if (div.dataset.job) clearInterval(pollers[div.dataset.job]); div.remove(); };
  go.onclick = () => startSingle(div, go);
  rowsEl.appendChild(div);
  return div;
}
function setStatus(div, html, cls) { const s = div.querySelector(".status"); s.className = "status "+(cls||""); s.innerHTML = html; }
function showSpinner(div, progressMsg) {
  let w = div.querySelector(".spinner-wrap");
  if (!w) {
    w = document.createElement("div"); w.className = "spinner-wrap";
    w.innerHTML = '<div class="spinner"></div><div><div class="spinner-text">Please hold on\u2026</div><div class="spinner-sub"></div></div>';
    div.appendChild(w);
  }
  if (progressMsg) w.querySelector(".spinner-sub").textContent = progressMsg;
}
function hideSpinner(div) { const w = div.querySelector(".spinner-wrap"); if (w) w.remove(); }
function showOneClick(url) {
  const help = document.getElementById("oneClickHelp");
  if (help) help.style.display = "block";
  if (url) {
    try {
      const pend = JSON.parse(localStorage.getItem("lb_pending")||"[]");
      if (!pend.includes(url)) pend.unshift(url);
      localStorage.setItem("lb_pending", JSON.stringify(pend.slice(0,20)));
    } catch (e) {}
  }
}
async function startJobRequest(url) {
  const r = await fetch(API+"/api/jobs", {method:"POST", headers:headers(), body:JSON.stringify({short_url:url})});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error||"Failed to start");
  rememberJob(data.job);
  return data.job;
}
async function startSingle(div, btn) {
  const url = div.querySelector("input").value.trim();
  if (!url.startsWith("http")) return alert("Paste a valid http(s) link first.");
  btn.disabled = true;
  const old = div.querySelector(".result-box"); if (old && old.remove) old.remove();
  try {
    const job = await startJobRequest(url);
    div.dataset.job = job.id;
    setStatus(div, "Working on your link now \u2014 hold on...");
    showSpinner(div, "Opening short link...");
    pollers[job.id] = setInterval(()=>pollJob(div, job.id, url), POLL_MS);
    pollJob(div, job.id, url);
  } catch(e){ setStatus(div, "\u274C "+esc(e.message), "failed"); btn.disabled = false; }
}
async function pollJob(div, jid, url) {
  try {
    const r = await fetch(API+"/api/jobs/"+jid, {headers:headers()});
    const ct = r.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      clearInterval(pollers[jid]);
      hideSpinner(div);
      setStatus(div, '⚠️ ngrok interstitial received. <a href="'+API+'" target="_blank" rel="noopener" style="color:#60a5fa">Click here to trust this ngrok URL</a>, then try again.', "failed");
      return;
    }
    const d = await r.json(); const job = d.job;
    if (!job) return;
    if (job.status==="done"||job.status==="failed") { clearInterval(pollers[jid]); hideSpinner(div); renderResult(div, job, url); loadHistory(); }
    else showSpinner(div, job.progress||"Working...");
  } catch(e) {
    clearInterval(pollers[jid]);
    hideSpinner(div);
    setStatus(div, "Error contacting server: " + (e.message || "network error"), "failed");
  }
}
function blockedRow(div, url) {
  /* Server IP is blocked: flip this row into 1-click mode automatically. */
  setStatus(div, "\u26A0\uFE0F Our server is blocked on this network — <b>1-click fix:</b> finishing on your internet instead.", "failed");
  showOneClick(url);
  let box = div.querySelector(".oneclick-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "result-box oneclick-box";
    const ol = document.createElement("ol");
    ol.style.cssText = "margin:6px 0 6px 18px;padding:0;font-size:.9rem";
    const li1 = document.createElement("li"); li1.textContent = "Tap below to copy the 1-click code";
    const li2 = document.createElement("li");
    const open = document.createElement("a"); open.href = url; open.target = "_blank"; open.rel = "noopener"; open.textContent = "Open your short link in a new tab";
    li2.appendChild(open);
    const li3 = document.createElement("li"); li3.textContent = "Paste the code in the address bar (type javascript: first) or console, hit Enter — done in ~1 min";
    ol.appendChild(li1); ol.appendChild(li2); ol.appendChild(li3);
    const acts = document.createElement("div"); acts.className = "result-actions";
    const cp = document.createElement("button"); cp.className = "btn btn-small copy1"; cp.textContent = "\uD83D\uDCCB Copy 1-click code";
    const op = document.createElement("a"); op.className = "btn btn-small open1"; op.href = url; op.target = "_blank"; op.rel = "noopener"; op.textContent = "\uD83D\uDD17 Open short link";
    cp.onclick = () => { if (bmCode) copyText(bmCode, cp); else alert("Code still loading — wait 5s and retry."); };
    acts.appendChild(cp); acts.appendChild(op);
    box.appendChild(ol); box.appendChild(acts);
    div.appendChild(box);
  }
}
function renderResult(div, job, url) {
  div.querySelector(".proceed").disabled = false;
  if (job.status==="failed") {
    const err = job.error||"unknown";
    setStatus(div, "\u274C Failed: "+esc(err.slice(0,300))+" — retrying automatically...", "failed");
    // Normal Render method: fix-push-test loop. The backend keeps evolving;
    // poll once more shortly in case a fresh deploy already resolved it.
    setTimeout(() => pollJob(div, job.id, url), 15000);
    return;
  }
  const dest = job.telegram || job.final_url || "";
  if (!dest) { setStatus(div, "\u26A0\uFE0F Finished but no link was captured. Try again.", "failed"); return; }
  setStatus(div, "\u2705 <b>Done! Your link is ready:</b>", "done");
  const box = document.createElement("div");
  box.className = "result-box";
  const label = document.createElement("div"); label.className = "label"; label.textContent = "Your link";
  const a = document.createElement("a"); a.href = dest; a.target = "_blank"; a.rel = "noopener"; a.textContent = dest;
  const acts = document.createElement("div"); acts.className = "result-actions";
  const cp = document.createElement("button"); cp.className = "btn btn-small copy"; cp.textContent = "\uD83D\uDCCB Copy";
  const op = document.createElement("a"); op.className = "btn btn-small open"; op.href = dest; op.target = "_blank"; op.rel = "noopener"; op.textContent = "\uD83D\uDD17 Open link";
  cp.onclick = ()=>copyText(dest, cp);
  acts.appendChild(cp); acts.appendChild(op);
  box.appendChild(label); box.appendChild(a); box.appendChild(acts);
  const old = div.querySelector(".result-box"); if (old && old.remove) old.remove();
  div.appendChild(box);
  box.scrollIntoView({behavior:"smooth", block:"nearest"});
}
document.getElementById("batchBtn").onclick = async (e) => {
  const btn = e.target;
  const rows = Array.from(rowsEl.querySelectorAll(".link-row"));
  const urls = rows.map(r=>r.querySelector("input").value.trim()).filter(u=>u.startsWith("http"));
  if (!urls.length) return alert("Add at least one valid link first.");
  btn.disabled = true;
  try {
    const r = await fetch(API+"/api/jobs/batch", {method:"POST", headers:headers(), body:JSON.stringify({urls:urls.slice(0,MAX_ROWS)})});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error||"Batch failed");
    data.jobs.forEach((job,i)=>{
      rememberJob(job);
      const div = rows[i]; if (!div) return;
      div.dataset.job = job.id;
      const old = div.querySelector(".result-box"); if (old && old.remove) old.remove();
      setStatus(div, "Working on your link now \u2014 hold on...");
      showSpinner(div, "Queued...");
      pollers[job.id] = setInterval(()=>pollJob(div, job.id, job.short_url), POLL_MS);
      pollJob(div, job.id, job.short_url);
    });
  } catch(err){ alert(err.message); }
  btn.disabled = false;
};
document.getElementById("addLink").onclick = ()=>addRow();
async function loadHistory() {
  const list = document.getElementById("historyList");
  try {
    const r = await fetch(API+"/api/history", {headers:headers()});
    const d = await r.json(); const jobs = d.jobs||[];
    list.innerHTML = "";
    if (!jobs.length) { const p=document.createElement("p"); p.className="muted"; p.textContent="No links yet. Bypass something above \uD83D\uDC46"; list.appendChild(p); return; }
    jobs.forEach((j)=>{
      const dest = j.telegram || j.final_url || "";
      const card = document.createElement("div");
      card.className = "hist-card";
      const short = document.createElement("div"); short.className = "short"; short.textContent = j.short_url+" ";
      const badge = document.createElement("span"); badge.className = "badge "+j.status; badge.textContent = j.status;
      short.appendChild(badge);
      const meta = document.createElement("div"); meta.className = "meta"; meta.textContent = fmtTime(j.created_at)+" \u00B7 "+(j.progress||"");
      card.appendChild(short); card.appendChild(meta);
      if (dest) {
        const dd = document.createElement("div"); dd.className = "dest";
        const a = document.createElement("a"); a.href = dest; a.target="_blank"; a.rel="noopener"; a.textContent = dest;
        dd.appendChild(a); card.appendChild(dd);
        const acts = document.createElement("div"); acts.className = "result-actions";
        const cp = document.createElement("button"); cp.className="btn btn-small copy"; cp.textContent="\uD83D\uDCCB Copy";
        const op = document.createElement("a"); op.className="btn btn-small open"; op.href=dest; op.target="_blank"; op.rel="noopener"; op.textContent="\uD83D\uDD17 Open link";
        cp.onclick = ()=>copyText(dest, cp);
        acts.appendChild(cp); acts.appendChild(op); card.appendChild(acts);
      } else if (j.status==="queued"||j.status==="running") {
        const spin = document.createElement("div"); spin.className = "spinner-wrap";
        spin.innerHTML = '<div class="spinner"></div><div><div class="spinner-text">Please hold on\u2026</div><div class="spinner-sub"></div></div>';
        spin.querySelector(".spinner-sub").textContent = j.progress||"Working...";
        card.appendChild(spin);
      } else if ((j.error||"").indexOf("BLOCKED") === 0) {
        const m2 = document.createElement("div"); m2.className="meta";
        m2.innerHTML = "\u26A0\uFE0F Server blocked — use the <b>1-click fix</b> in the bypass section above.";
        card.appendChild(m2);
      } else {
        const m2 = document.createElement("div"); m2.className="meta"; m2.textContent="\u274C "+(j.error||"Failed").slice(0,200);
        card.appendChild(m2);
      }
      list.appendChild(card);
      if ((j.status==="queued"||j.status==="running") && !pollers["h_"+j.id]) pollers["h_"+j.id]=setInterval(()=>pollHistoryJob(j.id), 8000);
    });
  } catch(e){ list.innerHTML = ""; const p=document.createElement("p"); p.className="muted"; p.textContent="Could not reach server. Is the backend running?"; list.appendChild(p); }
}
async function pollHistoryJob(jid) {
  try {
    const r = await fetch(API+"/api/jobs/"+jid, {headers:headers()});
    const ct = r.headers.get("content-type") || "";
    if (!ct.includes("application/json")) { clearInterval(pollers["h_"+jid]); return; }
    const d = await r.json();
    if (d.job && (d.job.status==="done"||d.job.status==="failed")) { clearInterval(pollers["h_"+jid]); loadHistory(); }
  } catch(e){ clearInterval(pollers["h_"+jid]); }
}
document.getElementById("refreshHistory").onclick = loadHistory;
document.getElementById("clearLocal").onclick = ()=>{ localStorage.removeItem("lb_jobs"); alert("Local view cleared. Server history for this device is kept \u2014 hit Refresh to reload it."); };
addRow();
loadHistory();
