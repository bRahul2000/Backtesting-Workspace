<#
  Register the Telemetry V1 scheduled tasks (administrator PowerShell). Safe to run again.

    Zoneflow-Telemetry-Daily     once a day at 00:45 UTC: ingest the spool, reconcile every finished day against the
                                 MT5 broker export, update the 14-day tracker. If the server was off at that time the
                                 task runs as soon as it is back ("start when available"), and any day the job did not
                                 reconcile in time is marked late / MISSED in the tracker.
    Zoneflow-Telemetry-Watchdog  every 5 minutes: last heartbeat, MT5 connection, stale writers -> status.json.
                                 Observe and report only: it never closes, flattens or changes anything.
#>
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator
New-Item -ItemType Directory -Force -Path (Join-Path $script:DataRoot 'telemetry') | Out-Null
if (-not (Read-ZoneflowEnv)['ZONEFLOW_TELEMETRY_ROOT']) {
    Set-ZoneflowEnvValue 'ZONEFLOW_TELEMETRY_ROOT' (Join-Path $script:DataRoot 'telemetry')
}
$shell = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path $shell)) { $shell = 'powershell.exe' }
$runner = Join-Path $script:InstallRoot 'deployment\windows\run-telemetry.ps1'
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

$dailyLocal = [DateTime]::SpecifyKind((Get-Date).ToUniversalTime().Date.AddMinutes(45), 'Utc').ToLocalTime()
$daily = New-ScheduledTaskAction -Execute $shell -WorkingDirectory $script:InstallRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Command daily"
Register-ScheduledTask -TaskName 'Zoneflow-Telemetry-Daily' -Action $daily -Settings $settings -Principal $principal `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $dailyLocal) -Force | Out-Null

$watch = New-ScheduledTaskAction -Execute $shell -WorkingDirectory $script:InstallRoot `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Command watchdog"
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName 'Zoneflow-Telemetry-Watchdog' -Action $watch -Settings $settings -Principal $principal `
    -Trigger $every5 -Force | Out-Null

Write-Host "Registered: Zoneflow-Telemetry-Daily (daily at $($dailyLocal.ToString('HH:mm')) server time = 00:45 UTC)"
Write-Host 'Registered: Zoneflow-Telemetry-Watchdog (every 5 minutes)'
Write-Host "Manual run: powershell -ExecutionPolicy Bypass -File `"$runner`" -Command daily"
