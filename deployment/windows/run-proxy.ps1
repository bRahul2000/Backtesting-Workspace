# Scheduled task "Zoneflow-Proxy": Caddy (HTTPS on 443, automatic certificate) in front of Zoneflow.
. (Join-Path $PSScriptRoot 'common.ps1')
$values = Import-ZoneflowEnv
if (-not $values['ZONEFLOW_DOMAIN']) { throw 'ZONEFLOW_DOMAIN is not set in zoneflow.env' }
$env:ZONEFLOW_SITE_ADDRESS = $values['ZONEFLOW_DOMAIN']
$env:ZONEFLOW_LOG_DIR = $script:LogDir
$env:XDG_DATA_HOME = Join-Path $script:DataRoot 'caddy'        # certificates live with the data, not in System32
$env:XDG_CONFIG_HOME = Join-Path $script:DataRoot 'caddy'
Invoke-Supervised -Name 'proxy' -FilePath $script:Caddy -WorkingDirectory $script:DataRoot -Arguments @(
    'run', '--config', (Join-Path $script:InstallRoot 'deployment\Caddyfile'), '--adapter', 'caddyfile')
