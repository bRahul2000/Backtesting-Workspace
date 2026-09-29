# Stop Zoneflow (it starts again at the next reboot, or with Start-Zoneflow.ps1). Administrator PowerShell.
# Only Zoneflow's own processes are stopped - MetaTrader 5 and RDP are not touched.
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator
Stop-Zoneflow
Write-Host 'Zoneflow stopped.'
