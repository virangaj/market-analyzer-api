# Deploying market-analyzer to Render

Two pieces: the **backend** (FastAPI web service) and the **frontend**
(static site). Deploy the backend first, then point the frontend at it.

---

## 1. Backend (FastAPI web service)

Files added for deployment: `main.py` (entry point), `render.yaml` (blueprint),
`runtime.txt` (Python version). `api.py` now reads CORS origins from an env var.

### Option A — Blueprint (one click)
1. Push your repo (with `Backend/` containing the Python files) to GitHub.
2. In Render: **New → Blueprint**, pick the repo. It reads `render.yaml`.
3. Adjust `rootDir` in `render.yaml` if your backend isn't in `Backend/`.
4. Deploy.

### Option B — Manual web service
**New → Web Service**, then set:

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Region | **Frankfurt** or **Singapore** (not US — see below) |
| Root Directory | `Backend` (the folder with `api.py`) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python main.py` |
| Health Check Path | `/health` |

Environment variables:

| Key | Value |
|---|---|
| `ALLOWED_ORIGINS` | `*` while testing, then your frontend URL |
| `PYTHON_VERSION` | `3.12.3` |

After it deploys you'll get a URL like `https://market-analyzer-api.onrender.com`.
Confirm it works: open `…/docs`, then try `…/health` and
`…/analyze?symbol=PAXGUSDT`.

> The start command `python main.py` binds uvicorn to Render's `$PORT`. You can
> equivalently use `uvicorn api:app --host 0.0.0.0 --port $PORT`.

---

## 2. Frontend (static site)

`client.ts` now reads the backend URL from `VITE_API_BASE` at build time.

**New → Static Site**, then set:

| Setting | Value |
|---|---|
| Build Command | `npm install && npm run build` |
| Publish Directory | `dist` |
| Env var `VITE_API_BASE` | your backend URL, e.g. `https://market-analyzer-api.onrender.com` |

Then set the backend's `ALLOWED_ORIGINS` to this static site's URL (e.g.
`https://market-analyzer-dashboard.onrender.com`) and redeploy the backend, so CORS allows it.

> You can also just paste the backend URL into the dashboard's API box at
> runtime — `VITE_API_BASE` only sets the default.

---

## 3. Important caveats

**Region matters.** MEXC and Binance both geo-restrict US IPs. If you deploy in
a US region, `/sanity` (Binance cross-check) will fail and MEXC data calls may
too. Use **Frankfurt** or **Singapore**.

**Free tier cold starts.** Free web services spin down after ~15 minutes idle
and take 30–60s to wake on the next request. The first dashboard load after a
quiet period will be slow. A paid instance avoids this.

**Memory.** `main.py` runs a single worker on purpose — pandas/numpy plus the
backtest can approach the free tier's 512 MB if you add workers.

**Secrets.** If you later wire the news feed, add `ANTHROPIC_API_KEY` as an
environment variable in Render — never commit it.
