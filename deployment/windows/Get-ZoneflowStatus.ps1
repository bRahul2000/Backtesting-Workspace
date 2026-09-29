# Show whether Zoneflow is running and healthy (read-only). Exit code 0 = healthy.
. (Join-Path $PSScriptRoot 'common.ps1')
foreach ($name in $script:TaskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    $state = if ($task) { $task.State } else { 'not installed' }
    Write-Host ('{0,-16} {1}' -f $name, $state)
}
$commit = Invoke-Native { & git -C $script:InstallRoot log -1 --format='%h %s (%ci)' 2>$null }
Write-Host "Code version:    $commit"
Invoke-Native { & $script:Python (Join-Path $script:InstallRoot 'tools\zoneflow_health.py') --env-file $script:EnvFile 2>$null }
exit $LASTEXITCODE
