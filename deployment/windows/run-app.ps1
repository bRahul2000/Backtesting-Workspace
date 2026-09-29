# Scheduled task "Zoneflow-App": Streamlit on 127.0.0.1 only, production login mode, restarted if it stops.
. (Join-Path $PSScriptRoot 'common.ps1')
$values = Import-ZoneflowEnv
$env:ZONEFLOW_AUTH_MODE = 'proxy'                      # production: every request needs a login (never 'off' here)
$port = if ($values['ZONEFLOW_APP_PORT']) { $values['ZONEFLOW_APP_PORT'] } else { '8501' }
Invoke-Supervised -Name 'app' -FilePath $script:Python -WorkingDirectory $script:InstallRoot -Arguments @(
    '-m', 'streamlit', 'run', 'app.py',
    '--server.headless', 'true', '--server.address', '127.0.0.1', '--server.port', $port,
    '--browser.gatherUsageStats', 'false', '--server.fileWatcherType', 'none', '--global.developmentMode', 'false')
