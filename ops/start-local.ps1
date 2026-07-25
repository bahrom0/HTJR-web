[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 5173,

    [ValidateRange(1, 300)]
    [int]$ReadinessTimeoutSeconds = 45
)

& (Join-Path $PSScriptRoot 'local.ps1') -Action Start -ApiPort $ApiPort -WebPort $WebPort -ReadinessTimeoutSeconds $ReadinessTimeoutSeconds
exit $LASTEXITCODE
