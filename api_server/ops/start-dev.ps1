[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Stop')]
    [string]$Action = 'Start',

    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [ValidateRange(1, 300)]
    [int]$ReadinessTimeoutSeconds = 30,

    [ValidateRange(30, 1800)]
    [int]$ModelWarmupTimeoutSeconds = 900,

    [string]$WebDistPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Repair-ProcessPathEnvironment {
    $pathKeys = @(
        [Environment]::GetEnvironmentVariables().Keys |
            Where-Object { [String]::Equals([string]$_, 'Path', [StringComparison]::OrdinalIgnoreCase) }
    )
    if ($pathKeys.Count -le 1) {
        return
    }

    $pathValue = [Environment]::GetEnvironmentVariable('Path', 'Process')
    foreach ($pathKey in $pathKeys) {
        [Environment]::SetEnvironmentVariable([string]$pathKey, $null, 'Process')
    }
    [Environment]::SetEnvironmentVariable('Path', $pathValue, 'Process')
}

Repair-ProcessPathEnvironment

$projectRoot = Split-Path -Parent $PSScriptRoot
$stateDirectory = Join-Path $projectRoot 'data\.runtime'
$statePath = Join-Path $stateDirectory 'dev-processes.json'
$apiOutputLogPath = Join-Path $stateDirectory 'api.stdout.log'
$apiErrorLogPath = Join-Path $stateDirectory 'api.stderr.log'
$workerOutputLogPath = Join-Path $stateDirectory 'worker.stdout.log'
$workerErrorLogPath = Join-Path $stateDirectory 'worker.stderr.log'
$configPath = Join-Path $projectRoot 'config.toml'
$workspaceRoot = Split-Path -Parent $projectRoot
$krakenLauncher = Join-Path $workspaceRoot 'kraken_sidecar\run-wsl.ps1'
$krakenOutputLogPath = Join-Path $stateDirectory 'kraken.stdout.log'
$krakenErrorLogPath = Join-Path $stateDirectory 'kraken.stderr.log'
$krakenPort = 8011
$webDist = $null
if (-not [String]::IsNullOrWhiteSpace($WebDistPath)) {
    $webDist = (Resolve-Path -LiteralPath $WebDistPath -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath (Join-Path $webDist 'index.html') -PathType Leaf)) {
        throw "Compiled web client is missing index.html: $webDist"
    }
}

function Resolve-ProjectInterpreter {
    $candidates = @(
        (Join-Path $projectRoot '.venv-s11\Scripts\python.exe'),
        (Join-Path $projectRoot '.venv\Scripts\python.exe')
    )

    Push-Location $projectRoot
    try {
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                continue
            }
            & $candidate -c 'import fastapi, uvicorn, app.main, app.worker.main' *> $null
            if ($LASTEXITCODE -eq 0) {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        }
    }
    finally {
        Pop-Location
    }

    throw 'No working project interpreter was found in .venv-s11 or .venv.'
}

function Read-LauncherState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-TrackedProcess {
    param(
        [int]$ProcessId,
        [string]$ExpectedInterpreter
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    try {
        return [String]::Equals(
            (Resolve-Path -LiteralPath $process.Path).Path,
            (Resolve-Path -LiteralPath $ExpectedInterpreter).Path,
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Remove-LauncherState {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
    }
}

function Test-KrakenSelected {
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $false
    }
    return $null -ne (
        Select-String -LiteralPath $configPath -Pattern '^\s*CRAFT\s*=\s*false\s*(?:#.*)?$' -CaseSensitive
    )
}

function Test-CudaSelected {
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $false
    }
    return $null -ne (
        Select-String -LiteralPath $configPath -Pattern '^\s*CUDA\s*=\s*true\s*(?:#.*)?$' -CaseSensitive
    )
}

function Test-KrakenReadiness {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$krakenPort/health" -TimeoutSec 2
        return $response.status -eq 'ready' -and
            -not [String]::IsNullOrWhiteSpace([string]$response.evidence.model_version)
    }
    catch {
        return $false
    }
}

function Stop-KrakenSidecar {
    if (-not (Test-KrakenReadiness)) {
        return
    }
    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$krakenPort/shutdown" -TimeoutSec 3 | Out-Null
    }
    catch {
        Write-Warning 'Kraken sidecar did not accept the graceful shutdown request.'
    }
}

function Stop-TrackedProcesses {
    $state = Read-LauncherState
    Stop-KrakenSidecar
    if ($null -eq $state) {
        Write-Output 'Tajik HTR Studio dev processes are not running.'
        return
    }

    foreach ($property in @('worker_pid', 'api_pid')) {
        $processId = [int]$state.$property
        if (Test-TrackedProcess -ProcessId $processId -ExpectedInterpreter ([string]$state.python)) {
            Stop-Process -Id $processId -ErrorAction Stop
            try {
                Wait-Process -Id $processId -Timeout 10 -ErrorAction Stop
            }
            catch {
                if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                    throw
                }
            }
        }
    }
    if (
        $state.PSObject.Properties.Name -contains 'kraken_pid' -and
        [int]$state.kraken_pid -gt 0
    ) {
        $krakenHost = Get-Process -Id ([int]$state.kraken_pid) -ErrorAction SilentlyContinue
        if ($null -ne $krakenHost) {
            try {
                Wait-Process -Id $krakenHost.Id -Timeout 10 -ErrorAction Stop
            }
            catch {
                Stop-Process -Id $krakenHost.Id -ErrorAction SilentlyContinue
            }
        }
    }
    Remove-LauncherState
    Write-Output 'Tajik HTR Studio API and worker stopped.'
}

function Test-ApiReadiness {
    param([int]$ApiPort)

    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/v1/health/live" -TimeoutSec 2
        return $response.status -eq 'ok'
    }
    catch {
        return $false
    }
}

function Test-WorkerReadiness {
    param([string]$Interpreter)

    Push-Location $projectRoot
    try {
        try {
            # The API and worker can be applying a migration at this exact
            # moment.  Treat a transient readiness-query exception as not
            # ready and keep polling instead of aborting the launcher.
            & $Interpreter -c 'from app.core.database import Database; from app.core.settings import settings; from app.domain.readiness import ReadinessService; raise SystemExit(0 if ReadinessService(Database(settings.database_path), settings).pipeline_check().is_ready else 1)' *> $null
            return $LASTEXITCODE -eq 0
        }
        catch {
            return $false
        }
    }
    finally {
        Pop-Location
    }
}

function Get-CudaSummary {
    param([string]$Interpreter)

    Push-Location $projectRoot
    try {
        $lines = & $Interpreter -c 'import torch; from app.core.settings import settings; print(settings.ml_device); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)' 2>$null
        if ($lines.Count -ne 3) {
            return $null
        }
        return "configured_device=$($lines[0]); cuda_available=$($lines[1]); device=$($lines[2])"
    }
    finally {
        Pop-Location
    }
}

function Get-ResourceSummary {
    $parts = [System.Collections.Generic.List[string]]::new()
    try {
        $samples = Get-Counter '\Memory\Committed Bytes', '\Memory\Commit Limit', '\Memory\Available MBytes' -ErrorAction Stop |
            Select-Object -ExpandProperty CounterSamples
        $committedGiB = [math]::Round((($samples | Where-Object Path -match 'committed bytes').CookedValue / 1GB), 2)
        $limitGiB = [math]::Round((($samples | Where-Object Path -match 'commit limit').CookedValue / 1GB), 2)
        $availableMiB = [math]::Round((($samples | Where-Object Path -match 'available mbytes').CookedValue), 0)
        $parts.Add("commit=$committedGiB/$limitGiB GiB; available_ram=$availableMiB MiB")
    }
    catch {}
    try {
        $gpu = & nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader 2>$null | Select-Object -First 1
        if (-not [String]::IsNullOrWhiteSpace([string]$gpu)) {
            $parts.Add("vram=$gpu")
        }
    }
    catch {}
    return ($parts -join '; ')
}

if ($Action -eq 'Stop') {
    Stop-TrackedProcesses
    exit 0
}

if ($Action -eq 'Status') {
    $state = Read-LauncherState
    if ($null -eq $state) {
        Write-Output '[--] API: stopped'
        Write-Output '[--] Worker: stopped'
        exit 1
    }
    $apiRunning = Test-TrackedProcess -ProcessId ([int]$state.api_pid) -ExpectedInterpreter ([string]$state.python)
    $workerRunning = Test-TrackedProcess -ProcessId ([int]$state.worker_pid) -ExpectedInterpreter ([string]$state.python)
    $apiReady = $apiRunning -and (Test-ApiReadiness -ApiPort ([int]$state.port))
    $pipelineReady = $workerRunning -and (Test-WorkerReadiness -Interpreter ([string]$state.python))
    $krakenSelected = Test-KrakenSelected
    $krakenReady = -not $krakenSelected -or (Test-KrakenReadiness)
    $isRunning = $apiReady -and $workerRunning
    Write-Output $(if ($apiReady) { "[OK] API: ready (PID $($state.api_pid))" } else { '[--] API: not ready' })
    Write-Output $(if ($workerRunning) { "[OK] Worker: running (PID $($state.worker_pid))" } else { '[--] Worker: stopped' })
    if ($krakenSelected) {
        Write-Output $(if ($krakenReady) { '[OK] Kraken: ready in WSL' } else { '[--] Kraken: unavailable' })
    }
    Write-Output $(if ($pipelineReady) { '[OK] ML pipeline: ready' } else { '[..] ML pipeline: warming or unavailable; see worker logs' })
    if (
        $workerRunning -and
        $state.PSObject.Properties.Name -contains 'cuda_summary' -and
        -not [String]::IsNullOrWhiteSpace([string]$state.cuda_summary)
    ) {
        Write-Output "[i] CUDA: $($state.cuda_summary)"
    }
    $resourceSummary = Get-ResourceSummary
    if (-not [String]::IsNullOrWhiteSpace($resourceSummary)) {
        Write-Output "[i] Resources: $resourceSummary"
    }
    exit $(if ($isRunning) { 0 } else { 1 })
}

$krakenSelected = Test-KrakenSelected
$krakenDevice = $(if (Test-CudaSelected) { 'cuda:0' } else { 'cpu' })
$priorState = Read-LauncherState
if ($null -ne $priorState) {
    $apiRunning = Test-TrackedProcess -ProcessId ([int]$priorState.api_pid) -ExpectedInterpreter ([string]$priorState.python)
    $workerRunning = Test-TrackedProcess -ProcessId ([int]$priorState.worker_pid) -ExpectedInterpreter ([string]$priorState.python)
    $krakenReady = -not $krakenSelected -or (Test-KrakenReadiness)
    $priorWebDist = $(if ($priorState.PSObject.Properties.Name -contains 'web_dist') { [string]$priorState.web_dist } else { '' })
    $requestedWebDist = $(if ($null -eq $webDist) { '' } else { [string]$webDist })
    $webModeMatches = [String]::Equals($priorWebDist, $requestedWebDist, [StringComparison]::OrdinalIgnoreCase)
    if ($apiRunning -and $workerRunning -and $krakenReady -and $webModeMatches -and (Test-ApiReadiness -ApiPort ([int]$priorState.port))) {
        Write-Output "Tajik HTR Studio API and worker are already running on http://127.0.0.1:$($priorState.port)."
        exit 0
    }
    if ($apiRunning -or $workerRunning) {
        Stop-TrackedProcesses
    }
    Remove-LauncherState
}

$python = Resolve-ProjectInterpreter
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$apiProcess = $null
$workerProcess = $null
$krakenProcess = $null

try {
    if ($krakenSelected) {
        if (-not (Test-Path -LiteralPath $krakenLauncher -PathType Leaf)) {
            throw "Kraken launcher is missing: $krakenLauncher"
        }
        Write-Output '[1/5] Kraken: starting BLLA line segmenter in Ubuntu WSL...'
        if (-not (Test-KrakenReadiness)) {
            $powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
            $krakenProcess = Start-Process -FilePath $powerShellPath -ArgumentList @(
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                "`"$krakenLauncher`"",
                '-Port',
                [string]$krakenPort,
                '-Device',
                $krakenDevice
            ) -WindowStyle Hidden -RedirectStandardOutput $krakenOutputLogPath -RedirectStandardError $krakenErrorLogPath -PassThru
        }
        $krakenDeadline = (Get-Date).AddSeconds($ModelWarmupTimeoutSeconds)
        while (-not (Test-KrakenReadiness) -and (Get-Date) -lt $krakenDeadline) {
            if ($null -ne $krakenProcess) {
                $krakenProcess.Refresh()
                if ($krakenProcess.HasExited) {
                    if (Test-Path -LiteralPath $krakenErrorLogPath -PathType Leaf) {
                        Get-Content -LiteralPath $krakenErrorLogPath -Tail 20 |
                            ForEach-Object { Write-Output "[Kraken] $_" }
                    }
                    throw "Kraken sidecar exited during startup. Check $krakenErrorLogPath"
                }
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not (Test-KrakenReadiness)) {
            throw "Kraken sidecar did not warm up within $ModelWarmupTimeoutSeconds seconds."
        }
        Write-Output "[OK] Kraken: ready at http://127.0.0.1:$krakenPort"
    }

    Write-Output '[1/4] API: starting local server...'
    $previousWebDist = $env:HTR_WEB_DIST
    try {
        if ($null -eq $webDist) {
            Remove-Item Env:HTR_WEB_DIST -ErrorAction SilentlyContinue
        }
        else {
            $env:HTR_WEB_DIST = $webDist
        }
        $apiProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$Port) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $apiOutputLogPath -RedirectStandardError $apiErrorLogPath -PassThru
    }
    finally {
        if ($null -eq $previousWebDist) {
            Remove-Item Env:HTR_WEB_DIST -ErrorAction SilentlyContinue
        }
        else {
            $env:HTR_WEB_DIST = $previousWebDist
        }
    }
    # Let the API finish database migrations before the worker opens the same
    # SQLite file.  Starting both processes simultaneously can make a cold
    # launch race on schema creation look like a model-startup failure.
    $apiDeadline = (Get-Date).AddSeconds($ReadinessTimeoutSeconds)
    do {
        $apiProcess.Refresh()
        if ($apiProcess.HasExited) {
            throw 'The API exited before it completed startup.'
        }
        if (Test-ApiReadiness -ApiPort $Port) {
            break
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $apiDeadline)
    if (-not (Test-ApiReadiness -ApiPort $Port)) {
        throw "The API did not become live within $ReadinessTimeoutSeconds seconds."
    }
    Write-Output "[OK] API: ready at http://127.0.0.1:$Port"

    Write-Output '[2/4] Worker: starting persistent ML worker...'
    $workerProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'app.worker.main') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $workerOutputLogPath -RedirectStandardError $workerErrorLogPath -PassThru
    $cuda = Get-CudaSummary -Interpreter $python
    [pscustomobject]@{
        schema_version = 2
        python = $python
        api_pid = $apiProcess.Id
        worker_pid = $workerProcess.Id
        kraken_enabled = $krakenSelected
        kraken_pid = $(if ($null -eq $krakenProcess) { 0 } else { $krakenProcess.Id })
        cuda_summary = $cuda
        web_dist = $(if ($null -eq $webDist) { '' } else { $webDist })
        port = $Port
        started_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

    $detectorLabel = $(if ($krakenSelected) { 'Kraken' } else { 'CRAFT' })
    Write-Output "[3/4] ML models: loading $detectorLabel + TrOCR and keeping them in memory..."
    if ($cuda) { Write-Output "[i] CUDA: $cuda" }
    $workerStartupDeadline = (Get-Date).AddSeconds($ModelWarmupTimeoutSeconds)
    do {
        $apiProcess.Refresh()
        $workerProcess.Refresh()
        if ($apiProcess.HasExited -or $workerProcess.HasExited) {
            throw 'The API or worker exited before readiness was reached.'
        }
        if (Test-WorkerReadiness -Interpreter $python) {
            break
        }
        $elapsed = [int]((Get-Date) - ($workerStartupDeadline.AddSeconds(-$ModelWarmupTimeoutSeconds))).TotalSeconds
        Write-Progress -Activity 'Tajik HTR Studio: warming ML models' -Status "$detectorLabel + TrOCR loading ($elapsed s / $ModelWarmupTimeoutSeconds s)" -PercentComplete ([Math]::Min(99, [int](100 * $elapsed / $ModelWarmupTimeoutSeconds)))
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $workerStartupDeadline)

    if (-not (Test-WorkerReadiness -Interpreter $python)) {
        throw "The ML worker did not finish warmup within $ModelWarmupTimeoutSeconds seconds. Check $workerErrorLogPath"
    }
    Write-Progress -Activity 'Tajik HTR Studio: warming ML models' -Completed
    Write-Output '[OK] ML models: ready and retained in worker memory.'
    $resourceSummary = Get-ResourceSummary
    if (-not [String]::IsNullOrWhiteSpace($resourceSummary)) {
        Write-Output "[i] Resources after warmup: $resourceSummary"
    }

    Write-Output "[OK] Backend stack: ready at http://127.0.0.1:$Port"
    exit 0
}
catch {
    if ($null -ne $workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id -ErrorAction SilentlyContinue
    }
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue
    }
    if ($krakenSelected) {
        Stop-KrakenSidecar
    }
    if ($null -ne $krakenProcess -and -not $krakenProcess.HasExited) {
        Stop-Process -Id $krakenProcess.Id -ErrorAction SilentlyContinue
    }
    Remove-LauncherState
    throw
}
