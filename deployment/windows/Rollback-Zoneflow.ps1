<#
  Go back to an earlier Zoneflow version. Administrator PowerShell:

    powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Rollback-Zoneflow.ps1
        (no arguments = the version recorded in the newest backup)
    ... Rollback-Zoneflow.ps1 -Commit 4cbc1da          (a specific version)
    ... Rollback-Zoneflow.ps1 -RestoreSettings          (also put back zoneflow.env from that backup)

  Only the code (and optionally settings) go back. Workspace data is left as it is: it only ever grows with verified
  MT5 bars, and an older app version reads it fine. To restore it too, copy the backup's workspace folder by hand.
  The next Update-Zoneflow.ps1 returns to the latest version.
#>
param([string]$Commit = '', [switch]$RestoreSettings)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator

$backup = Get-ChildItem $script:BackupDir -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending |
    Where-Object { -not $Commit -or (Get-Content (Join-Path $_.FullName 'commit.txt') -ErrorAction SilentlyContinue) -like "$Commit*" } |
    Select-Object -First 1
if (-not $Commit) {
    if (-not $backup) { throw 'No backup found - pass -Commit <version> (see "git log" in C:\Zoneflow).' }
    $Commit = (Get-Content (Join-Path $backup.FullName 'commit.txt')).Trim()
}
Invoke-Native { & git -C $script:InstallRoot cat-file -e "$Commit^{commit}" 2>$null }
if ($LASTEXITCODE -ne 0) { throw "Version $Commit is not known to C:\Zoneflow." }

$before = Get-RequirementsHash
Stop-Zoneflow
Assert-Git @('checkout', '--quiet', $Commit)
if ((Get-RequirementsHash) -ne $before) { Install-ZoneflowRequirements }
if ($RestoreSettings) {
    if (-not $backup -or -not (Test-Path (Join-Path $backup.FullName 'zoneflow.env'))) { throw 'That backup has no settings file.' }
    Copy-Item -Force (Join-Path $backup.FullName 'zoneflow.env') $script:EnvFile
    Protect-ZoneflowFile $script:EnvFile
}
Start-Zoneflow
Write-Host "Rolled back to $((& git -C $script:InstallRoot log -1 --format='%h %s').Trim())"
if (Wait-ZoneflowHealthy -Seconds 180) { Write-Host 'Zoneflow is healthy.' -ForegroundColor Green }
else { Write-Warning 'Zoneflow is not healthy - see C:\ZoneflowData\logs.'; exit 1 }
