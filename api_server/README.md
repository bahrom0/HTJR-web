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

## CUDA inference

`config.toml` is the local project configuration. Set `[ml].CUDA = true` to
prefer CUDA when a compatible NVIDIA GPU is available, or `false` to force CPU
inference. The worker keeps CRAFT and TrOCR model ownership; the API never
loads model weights. On CUDA, TrOCR uses FP16 and batches up to
`[ml].trocr_batch_size` line crops; CPU stays at one crop per generation for
predictable memory use. Production defaults to
`[ml].trocr_adapter_mode = "none"`, which runs the verified
`kazars24/trocr-base-handwritten-ru` backbone without importing PEFT or loading
the preserved rsLoRA files. Set `HTR_TROCR_ADAPTER_MODE=rslora` only for an
explicit compatibility/diagnostic run.

For the RTX 4050 Laptop configuration, install the pinned CUDA build into the
existing environment, then restart the local stack:

```powershell
.\.venv-s11\Scripts\python.exe -m pip install --upgrade --force-reinstall --index-url https://download.pytorch.org/whl/cu128 "torch==2.11.0+cu128" "torchvision==0.26.0+cu128"
..\start.bat stop
..\start.bat
```
