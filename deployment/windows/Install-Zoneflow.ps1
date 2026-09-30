<#
  Install Zoneflow on this Windows server (run once, in PowerShell opened with "Run as administrator").

    powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Install-Zoneflow.ps1 -Domain zoneflow.example.com

  What it does (safe to run again - every step checks what is already there):
    1. checks Git and Python 3.12 are installed
    2. creates C:\ZoneflowData\{workspace,logs,backups,auth,caddy,bin}
    3. gets the code into C:\Zoneflow (clones it if missing) on the chosen branch
    4. creates C:\Zoneflow\.venv and installs the pinned packages (Streamlit 1.37.1 ...)
    5. downloads Caddy (the HTTPS server) and checks its SHA-512 checksum before using it
    6. writes the non-secret settings to C:\ZoneflowData\zoneflow.env (finds MetaTrader 5's Common\Files folder)
    7. asks for the admin login if none exists yet (typed here, stored only as a hash - never in chat or Git)
    8. opens ports 80 + 443 in Windows Firewall and blocks 8501/8601 from outside. RDP (3389) is NOT touched.
    9. registers three start-at-boot tasks (Zoneflow-Auth, Zoneflow-App, Zoneflow-Proxy) and starts them,
       plus the Telemetry V1 daily reconciliation and 5-minute watchdog tasks (observe only)

  Nothing here enables trading: Zoneflow only reads MT5 data files; execution stays disabled.
#>
param(
    [string]$Domain = '',
    [string]$Branch = 'feature/tradingview-mode',
    [string]$RepoUrl = 'https://github.com/bRahul2000/Backtesting-Workspace.git',
    [string]$PythonExe = '',
    [switch]$SkipStart
)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Administrator

$CaddyVersion = '2.11.4'
$CaddySha512 = 'cd5ccfd86a4b40732cf715890d0dca5bf3f63adefec5a7914de85adf240c60ce7e5d2791631b88ef9758e46b23bb1730e020b9c5d696889740b284ffd4788e35'

function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }

# 1. prerequisites -------------------------------------------------------------------------------------------------
Step 'Checking Git and Python'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is not installed. Install it from https://git-scm.com/download/win (default options), then run this again.'
}
if (-not $PythonExe) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonExe = Invoke-Native { & py -3.12 -c 'import sys; print(sys.executable)' 2>$null }
    }
    if (-not $PythonExe) {
        throw 'Python 3.12 was not found. Install Python 3.12 (64-bit) from https://www.python.org/downloads/windows/ ' +
              '(tick "Add python.exe to PATH"), then run this again.'
    }
}
$version = & $PythonExe -c 'import sys; print("%d.%d" % sys.version_info[:2])'
if ($version -ne '3.12') { throw "Python 3.12 is required (found $version at $PythonExe)." }
Write-Host "Python: $PythonExe"

# 2. folders -------------------------------------------------------------------------------------------------------
Step 'Creating folders'
foreach ($sub in @('workspace', 'logs', 'backups', 'auth', 'caddy', 'bin', 'telemetry')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $script:DataRoot $sub) | Out-Null
}
& icacls $script:DataRoot /inheritance:r /grant:r 'SYSTEM:(OI)(CI)(F)' 'Administrators:(OI)(CI)(F)' | Out-Null

# 3. code ----------------------------------------------------------------------------------------------------------
Step "Getting the code ($Branch)"
if (-not (Test-Path (Join-Path $script:InstallRoot '.git'))) {
    if ((Test-Path $script:InstallRoot) -and (Get-ChildItem $script:InstallRoot -Force | Select-Object -First 1)) {
        throw "$($script:InstallRoot) exists but is not a Git checkout. Move it away, then run this again."
    }
    Invoke-Native { & git clone --branch $Branch $RepoUrl $script:InstallRoot }
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed (for a private repository, sign in to GitHub when Git asks).' }
} else {
    Write-Host "Code already present at $($script:InstallRoot) (use Update-Zoneflow.ps1 to update it)."
}

# 4. Python environment --------------------------------------------------------------------------------------------
Step 'Installing Python packages (a few minutes the first time)'
if (-not (Test-Path $script:Python)) {
    & $PythonExe -m venv (Join-Path $script:InstallRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
}
& $script:Python -m pip install --disable-pip-version-check -q --upgrade pip
Install-ZoneflowRequirements
& $script:Python -c 'import streamlit, argon2; assert streamlit.__version__ == "1.37.1", streamlit.__version__'
if ($LASTEXITCODE -ne 0) { throw 'Streamlit 1.37.1 / argon2 check failed after install.' }

# 5. Caddy ---------------------------------------------------------------------------------------------------------
Step "Installing Caddy $CaddyVersion"
if (-not (Test-Path $script:Caddy) -or -not ((& $script:Caddy version) -like "v$CaddyVersion*")) {
    $zip = Join-Path $env:TEMP "caddy_$CaddyVersion.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -OutFile $zip `
        "https://github.com/caddyserver/caddy/releases/download/v$CaddyVersion/caddy_${CaddyVersion}_windows_amd64.zip"
    $actual = (Get-FileHash -Algorithm SHA512 $zip).Hash.ToLower()
    if ($actual -ne $CaddySha512) { Remove-Item $zip; throw "Caddy download checksum mismatch ($actual) - not installed." }
    $unpack = Join-Path $env:TEMP "caddy_$CaddyVersion"
    Expand-Archive -Force $zip $unpack
    Copy-Item -Force (Join-Path $unpack 'caddy.exe') $script:Caddy
    Remove-Item -Recurse -Force $zip, $unpack
}
Write-Host (& $script:Caddy version)

# 6. settings ------------------------------------------------------------------------------------------------------
Step 'Writing settings'
if (-not (Test-Path $script:EnvFile)) {
    Set-Content -Path $script:EnvFile -Value '# Zoneflow private settings - NEVER commit or share this file'
}
Protect-ZoneflowFile $script:EnvFile
$settings = [ordered]@{
    ZONEFLOW_AUTH_MODE = 'proxy'; ZONEFLOW_AUTH_PORT = '8601'; ZONEFLOW_APP_PORT = '8501'
    ZONEFLOW_AUTH_STATE_DIR = (Join-Path $script:DataRoot 'auth'); ZONEFLOW_LOG_DIR = $script:LogDir
    TV_WORKSPACE_DATA = (Join-Path $script:DataRoot 'workspace')
    ZONEFLOW_TELEMETRY_ROOT = (Join-Path $script:DataRoot 'telemetry')
}
if ($Domain) { $settings['ZONEFLOW_DOMAIN'] = $Domain; $settings['ZONEFLOW_PUBLIC_BASE_URL'] = "https://$Domain" }
$mt5 = Find-Mt5CommonFiles
if ($mt5) { $settings['TV_MT5_COMMON_FILES'] = $mt5; Write-Host "MetaTrader 5 data folder: $mt5" }
else { Write-Warning 'MetaTrader 5 Common\Files folder not found - live MT5 data will be unavailable until TV_MT5_COMMON_FILES is set in zoneflow.env.' }
foreach ($key in $settings.Keys) { Set-ZoneflowEnvValue $key $settings[$key] }

# 7. admin login ---------------------------------------------------------------------------------------------------
$current = Read-ZoneflowEnv
if (-not $current['ZONEFLOW_ADMIN_PASSWORD_HASH']) {
    Step 'Create the admin login (typed here only; the password is stored as a one-way hash)'
    & (Join-Path $PSScriptRoot 'New-ZoneflowAdmin.ps1') -NoRestart
}

# 8. firewall ------------------------------------------------------------------------------------------------------
Step 'Firewall: allow 80/443, block 8501/8601 from outside (RDP untouched)'
foreach ($rule in @('Zoneflow HTTPS', 'Zoneflow internal ports blocked')) {
    Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
New-NetFirewallRule -DisplayName 'Zoneflow HTTPS' -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow | Out-Null
New-NetFirewallRule -DisplayName 'Zoneflow internal ports blocked' -Direction Inbound -Protocol TCP `
    -LocalPort 8501, 8601, 2019 -Action Block | Out-Null

# 9. start-at-boot tasks -------------------------------------------------------------------------------------------
Step 'Registering start-at-boot tasks'
$shell = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path $shell)) { $shell = 'powershell.exe' }
$taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$scripts = @{ 'Zoneflow-Auth' = 'run-auth.ps1'; 'Zoneflow-App' = 'run-app.ps1'; 'Zoneflow-Proxy' = 'run-proxy.ps1' }
foreach ($name in $script:TaskNames) {
    $file = Join-Path $script:InstallRoot "deployment\windows\$($scripts[$name])"
    $action = New-ScheduledTaskAction -Execute $shell -WorkingDirectory $script:InstallRoot `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$file`""
    Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Settings $taskSettings -Principal $principal -Force | Out-Null
    Write-Host "  $name"
}
& (Join-Path $PSScriptRoot 'Register-ZoneflowTelemetry.ps1')

if ($SkipStart) { Write-Host 'Installed. Start with Start-Zoneflow.ps1.'; exit 0 }
if (-not (Read-ZoneflowEnv)['ZONEFLOW_DOMAIN']) {
    Write-Warning 'No domain set yet: run this again with -Domain your.domain once its DNS A record points at this server.'
    exit 0
}
Step 'Starting Zoneflow'
Stop-Zoneflow
Start-Zoneflow
if (Wait-ZoneflowHealthy -Seconds 180) {
    Write-Host "Zoneflow is running: https://$((Read-ZoneflowEnv)['ZONEFLOW_DOMAIN'])" -ForegroundColor Green
} else {
    Write-Warning 'Zoneflow did not report healthy yet. Run Get-ZoneflowStatus.ps1 and see C:\ZoneflowData\logs.'
    exit 1
}
