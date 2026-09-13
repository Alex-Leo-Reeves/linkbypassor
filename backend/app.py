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


def device_id_from_request():
    did = request.headers.get("X-Device-Id", "") or (request.get_json(silent=True) or {}).get("device_id", "")
    return ensure_device(did)


def _run_job(jid, short_url):
    def prog(msg):
        update_job(jid, status="running", progress=msg)

    update_job(jid, status="running", progress="Starting...")
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


@app.get("/googlea03eddeedac715ac.html")
def google_verify():
    return send_from_directory(STATIC_DIR, "googlea03eddeedac715ac.html", mimetype="text/html")


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
