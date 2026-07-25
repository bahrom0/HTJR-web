[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Stop')]
    [string]$Action = 'Start',

    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [ValidateRange(1, 300)]
    [int]$ReadinessTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$stateDirectory = Join-Path $projectRoot 'data\.runtime'
$statePath = Join-Path $stateDirectory 'dev-processes.json'
$apiOutputLogPath = Join-Path $stateDirectory 'api.stdout.log'
$apiErrorLogPath = Join-Path $stateDirectory 'api.stderr.log'
$workerOutputLogPath = Join-Path $stateDirectory 'worker.stdout.log'
$workerErrorLogPath = Join-Path $stateDirectory 'worker.stderr.log'

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

function Stop-TrackedProcesses {
    $state = Read-LauncherState
    if ($null -eq $state) {
        Write-Output 'Tajik HTR Studio dev processes are not running.'
        return
    }

    foreach ($property in @('worker_pid', 'api_pid')) {
        $processId = [int]$state.$property
        if (Test-TrackedProcess -ProcessId $processId -ExpectedInterpreter ([string]$state.python)) {
            try {
                Stop-Process -Id $processId -ErrorAction Stop
                Wait-Process -Id $processId -Timeout 10 -ErrorAction Stop
            }
            catch {
                if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                    throw
                }
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

if ($Action -eq 'Stop') {
    Stop-TrackedProcesses
    exit 0
}

if ($Action -eq 'Status') {
    $state = Read-LauncherState
    if ($null -eq $state) {
        Write-Output 'Tajik HTR Studio dev processes are not running.'
        exit 1
    }
    $apiRunning = Test-TrackedProcess -ProcessId ([int]$state.api_pid) -ExpectedInterpreter ([string]$state.python)
    $workerRunning = Test-TrackedProcess -ProcessId ([int]$state.worker_pid) -ExpectedInterpreter ([string]$state.python)
    $isReady = $apiRunning -and $workerRunning -and (Test-ApiReadiness -ApiPort ([int]$state.port)) -and (Test-WorkerReadiness -Interpreter ([string]$state.python))
    Write-Output $(if ($isReady) { 'Tajik HTR Studio dev processes are ready.' } else { 'Tajik HTR Studio dev processes are not ready.' })
    exit $(if ($isReady) { 0 } else { 1 })
}

$priorState = Read-LauncherState
if ($null -ne $priorState) {
    $apiRunning = Test-TrackedProcess -ProcessId ([int]$priorState.api_pid) -ExpectedInterpreter ([string]$priorState.python)
    $workerRunning = Test-TrackedProcess -ProcessId ([int]$priorState.worker_pid) -ExpectedInterpreter ([string]$priorState.python)
    if ($apiRunning -or $workerRunning) {
        throw 'Tajik HTR Studio dev processes are already running. Use -Action Status or -Action Stop.'
    }
    Remove-LauncherState
}

$python = Resolve-ProjectInterpreter
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$apiProcess = $null
$workerProcess = $null

try {
    $apiProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$Port) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $apiOutputLogPath -RedirectStandardError $apiErrorLogPath -PassThru
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

    $workerProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'app.worker.main') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $workerOutputLogPath -RedirectStandardError $workerErrorLogPath -PassThru
    [pscustomobject]@{
        schema_version = 1
        python = $python
        api_pid = $apiProcess.Id
        worker_pid = $workerProcess.Id
        port = $Port
        started_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

    $deadline = (Get-Date).AddSeconds($ReadinessTimeoutSeconds)
    do {
        $apiProcess.Refresh()
        $workerProcess.Refresh()
        if ($apiProcess.HasExited -or $workerProcess.HasExited) {
            throw 'The API or worker exited before readiness was reached.'
        }
        if ((Test-ApiReadiness -ApiPort $Port) -and (Test-WorkerReadiness -Interpreter $python)) {
            Write-Output "Tajik HTR Studio API and worker are ready on http://127.0.0.1:$Port."
            exit 0
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    throw "Readiness was not reached within $ReadinessTimeoutSeconds seconds."
}
catch {
    if ($null -ne $workerProcess -and -not $workerProcess.HasExited) {
        Stop-Process -Id $workerProcess.Id -ErrorAction SilentlyContinue
    }
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue
    }
    Remove-LauncherState
    throw
}
