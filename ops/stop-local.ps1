[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot 'local.ps1') -Action Stop
exit $LASTEXITCODE
