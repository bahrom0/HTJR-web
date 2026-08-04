[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status', 'Stop')]
    [string]$Action = 'Start',

    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 5173,

    [ValidateRange(1, 300)]
    [int]$ReadinessTimeoutSeconds = 45
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
Add-Type -AssemblyName System.Net.Http

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $workspaceRoot 'api_server'
$webRoot = Join-Path $workspaceRoot 'web_app'
$apiLauncher = Join-Path $apiRoot 'ops\start-dev.ps1'
$viteEntry = Join-Path $webRoot 'node_modules\vite\bin\vite.js'
$viteEntryArgument = 'node_modules\vite\bin\vite.js'
$stateDirectory = Join-Path $webRoot 'output\.runtime'
$statePath = Join-Path $stateDirectory 'local-web.json'
$webOutputLogPath = Join-Path $stateDirectory 'web.stdout.log'
$webErrorLogPath = Join-Path $stateDirectory 'web.stderr.log'

function Read-WebState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-TrackedWebProcess {
    param([object]$State)

    if ($null -eq $State) {
        return $false
    }
    $process = Get-Process -Id ([int]$State.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    try {
        return [String]::Equals(
            (Resolve-Path -LiteralPath $process.Path).Path,
            (Resolve-Path -LiteralPath ([string]$State.node)).Path,
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Find-WebListenerProcess {
    param(
        [int]$Port,
        [string]$ExpectedNode
    )

    $pattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p TCP)) {
        if ($line -notmatch $pattern) {
            continue
        }
        $candidate = Get-Process -Id ([int]$Matches[1]) -ErrorAction SilentlyContinue
        if ($null -eq $candidate) {
            continue
        }
        try {
            if ([String]::Equals(
                (Resolve-Path -LiteralPath $candidate.Path).Path,
                (Resolve-Path -LiteralPath $ExpectedNode).Path,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                return $candidate
            }
        }
        catch {
            continue
        }
    }
    return $null
}

function Write-WebState {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Node,
        [int]$Port
    )

    [pscustomobject]@{
        schema_version = 1
        node = $Node
        pid = $Process.Id
        port = $Port
        started_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Test-LoopbackPortAvailable {
    param([int]$Port)

    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        $listener.Stop()
    }
}

function Remove-WebState {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
    }
}

function Stop-Web {
    $state = Read-WebState
    if (Test-TrackedWebProcess -State $state) {
        $processId = [int]$state.pid
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
    Remove-WebState
}

function Test-LiveRoundTrip {
    param([int]$Port)

    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health/live" -TimeoutSec 2
        return $response.status -eq 'ok' -and -not [String]::IsNullOrWhiteSpace([string]$response.request_id)
    }
    catch {
        return $false
    }
}

function Test-ErrorEnvelopeRoundTrip {
    param([int]$Port)

    $client = [System.Net.Http.HttpClient]::new()
    try {
        $password = [string]::new('x', 129)
        $content = [System.Net.Http.StringContent]::new("{`"email`":`"launcher@example.invalid`",`"password`":`"$password`"}", [Text.Encoding]::UTF8, 'application/json')
        $response = $client.PostAsync("http://127.0.0.1:$Port/api/v1/access/login", $content).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        return ([int]$response.StatusCode -eq 422) -and
            $body.code -eq 'request_validation_failed' -and
            $body.retryable -eq $false -and
            -not [String]::IsNullOrWhiteSpace([string]$body.request_id) -and
            -not ($response.Content.ReadAsStringAsync().GetAwaiter().GetResult() -match $password)
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Test-ApiStatus {
    & $apiLauncher -Action Status -Port $ApiPort
    return $LASTEXITCODE -eq 0
}

if ($Action -eq 'Stop') {
    Stop-Web
    & $apiLauncher -Action Stop -Port $ApiPort
    Write-Output 'Tajik HTR Studio local stack stopped.'
    exit 0
}

if ($Action -eq 'Status') {
    $webReady = Test-TrackedWebProcess -State (Read-WebState)
    Write-Output $(if ($webReady) { '[OK] Frontend: ready at http://127.0.0.1:5173' } else { '[--] Frontend: not ready' })
    & $apiLauncher -Action Status -Port $ApiPort
    $apiReady = $LASTEXITCODE -eq 0
    $roundTripReady = $webReady -and (Test-LiveRoundTrip -Port $WebPort) -and (Test-ErrorEnvelopeRoundTrip -Port $WebPort)
    if ($apiReady -and $roundTripReady) {
        Write-Output '[OK] Browser -> API proxy: ready'
        exit 0
    }
    Write-Output '[--] Browser -> API proxy: not ready'
    exit 1
}

if (-not (Test-Path -LiteralPath $viteEntry -PathType Leaf)) {
    throw 'Web dependencies are missing. Run npm.cmd ci in web_app first.'
}

$priorWebState = Read-WebState
if (Test-TrackedWebProcess -State $priorWebState) {
    & $apiLauncher -Action Start -Port $ApiPort -ReadinessTimeoutSeconds $ReadinessTimeoutSeconds
    if ($LASTEXITCODE -eq 0 -and (Test-LiveRoundTrip -Port $WebPort)) {
        Write-Output "Tajik HTR Studio local stack is already running at http://127.0.0.1:$WebPort."
        exit 0
    }
    throw 'The tracked Web server is running, but its API connection is unavailable. Use start.bat stop, then start.bat.'
}
Remove-WebState
if (-not (Test-LoopbackPortAvailable -Port $WebPort)) {
    throw "Web port $WebPort is occupied by an untracked process. Close the old launcher once, or run start.bat stop before starting again."
}

$nodeCommand = Get-Command node.exe -ErrorAction Stop
$nodePath = $nodeCommand.Source
$webProcess = $null
try {
    Write-Output '[4/4] Frontend: starting Vite development server...'
    & $apiLauncher -Action Start -Port $ApiPort -ReadinessTimeoutSeconds $ReadinessTimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw 'API/worker launcher failed.'
    }

    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $previousProxyTarget = $env:HTR_WEB_API_PROXY_TARGET
    try {
        $env:HTR_WEB_API_PROXY_TARGET = "http://127.0.0.1:$ApiPort"
        $webProcess = Start-Process -FilePath $nodePath -ArgumentList @($viteEntryArgument, '--host', '127.0.0.1', '--port', [string]$WebPort, '--strictPort') -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput $webOutputLogPath -RedirectStandardError $webErrorLogPath -PassThru
    }
    finally {
        if ($null -eq $previousProxyTarget) {
            Remove-Item Env:HTR_WEB_API_PROXY_TARGET -ErrorAction SilentlyContinue
        }
        else {
            $env:HTR_WEB_API_PROXY_TARGET = $previousProxyTarget
        }
    }
    Write-WebState -Process $webProcess -Node $nodePath -Port $WebPort

    $deadline = (Get-Date).AddSeconds($ReadinessTimeoutSeconds)
    do {
        $webProcess.Refresh()
        if ($webProcess.HasExited) {
            $listener = Find-WebListenerProcess -Port $WebPort -ExpectedNode $nodePath
            if ($null -ne $listener) {
                $webProcess = $listener
                Write-WebState -Process $webProcess -Node $nodePath -Port $WebPort
            }
        }
        if (-not $webProcess.HasExited -and (Test-LiveRoundTrip -Port $WebPort) -and (Test-ErrorEnvelopeRoundTrip -Port $WebPort)) {
            Write-Output "[OK] Frontend: ready at http://127.0.0.1:$WebPort"
            Write-Output '[READY] Tajik HTR Studio is fully started. Models are preloaded.'
            exit 0
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    throw "Local stack readiness was not reached within $ReadinessTimeoutSeconds seconds."
}
catch {
    if ($null -ne $webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -ErrorAction SilentlyContinue
    }
    Remove-WebState
    & $apiLauncher -Action Stop -Port $ApiPort
    throw
}
