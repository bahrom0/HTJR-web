[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$IntervalSeconds = 2,
    [int]$TailLines = 20,
    [switch]$Once
)

$ErrorActionPreference = 'SilentlyContinue'
$apiRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $apiRoot 'data\.runtime'
$logPaths = @(
    (Join-Path $runtime 'api.stderr.log'),
    (Join-Path $runtime 'worker.stderr.log'),
    (Join-Path $runtime 'api.stdout.log'),
    (Join-Path $runtime 'worker.stdout.log')
)

Write-Host "Watching http://127.0.0.1:$Port and runtime logs. Press Ctrl+C to stop."
Write-Host "Logs: $runtime"

$logOffsets = @{}
foreach ($path in $logPaths) {
    $label = Split-Path $path -Leaf
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "[$label] log file is not present: $path" -ForegroundColor Yellow
        $logOffsets[$path] = 0L
        continue
    }
    Get-Content -LiteralPath $path -Tail $TailLines | ForEach-Object {
        Write-Host "[$label] $_" -ForegroundColor $(if ($label -like '*.stderr.log') { 'Red' } else { 'DarkGray' })
    }
    $logOffsets[$path] = [int64](Get-Item -LiteralPath $path).Length
}

$lastHealth = $null
while ($true) {
    foreach ($path in $logPaths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $label = Split-Path $path -Leaf
        $length = [int64](Get-Item -LiteralPath $path).Length
        $offset = [int64]$logOffsets[$path]
        if ($length -lt $offset) { $offset = 0L }
        if ($length -gt $offset) {
            $stream = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
            try {
                [void]$stream.Seek($offset, [System.IO.SeekOrigin]::Begin)
                $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true, 4096, $true)
                try {
                    $newText = $reader.ReadToEnd()
                    $logOffsets[$path] = $stream.Position
                }
                finally {
                    $reader.Dispose()
                }
            }
            finally {
                $stream.Dispose()
            }
            ($newText -split '\r?\n') | Where-Object { $_ } | ForEach-Object {
                Write-Host "[$label] $_" -ForegroundColor $(if ($label -like '*.stderr.log') { 'Red' } else { 'DarkGray' })
            }
        }
    }

    $listening = $false
    try {
        $connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen)
        $listening = $connections.Count -gt 0
    }
    catch {
        $listening = $false
    }
    if (-not $listening) {
        $listening = Test-NetConnection -ComputerName '127.0.0.1' -Port $Port -InformationLevel Quiet
    }

    $health = 'unreachable'
    try {
        $payload = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health/live" -TimeoutSec 2
        $health = "200 $(($payload | ConvertTo-Json -Compress))"
    }
    catch {
        $health = $_.Exception.Message
    }

    $current = "port=$listening; health=$health"
    if ($current -ne $lastHealth) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $current"
        $lastHealth = $current
    }
    if ($Once) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
