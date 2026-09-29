# Scheduled task "Zoneflow-Auth": the login service on 127.0.0.1 only, restarted if it stops.
. (Join-Path $PSScriptRoot 'common.ps1')
Import-ZoneflowEnv | Out-Null
Invoke-Supervised -Name 'auth' -FilePath $script:Python -WorkingDirectory $script:InstallRoot -Arguments @('-m', 'services.auth.server')
