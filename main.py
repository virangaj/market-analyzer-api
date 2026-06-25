"""
Render entry point.

Render injects the port to listen on via the $PORT environment variable and
expects the process to bind 0.0.0.0. This wraps the FastAPI app (api:app) so
the platform can start it with a single command:  python main.py

Locally it falls back to port 8000, so `python main.py` also works on your
machine (equivalent to `uvicorn api:app --port 8000`).
"""
import os
import uvicorn
from api import app          # <-- top-level, this is what Vercel grabs

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, workers=1)
