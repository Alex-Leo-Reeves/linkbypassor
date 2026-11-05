"""Flask backend for Render. Serves the UI + job API. SQLite storage, no external DB."""
import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory

from db import _connect, create_job, ensure_device, get_job, init_db, list_jobs, update_job
from worker import run_bypass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
executor = ThreadPoolExecutor(max_workers=int(os.environ.get("MAX_WORKERS", "3")))
init_db()

@app.route("/api/health")
def health():
    return jsonify({"ok": True})

def _claim_next_job():
    """Atomically claim the oldest queued job (mark as running)."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if not row:
        conn.close()
        return None
    jid = row["id"]
    now = int(time.time())
    conn.execute(
        "UPDATE jobs SET status='running', progress='Claimed by worker...', updated_at=? WHERE id=? AND status='queued'",
        (now, jid),
    )
    conn.commit()
    confirmed = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    if confirmed and confirmed["status"] == "running":
        return dict(confirmed)
    return None


def _background_worker():
    """Poll for queued jobs and run bypass. Runs on the laptop (residential IP)."""
    import time as _time
    print("[worker] background thread started", flush=True)
    while True:
        try:
            job = _claim_next_job()
            if not job:
                _time.sleep(3)
                continue
            jid = job["id"]
            short_url = job["short_url"]
            print(f"[worker] claimed job {jid} ({short_url})", flush=True)
            _run_job(jid, short_url)
        except Exception as e:
            print(f"[worker] error: {str(e)[:200]}", flush=True)
            _time.sleep(5)


def start_worker_if_enabled():
    """Start the background worker thread if enabled."""
    import time as _time
    if os.environ.get("WORKER_ENABLED", "true").lower() in ("1", "true", "yes"):
        t = threading.Thread(target=_background_worker, daemon=True)
        t.start()
        print("[worker] enabled", flush=True)
    else:
        print("[worker] disabled (UI-only mode)", flush=True)


@app.get("/api/worker/status")
def worker_status():
    enabled = os.environ.get("WORKER_ENABLED", "true").lower() in ("1", "true", "yes")
    conn = _connect()
    queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
    conn.close()
    return jsonify({"enabled": enabled, "queued": int(queued), "running": int(running)})





@app.after_request
def _cors(resp):
    # Lets the on-device userscript/bookmarklet POST /api/report from
    # linkshortx.in / hindisink.com via plain fetch (belt: GM_xmlhttpRequest
    # in the userscript bypasses CORS anyway; this is the suspenders).
    resp.headers["Access-Control-Allow-Origin"] = "*"
    # ngrok-skip-browser-warning: lets the Render UI (a different origin) call
    # the laptop API through the ngrok tunnel without hitting ngrok's free-tier
    # browser-warning interstitial (ERR_NGROK_6024). Must be whitelisted here or
    # the CORS preflight for GET requests is rejected by the browser.
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Device-Id, ngrok-skip-browser-warning"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/api/report", methods=["OPTIONS"])
def _report_preflight():
    return ("", 204)


def device_id_from_request():
    did = request.headers.get("X-Device-Id", "") or (request.get_json(silent=True) or {}).get("device_id", "")
    return ensure_device(did)


def _run_job(jid, short_url):
    def prog(msg):
        update_job(jid, status="running", progress=msg)

    # Single server-side path, zero user steps: the local Playwright chain.
    # NOTE: the old curl_cffi "fast path" (run_curl_bypass, ~40s) was removed -
    # it never returned a telegram link (the interstitial needs a real browser),
    # so every job discarded its result and re-ran from scratch. Dropping it
    # saves ~40s per job with no functional change.
    # NOTE: the GitHub Actions bridge is intentionally NOT in this path:
    # Azure runners 403 identically, and dispatching only burns minutes
    # before the same failure. See PROBLEM.md.
    update_job(jid, status="running", progress="Starting...")
    # Local Playwright full chain on the *requesting* host's network (the
    # laptop via ngrok for the live site, so a residential IP bypasses the
    # shortener's datacenter-403 block).
    try:
        result = asyncio.run(run_bypass(short_url, progress_cb=prog))
        telegram = result.get("telegram") or result.get("final_url")
        update_job(
            jid,
            status="done" if telegram else "failed",
            progress="Done!" if telegram else "Finished but no link found",
            gateway=result.get("gateway"),
            telegram=result.get("telegram"),
            final_url=result.get("final_url"),
            error=None if telegram else "No telegram link captured",
        )
    except Exception as e:
        update_job(jid, status="failed", progress="Failed", error=str(e)[:1000])


@app.route("/api/probe")
def probe():
    """Diagnostics: test outbound IPv4 vs IPv6 + Cloudflare Worker candidate info."""
    import subprocess
    short = "https://linkshortx.in/5kST8sz"
    results = {}
    try:
        r = subprocess.run(
            ["curl", "-4", "-s", "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}",
             "--max-time", "15", short],
            capture_output=True, text=True, timeout=20
        )
        results["ipv4"] = r.stdout.strip()
    except Exception as e:
        results["ipv4"] = f"ERR {str(e)[:80]}"
    try:
        r = subprocess.run(
            ["curl", "-6", "-s", "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}",
             "--max-time", "15", short],
            capture_output=True, text=True, timeout=20
        )
        results["ipv6"] = r.stdout.strip()
    except Exception as e:
        results["ipv6"] = f"ERR {str(e)[:80]}"
    return jsonify({
        "results": results,
        "host": os.environ.get("HOSTNAME", "unknown"),
        "render_region": os.environ.get("RENDER_REGION", "unknown"),
        "note": "200/307 = clean; 403 = datacenter block"
    })



@app.post("/api/jobs")
def start_job():
    data = request.get_json(silent=True) or {}
    short_url = (data.get("short_url") or "").strip()
    if not short_url.startswith("http"):
        return jsonify({"error": "Provide a valid http(s) link"}), 400
    did = device_id_from_request()
    job = create_job(did, short_url)
    executor.submit(_run_job, job["id"], short_url)
    return jsonify({"device_id": did, "job": job})


@app.post("/api/jobs/batch")
def start_batch():
    data = request.get_json(silent=True) or {}
    urls = [u.strip() for u in (data.get("urls") or []) if u and u.strip().startswith("http")]
    urls = urls[:5]
    if not urls:
        return jsonify({"error": "Provide 1-5 valid links"}), 400
    did = device_id_from_request()
    jobs = []
    for u in urls:
        job = create_job(did, u)
        executor.submit(_run_job, job["id"], u)
        jobs.append(job)
    return jsonify({"device_id": did, "jobs": jobs})


@app.get("/api/jobs/<jid>")
def job_status(jid):
    job = get_job(jid)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({"job": job})


@app.get("/api/history")
def history():
    did = request.headers.get("X-Device-Id", "") or request.args.get("device_id", "")
    if not did:
        return jsonify({"device_id": None, "jobs": []})
    ensure_device(did)
    return jsonify({"device_id": did, "jobs": list_jobs(did)})


@app.route("/api/bridge/result", methods=["POST", "OPTIONS"])
def bridge_result():
    """Webhook: GitHub Actions worker posts the bypass result here.
    Signed with BRIDGE_SECRET so random callers can't forge completions."""
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    secret = (data.get("bridge_secret") or "").strip()
    expected = (os.environ.get("BRIDGE_SECRET") or "").strip()
    if not expected or secret != expected:
        return jsonify({"error": "unauthorized"}), 401
    jid = (data.get("job_id") or "").strip()
    job = get_job(jid) if jid else None
    if not job:
        return jsonify({"error": "job not found"}), 404
    status = data.get("status") or "failed"
    update_job(
        jid,
        status="done" if status == "done" else "failed",
        progress=data.get("progress") or ("Done!" if status == "done" else "Failed"),
        gateway=data.get("gateway"),
        telegram=data.get("telegram"),
        final_url=data.get("final_url"),
        error=data.get("error"),
    )
    return jsonify({"ok": True, "job": get_job(jid)})


@app.post("/api/report")
def report():
    """Bookmarklet hook: the on-device script found the final link (using the
    user's residential IP) and reports it so it lands in device history."""
    data = request.get_json(silent=True) or {}
    short_url = (data.get("short_url") or "").strip()
    telegram = (data.get("telegram") or "").strip()
    gateway = (data.get("gateway") or "").strip()
    final_url = (data.get("final_url") or telegram or "").strip()
    if not short_url.startswith("http") or not (telegram or gateway):
        return jsonify({"error": "short_url + telegram/gateway required"}), 400
    did = device_id_from_request()
    job = create_job(did, short_url)
    update_job(
        job["id"],
        status="done",
        progress="Done via 1-click bypass!",
        gateway=gateway or None,
        telegram=telegram or None,
        final_url=final_url or None,
    )
    return jsonify({"device_id": did, "job": get_job(job["id"])})


@app.get("/bypass.user.js")
def userscript():
    # Served with a JS content-type + suggestive filename so Tampermonkey
    # offers a 1-click Install screen when users hit the install button.
    resp = send_from_directory(STATIC_DIR, "bypass.user.js", mimetype="application/javascript")
    resp.headers["Content-Disposition"] = "inline; filename=linkbypassor.user.js"
    return resp


@app.get("/googlea03eddeedac715ac.html")
def google_verify():
    return send_from_directory(STATIC_DIR, "googlea03eddeedac715ac.html", mimetype="text/html")


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


    start_worker_if_enabled()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
