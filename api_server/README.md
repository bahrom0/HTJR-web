# Tajik HTR Studio API

The API and ML worker are separate local processes. Neither imports `HTR v2 CER/backend` or loads ML weights in the API process.

```powershell
# Uses an isolated Python environment after it is created for this project.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.worker.main
```

On Windows, the project launcher selects the first interpreter that passes an API/worker import probe (`.venv-s11`, then `.venv`), starts both processes without visible child windows, and waits for API plus worker readiness:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start-dev.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start-dev.ps1 -Action Status
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start-dev.ps1 -Action Stop
```

The Web development server proxies `/api/v1` and `/events` to `HTR_WEB_API_PROXY_TARGET` (default `http://127.0.0.1:8000`). Production must proxy the same paths from one origin; feature code never embeds a localhost API URL.

`/api/v1/health/live` is public liveness only. Readiness is an internal abstraction and does not load a model or disclose local paths.
