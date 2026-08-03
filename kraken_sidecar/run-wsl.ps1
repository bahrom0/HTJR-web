[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8011,

    [ValidateSet('cpu', 'cuda:0')]
    [string]$Device = 'cuda:0'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-WslPath {
    param([string]$WindowsPath)

    $resolved = (Resolve-Path -LiteralPath $WindowsPath).Path.Replace('\', '/')
    if ($resolved -notmatch '^([A-Za-z]):/(.+)$') {
        throw "Could not convert path to WSL: $WindowsPath"
    }
    return "/mnt/$($Matches[1].ToLowerInvariant())/$($Matches[2])"
}

$serverPath = Join-Path $PSScriptRoot 'server.py'
$checkPath = Join-Path $PSScriptRoot 'check-wsl.sh'
$linuxServerPath = ConvertTo-WslPath -WindowsPath $serverPath

$linuxCheckPath = ConvertTo-WslPath -WindowsPath $checkPath
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & wsl.exe -d Ubuntu -- bash $linuxCheckPath $Device
    $probeExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($probeExitCode -ne 0) {
    if ($Device -eq 'cuda:0') {
        throw "Kraken WSL environment is not ready for CUDA. Run: wsl.exe -d Ubuntu -- bash -lc `"cd '/mnt/c/Users/bahro/OneDrive/Desktop/HTR App X Server/kraken_sidecar' && KRAKEN_TORCH_FLAVOR=cu128 bash setup-wsl.sh`""
    }
    throw "Kraken WSL environment is incomplete. Run: wsl.exe -d Ubuntu -- bash -lc `"cd '/mnt/c/Users/bahro/OneDrive/Desktop/HTR App X Server/kraken_sidecar' && bash setup-wsl.sh`""
}

$runtimePython = '${HOME}/.local/share/tajik-htr/kraken-7.0.3/venv/bin/python'
$quotedServer = "'" + $linuxServerPath.Replace("'", "'\''") + "'"
$precision = $(if ($Device -eq 'cpu') { '32-true' } else { 'bf16-mixed' })
$command = "exec $runtimePython $quotedServer --host 127.0.0.1 --port $Port --device $Device --precision $precision"
& wsl.exe -d Ubuntu -- bash -lc $command
exit $LASTEXITCODE
