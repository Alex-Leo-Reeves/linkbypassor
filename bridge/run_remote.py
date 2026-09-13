"""Runner-side entrypoint: executes INSIDE GitHub Actions (Azure IPs, not blocked).

Usage (called by .github/workflows/bypass.yml):
    python bridge/run_remote.py '<json payload>'

Payload keys: job_id, short_url, device_id, callback_url, bridge_secret.
Posts back: {job_id, status, telegram, gateway, final_url, error, bridge_secret}.
"""
import asyncio
import json
import sys
import urllib.request


def post_result(callback_url: str, body: dict):
    req = urllib.request.Request(
        callback_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "linkbypassor-worker"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("callback HTTP", r.status, flush=True)


async def _run(short_url: str, progress):
    # Import here so `python -m py_compile` on Render (no playwright) still works.
    # run_remote.py executes as a plain script, so the repo root must be on
    # sys.path for the `backend` package import to resolve.
    import os
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.worker import run_bypass

    return await run_bypass(short_url, progress_cb=progress)


def main():
    payload = json.loads(sys.argv[1])
    job_id = payload["job_id"]
    short_url = payload["short_url"]
    callback_url = payload["callback_url"]
    secret = payload["bridge_secret"]

    def progress(msg):
        print(f"[remote] {msg}", flush=True)

    try:
        result = asyncio.run(_run(short_url, progress))
        telegram = result.get("telegram") or result.get("final_url")
        body = {
            "job_id": job_id,
            "status": "done" if telegram else "failed",
            "progress": "Done!" if telegram else "Finished but no link found",
            "gateway": result.get("gateway"),
            "telegram": result.get("telegram"),
            "final_url": result.get("final_url"),
            "error": None if telegram else "No telegram link captured",
            "bridge_secret": secret,
        }
    except Exception as e:
        body = {
            "job_id": job_id,
            "status": "failed",
            "progress": "Failed",
            "gateway": None,
            "telegram": None,
            "final_url": None,
            "error": str(e)[:1000],
            "bridge_secret": secret,
        }
    print("RESULT " + json.dumps({k: (str(v)[:160] if v else v) for k, v in body.items() if k != "bridge_secret"}), flush=True)
    post_result(callback_url, body)


if __name__ == "__main__":
    main()
