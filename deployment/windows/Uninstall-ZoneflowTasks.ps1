# Remove Zoneflow's start-at-boot tasks and firewall rules (code and C:\ZoneflowData are kept). Administrator PowerShell.
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator
Stop-Zoneflow
foreach ($name in $script:TaskNames + @('Zoneflow-Telemetry-Daily', 'Zoneflow-Telemetry-Watchdog')) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
foreach ($rule in @('Zoneflow HTTPS', 'Zoneflow internal ports blocked')) {
    Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
Write-Host 'Zoneflow tasks and firewall rules removed.'
