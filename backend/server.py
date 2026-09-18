"""Uvicorn entrypoint.

Kept at the repository's historical path (``backend/server.py``) so existing
process managers keep working; the application itself lives in ``app.main``.
"""
from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
