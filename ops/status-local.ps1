[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 5173
)

& (Join-Path $PSScriptRoot 'local.ps1') -Action Status -ApiPort $ApiPort -WebPort $WebPort
exit $LASTEXITCODE
