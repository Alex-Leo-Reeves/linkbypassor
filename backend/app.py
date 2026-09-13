"""Flask backend for Render. Serves the UI + job API. SQLite storage, no external DB."""
import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory

from .db import create_job, ensure_device, get_job, init_db, list_jobs, update_job
from .worker import run_bypass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")
executor = ThreadPoolExecutor(max_workers=int(os.environ.get("MAX_WORKERS", "3")))
init_db()


@app.after_request
def _cors(resp):
    # Lets the on-device userscript/bookmarklet POST /api/report from
    # linkshortx.in / hindisink.com via plain fetch (belt: GM_xmlhttpRequest
    # in the userscript bypasses CORS anyway; this is the suspenders).
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Device-Id"
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

    # Render-only strategy order (all server-side, zero user steps):
    #  0. curl_cffi HTTP fast path (no browser, ~40s). Falls through fast
    #     on any HTTP-* error (including HTTP-403 datacenter block).
    #  1. Local Playwright full chain (works wherever the host IP passes).
    # NOTE: the GitHub Actions bridge is intentionally NOT in this path:
    # Azure runners 403 identically, and dispatching only burns minutes
    # before the same failure. See PROBLEM.md.
    update_job(jid, status="running", progress="Starting...")
    # Strategy 0: HTTP fast path first (cheap, ~40s). Any HTTP-* error means
    # the datacenter IP is rejected at that stage -> fall through to browser.
    # A non-HTTP exception (missing lib, bug) is also non-fatal: fall through.
    curl_res = None
    try:
        from .curl_path import run_curl_bypass

        try:
            prog("Trying HTTP fast path...")
            curl_res = run_curl_bypass(short_url, progress_cb=prog)
        except Exception as e:
            if str(e).startswith("HTTP-"):
                prog(f"Fast path skipped ({e}); using browser...")
            else:
                prog(f"Fast path unavailable ({str(e)[:120]}); using browser...")
    except Exception as e:
        prog(f"Fast path unavailable ({str(e)[:120]}); using browser...")
    if curl_res and curl_res.get("telegram"):
        tg = curl_res["telegram"]
        update_job(
            jid, status="done", progress="Done!",
            gateway=curl_res.get("gateway"), telegram=tg,
            final_url=curl_res.get("final_url") or tg,
        )
        return
    if curl_res:
        prog(f"Fast path through step 3 ({(curl_res.get('final_href') or '')[:60]}); browser takes step 4...")
    # Strategy 1: local Playwright full chain. The browser binary path is
    # pinned at build time (render.yaml) + forced in worker.py; if the host
    # IP is blocked the worker raises HTTP-403 and the job fails honestly.
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


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
