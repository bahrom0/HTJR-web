[CmdletBinding()]
param(
    [ValidateSet('Start', 'Stop', 'Status')]
    [string]$Action = 'Start',

    [ValidateRange(1, 65535)]
    [int]$Port = 8020,

    [switch]$NoOpen
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

$appRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent $appRoot
$python = Join-Path $workspaceRoot 'api_server\.venv-s11\Scripts\python.exe'
$runtimeDirectory = Join-Path $appRoot 'data\.runtime'
$statePath = Join-Path $runtimeDirectory 'process.json'
$stdoutPath = Join-Path $runtimeDirectory 'server.stdout.log'
$stderrPath = Join-Path $runtimeDirectory 'server.stderr.log'

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-Health {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        return $response.status -eq 'ok'
    }
    catch {
        return $false
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = @(
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    )
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
    Wait-Process -Id $ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

function Stop-App {
    $state = Read-State
    if ($null -ne $state) {
        $process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            # A venv python.exe can spawn the base interpreter that actually
            # owns port 8020. Stopping only the wrapper leaves the old server
            # alive and makes subsequent starts silently reuse stale code.
            Stop-ProcessTree -ProcessId $process.Id
        }
    }
    if (Test-Path -LiteralPath $statePath) {
        Remove-Item -LiteralPath $statePath -Force
    }
}

if ($Action -eq 'Stop') {
    Stop-App
    Write-Output 'Kraken Annotator stopped.'
    exit 0
}

if ($Action -eq 'Status') {
    if (Test-Health) {
        Write-Output "[OK] Kraken Annotator: http://127.0.0.1:$Port"
        exit 0
    }
    Write-Output '[--] Kraken Annotator is stopped.'
    exit 1
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing: $python"
}
if (Test-Health) {
    Write-Output "[OK] Kraken Annotator is already running at http://127.0.0.1:$Port"
    if (-not $NoOpen) {
        Start-Process "http://127.0.0.1:$Port"
    }
    exit 0
}

Stop-App
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @(
    '-m',
    'uvicorn',
    'annotation_app.server:app',
    '--host',
    '127.0.0.1',
    '--port',
    [string]$Port
) -WorkingDirectory $workspaceRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru

[pscustomobject]@{
    schema_version = 1
    pid = $process.Id
    port = $Port
    python = $python
    started_at = (Get-Date).ToUniversalTime().ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    $process.Refresh()
    if ($process.HasExited) {
        $tail = Get-Content -LiteralPath $stderrPath -Tail 30 -ErrorAction SilentlyContinue
        if ($tail) {
            $tail | ForEach-Object { Write-Output "[Annotator] $_" }
        }
        throw "Kraken Annotator exited during startup. Check $stderrPath"
    }
    if (Test-Health) {
        Write-Output "[OK] Kraken Annotator: http://127.0.0.1:$Port"
        if (-not $NoOpen) {
            Start-Process "http://127.0.0.1:$Port"
        }
        exit 0
    }
    Start-Sleep -Milliseconds 250
}

Stop-App
throw 'Kraken Annotator did not become ready within 30 seconds.'
