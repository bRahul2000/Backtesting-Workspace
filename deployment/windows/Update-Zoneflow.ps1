<#
  Update Zoneflow to the latest pushed code. Administrator PowerShell:

    powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Update-Zoneflow.ps1

  1. makes a backup in C:\ZoneflowData\backups\<date-time>\ (code version, settings, workspace data files)
  2. stops Zoneflow, downloads the new code (fast-forward only - never overwrites local history)
  3. installs Python packages only if the requirements changed
  4. starts Zoneflow and waits for the health check
  5. if it is not healthy within 3 minutes, it automatically goes back to the previous version

  Workspace data (C:\ZoneflowData\workspace) is never deleted or rebuilt by an update.
#>
param([string]$Branch = 'feature/tradingview-mode', [switch]$NoAutoRollback)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator

$dirty = & git -C $script:InstallRoot status --porcelain --untracked-files=no
if ($dirty) { throw "C:\Zoneflow has local code changes - not updating:`n$dirty" }

$previous = (& git -C $script:InstallRoot rev-parse HEAD).Trim()
$previousRequirements = Get-RequirementsHash
$backup = & (Join-Path $PSScriptRoot 'Backup-Zoneflow.ps1')
Write-Host "Backup: $backup  (current version $($previous.Substring(0, 7)))"

Stop-Zoneflow
try {
    Assert-Git @('fetch', '--prune', 'origin')
    Assert-Git @('checkout', $Branch)
    Assert-Git @('pull', '--ff-only', 'origin', $Branch)
    if ((Get-RequirementsHash) -ne $previousRequirements) {
        Write-Host 'Requirements changed - installing Python packages...'
        Install-ZoneflowRequirements
    }
} catch {
    Write-Warning "Update failed: $_"
    Write-Warning "Going back to $($previous.Substring(0, 7))."
    Invoke-Native { & git -C $script:InstallRoot checkout --quiet $previous }
    Start-Zoneflow
    exit 1
}
$current = (& git -C $script:InstallRoot rev-parse HEAD).Trim()
Write-Host "Code: $($previous.Substring(0, 7)) -> $($current.Substring(0, 7))"
Start-Zoneflow
if (Wait-ZoneflowHealthy -Seconds 180) {
    Write-Host 'Update complete - Zoneflow is healthy.' -ForegroundColor Green
    exit 0
}
if ($NoAutoRollback) { Write-Warning 'Zoneflow is NOT healthy after the update. Run Rollback-Zoneflow.ps1 to go back.'; exit 1 }
Write-Warning 'Zoneflow is NOT healthy after the update - rolling back automatically.'
& (Join-Path $PSScriptRoot 'Rollback-Zoneflow.ps1') -Commit $previous
exit 1
