<#
  Back up what cannot be rebuilt from Git: settings (zoneflow.env), the workspace data folder and the running code
  version. Writes C:\ZoneflowData\backups\<yyyyMMdd-HHmmss>\ and prints that folder. Keeps the newest 10 backups.
  The backup contains the private settings, so the folder is readable by administrators only.
#>
. (Join-Path $PSScriptRoot 'common.ps1')
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$target = Join-Path $script:BackupDir $stamp
New-Item -ItemType Directory -Force -Path $target | Out-Null
(& git -C $script:InstallRoot rev-parse HEAD).Trim() | Set-Content (Join-Path $target 'commit.txt')
Get-RequirementsHash | Set-Content (Join-Path $target 'requirements.sha256')
if (Test-Path $script:EnvFile) {
    Copy-Item $script:EnvFile (Join-Path $target 'zoneflow.env')
    Protect-ZoneflowFile (Join-Path $target 'zoneflow.env')
}
$workspace = Join-Path $script:DataRoot 'workspace'
if (Test-Path $workspace) { Copy-Item -Recurse $workspace (Join-Path $target 'workspace') }
Get-ChildItem $script:BackupDir -Directory | Sort-Object Name -Descending | Select-Object -Skip 10 |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
Write-Output $target
