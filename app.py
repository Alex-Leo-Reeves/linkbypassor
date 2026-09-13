"""Root-level WSGI entrypoint for Render.

Render's default Start Command is `gunicorn app:app`, but our Flask app
lives at `backend.app:app`. This shim makes BOTH work, so the deploy
succeeds no matter which start command is configured in the dashboard.
"""
from backend.app import app  # noqa: F401  (gunicorn looks up `app` here)

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
