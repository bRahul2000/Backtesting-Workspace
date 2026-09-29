<#
  Create or change the Zoneflow admin login. Run it ON THE SERVER, in an administrator PowerShell:

    powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\New-ZoneflowAdmin.ps1

  You type the username and the password (twice, hidden). Only an Argon2id hash is saved, in C:\ZoneflowData\zoneflow.env.
  New random session/proxy secrets are made at the same time, so everyone currently logged in is logged out.
  Never send the password through chat or e-mail, and never put it in Git.
#>
param([switch]$NoRestart)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator
& $script:Python (Join-Path $script:InstallRoot 'tools\create_zoneflow_admin.py') --env-file $script:EnvFile
if ($LASTEXITCODE -ne 0) { throw 'The admin login was not changed.' }
Protect-ZoneflowFile $script:EnvFile
if (-not $NoRestart -and (Get-ScheduledTask -TaskName 'Zoneflow-App' -ErrorAction SilentlyContinue)) {
    Write-Host 'Restarting Zoneflow so it uses the new login...'
    Stop-Zoneflow
    Start-Zoneflow
}
