<#
  Run a Telemetry V1 job (used by the scheduled tasks; also the manual command). Read-only towards MT5 - it never trades.

    powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\run-telemetry.ps1 -Command daily
    ... -Command reconcile -Date 2026-10-05       (re)check one day
    ... -Command tracker                          show the 14-day progress
    ... -Command watchdog                         heartbeat / MT5 connection status
    ... -Command start-validation -Date 2026-10-05
#>
param(
    [ValidateSet('daily', 'reconcile', 'tracker', 'watchdog', 'ingest', 'start-validation')]
    [string]$Command = 'daily',
    [string]$Date = ''
)
. (Join-Path $PSScriptRoot 'common.ps1')
Import-ZoneflowEnv | Out-Null
$arguments = @('-m', 'services.telemetry', $Command)
if ($Date) { $arguments += @('--date', $Date) }
$log = Join-Path $script:LogDir "telemetry-$Command.log"
Write-ZoneflowLog "telemetry-$Command" "run: $($arguments -join ' ')"
Push-Location $script:InstallRoot
try {
    Invoke-Native { & $script:Python @arguments 2>&1 | Tee-Object -FilePath $log -Append }
    $code = $LASTEXITCODE
} finally { Pop-Location }
Write-ZoneflowLog "telemetry-$Command" "exit code $code"
exit $code
