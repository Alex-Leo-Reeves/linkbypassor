"""GitHub Actions Worker Bridge.

Render's datacenter IP gets HTTP 403 from linkshortx.in, so the bypass runs
on a GitHub Actions runner (Azure IP pool, free) instead. Flow:

  user pastes link -> Flask creates job (queued) -> dispatch workflow via
  GitHub repository_dispatch -> runner executes bridge/run_remote.py with
  real Playwright -> runner POSTs result to /api/bridge/result (signed with
  BRIDGE_SECRET) -> job flips to done/failed -> UI polling picks it up.

Env required on Render:
  GH_REPO        e.g. Alex-Leo-Reeves/linkbypassor
  GH_TOKEN       PAT (classic) with `repo` scope (needs workflow dispatch)
  BRIDGE_SECRET  shared secret, also set as GitHub Actions secret
  RENDER_URL     e.g. https://linkbypassor.onrender.com (callback target)
"""
import os
import urllib.request
import json

TIMEOUT = 20


def bridge_configured() -> bool:
    return bool(os.environ.get("GH_REPO") and os.environ.get("GH_TOKEN") and os.environ.get("BRIDGE_SECRET"))


def callback_url() -> str:
    base = (os.environ.get("RENDER_URL") or "").rstrip("/") or "https://linkbypassor.onrender.com"
    return base + "/api/bridge/result"


def dispatch_bypass(job_id: str, short_url: str, device_id: str) -> tuple[bool, str]:
    """Fire repository_dispatch event. Returns (ok, message)."""
    repo = os.environ.get("GH_REPO", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    secret = os.environ.get("BRIDGE_SECRET", "").strip()
    if not (repo and token and secret):
        return False, "bridge not configured (GH_REPO/GH_TOKEN/BRIDGE_SECRET)"
    payload = {
        "event_type": "bypass-link",
        "client_payload": {
            "job_id": job_id,
            "short_url": short_url,
            "device_id": device_id,
            "callback_url": callback_url(),
            "bridge_secret": secret,
        },
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/dispatches",
        data=json.dumps(payload).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "linkbypassor-bridge",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status in (200, 201, 202, 204):
                return True, f"dispatched (HTTP {r.status})"
            return False, f"dispatch HTTP {r.status}"
    except Exception as e:
        # urllib raises HTTPError (has .code) on non-2xx
        code = getattr(e, "code", "?")
        body = ""
        try:
            body = e.read().decode()[:300]  # type: ignore
        except Exception:
            pass
        return False, f"dispatch failed HTTP {code}: {str(e)[:150]} {body[:150]}"
