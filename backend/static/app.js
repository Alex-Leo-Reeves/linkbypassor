/* Device id: stable per browser, stored in localStorage (no login needed).
   Server (SQLite) is the source of truth; localStorage mirrors job ids so
   history survives close/reopen even if the device id were ever reset. */
const API = "";
const MAX_ROWS = 5;
const WAIT_MS = 5 * 60 * 1000;
function deviceId() {
  let id = localStorage.getItem("lb_device_id");
  if (!id) { id = "dev-" + Math.random().toString(36).slice(2,10) + Date.now().toString(36); localStorage.setItem("lb_device_id", id); }
  return id;
}
function headers(extra) { return Object.assign({"Content-Type":"application/json","X-Device-Id":deviceId()}, extra||{}); }
function rememberJob(job) {
  try { const ids = JSON.parse(localStorage.getItem("lb_jobs")||"[]"); if (!ids.includes(job.id)) ids.unshift(job.id); localStorage.setItem("lb_jobs", JSON.stringify(ids.slice(0,100))); } catch(e){}
}
function fmtTime(ts) { return ts ? new Date(ts*1000).toLocaleString() : ""; }
function copyText(t, btn) { navigator.clipboard.writeText(t).then(()=>{ const o=btn.textContent; btn.textContent="Copied \u2713"; setTimeout(()=>btn.textContent=o,1500); }); }
const rowsEl = document.getElementById("rows");
let pollers = {};
function addRow(prefill) {
  if (rowsEl.children.length >= MAX_ROWS) { alert("Max "+MAX_ROWS+" links. Hit Batch process to run them together."); return; }
  const div = document.createElement("div");
  div.className = "link-row";
  div.innerHTML = '<div class="row-top"><input type="url" placeholder="https://linkshortx.in/XXXXXX" value="'+(prefill||"").replace(/"/g,"&quot;")+'" /><button class="btn btn-blue proceed">Proceed</button><button class="remove-row" title="Remove">\u2715</button></div><p class="status">Idle \u2014 paste a link and hit Proceed (or Batch process below).</p>';
  div.querySelector(".remove-row").onclick = () => { if (div.dataset.job) clearInterval(pollers[div.dataset.job]); div.remove(); };
  div.querySelector(".proceed").onclick = (e) => startSingle(div, e.target);
  rowsEl.appendChild(div);
  return div;
}
function setStatus(div, html, cls) { const s = div.querySelector(".status"); s.className = "status "+(cls||""); s.innerHTML = html; }
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
  try {
    const job = await startJobRequest(url);
    div.dataset.job = job.id;
    const target = Date.now()+WAIT_MS;
    pollers[job.id] = setInterval(()=>pollJob(div, job.id, target), 5000);
    setStatus(div, '\u23F3 Job started! Come back in <span class="countdown" data-t="'+target+'">5:00</span>. Safe to close this tab \u2014 saved in <a href="#history">History</a>.');
    pollJob(div, job.id, target); tickCountdowns();
  } catch(e){ setStatus(div, "\u274C "+e.message, "failed"); btn.disabled = false; }
}
async function pollJob(div, jid, target) {
  try {
    const r = await fetch(API+"/api/jobs/"+jid, {headers:headers()});
    const d = await r.json(); const job = d.job;
    if (!job) return;
    if (job.status==="done"||job.status==="failed") { clearInterval(pollers[jid]); renderResult(div, job); loadHistory(); }
    else setStatus(div, '\u23F3 <b>'+(job.progress||"Working...")+"</b> \u2014 come back in <span class='countdown' data-t='"+(target||Date.now()+WAIT_MS)+"'>~5 min</span>. Saved in <a href='#history'>History</a>.");
  } catch(e){}
}
function renderResult(div, job) {
  div.querySelector(".proceed").disabled = false;
  if (job.status==="failed") { setStatus(div, "\u274C Failed: "+((job.error||"unknown").slice(0,200)), "failed"); return; }
  const dest = job.telegram || job.final_url || "";
  setStatus(div, "\u2705 <b>Done!</b>", "done");
  const box = document.createElement("div");
  box.className = "result-box";
  box.innerHTML = '<div class="label">Your link</div><a href="'+dest+'" target="_blank" rel="noopener">'+dest+'</a><div class="result-actions"><button class="btn btn-small copy">\uD83D\uDCCB Copy</button><a class="btn btn-small open" href="'+dest+'" target="_blank" rel="noopener">\uD83D\uDD17 Open link</a></div>';
  const old = div.querySelector(".result-box"); if (old) old.remove();
  div.appendChild(box);
  box.querySelector(".copy").onclick = (e)=>copyText(dest, e.target);
}
function tickCountdowns() {
  document.querySelectorAll(".countdown[data-t]").forEach((el)=>{
    const left = Math.max(0, +el.dataset.t - Date.now());
    const m = Math.floor(left/60000), s = Math.floor((left%60000)/1000);
    el.textContent = m+":"+String(s).padStart(2,"0");
  });
}
setInterval(tickCountdowns, 1000);
document.getElementById("batchBtn").onclick = async (e) => {
  const btn = e.target;
  const urls = Array.from(rowsEl.querySelectorAll(".link-row input")).map(i=>i.value.trim()).filter(u=>u.startsWith("http"));
  if (!urls.length) return alert("Add at least one valid link first.");
  btn.disabled = true;
  try {
    const r = await fetch(API+"/api/jobs/batch", {method:"POST", headers:headers(), body:JSON.stringify({urls:urls.slice(0,MAX_ROWS)})});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error||"Batch failed");
    const divs = Array.from(rowsEl.querySelectorAll(".link-row")).slice(0, data.jobs.length);
    data.jobs.forEach((job,i)=>{
      rememberJob(job);
      const div = divs[i]; if (!div) return;
      div.dataset.job = job.id;
      const target = Date.now()+WAIT_MS;
      pollers[job.id] = setInterval(()=>pollJob(div, job.id, target), 5000);
      setStatus(div, '\u23F3 Batch started! Come back in <span class="countdown" data-t="'+target+'">5:00</span>. Saved in <a href="#history">History</a>.');
      pollJob(div, job.id, target);
    });
    tickCountdowns();
  } catch(err){ alert(err.message); }
  btn.disabled = false;
};
document.getElementById("addLink").onclick = ()=>addRow();
async function loadHistory() {
  const list = document.getElementById("historyList");
  try {
    const r = await fetch(API+"/api/history", {headers:headers()});
    const d = await r.json(); const jobs = d.jobs||[];
    if (!jobs.length) { list.innerHTML = '<p class="muted">No links yet. Bypass something above \uD83D\uDC46</p>'; return; }
    list.innerHTML = "";
    jobs.forEach((j)=>{
      const dest = j.telegram || j.final_url || "";
      const card = document.createElement("div");
      card.className = "hist-card";
      card.innerHTML = '<div class="short">'+j.short_url+' <span class="badge '+j.status+'">'+j.status+'</span></div><div class="meta">'+fmtTime(j.created_at)+' \u00B7 '+(j.progress||"")+'</div>'+(dest?'<div class="dest"><a href="'+dest+'" target="_blank" rel="noopener">'+dest+'</a></div><div class="result-actions"><button class="btn btn-small copy">\uD83D\uDCCB Copy</button><a class="btn btn-small open" href="'+dest+'" target="_blank" rel="noopener">\uD83D\uDD17 Open link</a></div>':'<div class="meta">Still working \u2014 check back in a few minutes.</div>');
      const cp = card.querySelector(".copy"); if (cp) cp.onclick=(e)=>copyText(dest, e.target);
      list.appendChild(card);
      if ((j.status==="queued"||j.status==="running") && !pollers[j.id]) pollers[j.id]=setInterval(()=>pollHistoryJob(j.id), 8000);
    });
  } catch(e){ list.innerHTML = '<p class="muted">Could not reach server. Is the backend running?</p>'; }
}
async function pollHistoryJob(jid) {
  try {
    const r = await fetch(API+"/api/jobs/"+jid, {headers:headers()});
    const d = await r.json();
    if (d.job && (d.job.status==="done"||d.job.status==="failed")) { clearInterval(pollers[jid]); loadHistory(); }
  } catch(e){}
}
document.getElementById("refreshHistory").onclick = loadHistory;
document.getElementById("clearLocal").onclick = ()=>{ localStorage.removeItem("lb_jobs"); alert("Local view cleared. Server history for this device is kept \u2014 hit Refresh to reload it."); };
addRow();
loadHistory();
