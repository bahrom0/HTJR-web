# Local development workflow

From the workspace root:

```powershell
.\ops\start-local.ps1
.\ops\status-local.ps1
.\ops\stop-local.ps1
```

`start-local.ps1` selects the verified API project interpreter through the API launcher,
starts API, worker and Vite in hidden processes, then waits for two real browser-origin
round trips through the Vite proxy: `/api/v1/health/live` and the typed validation-error
envelope. Process IDs are stored only under ignored runtime directories and stop/status
validate the executable path before acting on a PID.

The workflow is local-only. It is not evidence of public HTTPS or model inference.
