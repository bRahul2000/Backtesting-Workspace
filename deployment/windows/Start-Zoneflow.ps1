# Start Zoneflow (the three background tasks). Administrator PowerShell.
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator
Start-Zoneflow
if (Wait-ZoneflowHealthy -Seconds 120) { Write-Host 'Zoneflow is running.' -ForegroundColor Green }
else { Write-Warning 'Started, but not healthy yet - run Get-ZoneflowStatus.ps1 and check C:\ZoneflowData\logs.'; exit 1 }
