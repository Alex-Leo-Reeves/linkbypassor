"""Root-level WSGI entrypoint for Render.

Render's default Start Command is `gunicorn app:app`, but our Flask app
lives at `backend.app:app`. This shim makes BOTH work, so the deploy
succeeds no matter which start command is configured in the dashboard.
"""
import os
import sys

# Add backend directory to Python path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from backend.app import app  # noqa: F401  (gunicorn looks up `app` here)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
