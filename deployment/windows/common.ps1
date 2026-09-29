# Shared helpers for the Zoneflow Windows scripts (dot-sourced; nothing here runs on its own).
# Layout:  C:\Zoneflow        code (Git checkout) + .venv                          (changed only by updates)
#          C:\ZoneflowData    zoneflow.env, workspace, auth, logs, backups, caddy, bin\caddy.exe (kept across updates)

$ErrorActionPreference = 'Stop'
$script:InstallRoot = if ($env:ZONEFLOW_INSTALL_ROOT) { $env:ZONEFLOW_INSTALL_ROOT } else { 'C:\Zoneflow' }
$script:DataRoot    = if ($env:ZONEFLOW_DATA_ROOT) { $env:ZONEFLOW_DATA_ROOT } else { 'C:\ZoneflowData' }
$script:EnvFile     = Join-Path $script:DataRoot 'zoneflow.env'
$script:LogDir      = Join-Path $script:DataRoot 'logs'
$script:Python      = Join-Path $script:InstallRoot '.venv\Scripts\python.exe'
$script:Caddy       = Join-Path $script:DataRoot 'bin\caddy.exe'
$script:BackupDir   = Join-Path $script:DataRoot 'backups'
$script:TaskNames   = @('Zoneflow-Auth', 'Zoneflow-App', 'Zoneflow-Proxy')

function Read-ZoneflowEnv {
    # KEY=VALUE lines, '#' comments, no variable expansion (Argon2 hashes contain '$') - same rules as config.py.
    param([string]$Path = $script:EnvFile)
    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($raw in [System.IO.File]::ReadAllLines($Path)) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
        $index = $line.IndexOf('=')
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'") -and $value[-1] -eq $value[0]) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Set-ZoneflowEnvValue {
    # Set one non-secret setting in zoneflow.env, keeping every other line.
    param([string]$Key, [string]$Value, [string]$Path = $script:EnvFile)
    $lines = @()
    if (Test-Path -LiteralPath $Path) { $lines = [System.IO.File]::ReadAllLines($Path) }
    $kept = @($lines | Where-Object { -not ($_.Split('=')[0].Trim() -eq $Key) })
    $kept += "$Key=$Value"
    [System.IO.File]::WriteAllLines($Path, [string[]]$kept)
}

function Import-ZoneflowEnv {
    # Load zoneflow.env into this process's environment (for the service supervisors).
    $values = Read-ZoneflowEnv
    foreach ($key in $values.Keys) { [Environment]::SetEnvironmentVariable($key, $values[$key], 'Process') }
    [Environment]::SetEnvironmentVariable('ZONEFLOW_ENV_FILE', $script:EnvFile, 'Process')
    return $values
}

function Protect-ZoneflowFile {
    # Only SYSTEM and Administrators may read a secrets file (zoneflow.env, backups of it).
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    & icacls $Path /inheritance:r /grant:r 'SYSTEM:(F)' 'Administrators:(F)' | Out-Null
}

function Write-ZoneflowLog {
    param([string]$Name, [string]$Message)
    New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
    $file = Join-Path $script:LogDir "$Name.log"
    if ((Test-Path $file) -and (Get-Item $file).Length -gt 5MB) {        # bounded: keep 5 rotated files
        for ($i = 4; $i -ge 1; $i--) {
            $src = "$file.$i"; if (Test-Path $src) { Move-Item -Force $src "$file.$($i + 1)" }
        }
        Move-Item -Force $file "$file.1"
    }
    Add-Content -Path $file -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

function Invoke-Supervised {
    # Run a process forever: restart it after a crash with a growing pause (5 s .. 60 s), log every start and exit.
    param([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory)
    $delay = 5
    while ($true) {
        Write-ZoneflowLog $Name "starting: $FilePath"
        $stdout = Join-Path $script:LogDir "$Name.stdout.log"
        $stderr = Join-Path $script:LogDir "$Name.stderr.log"
        foreach ($f in @($stdout, $stderr)) { if ((Test-Path $f) -and (Get-Item $f).Length -gt 5MB) { Move-Item -Force $f "$f.old" } }
        $started = Get-Date
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
            -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $process.WaitForExit()
        Write-ZoneflowLog $Name "exited with code $($process.ExitCode) after $([int]((Get-Date) - $started).TotalSeconds) s"
        if (((Get-Date) - $started).TotalMinutes -gt 10) { $delay = 5 } else { $delay = [Math]::Min(60, $delay * 2) }
        Start-Sleep -Seconds $delay
    }
}

function Find-Mt5CommonFiles {
    # MetaTrader 5's Common\Files folder of any Windows user on this machine (the one with Zoneflow files first).
    $candidates = @(Get-ChildItem -Path 'C:\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        Join-Path $_.FullName 'AppData\Roaming\MetaQuotes\Terminal\Common\Files' } | Where-Object { Test-Path $_ })
    $withData = @($candidates | Where-Object {
        (Get-ChildItem -Path $_ -Filter 'tv_live_*' -ErrorAction SilentlyContinue) -or
        (Get-ChildItem -Path $_ -Filter 'xauusd_XAUUSDm_*' -ErrorAction SilentlyContinue) })
    if ($withData.Count -gt 0) { return $withData[0] }
    if ($candidates.Count -gt 0) { return $candidates[0] }
    return $null
}

function Assert-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Please run this script in PowerShell opened with "Run as administrator".'
    }
}

function Start-Zoneflow { foreach ($name in $script:TaskNames) { Start-ScheduledTask -TaskName $name } }

function Stop-Zoneflow {
    # Ending a task stops its supervisor; then stop the processes it started, recognised by their command lines
    # (a venv python.exe hands over to the base interpreter, so the executable path alone is not enough).
    foreach ($name in $script:TaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $name }
    }
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and (($_.CommandLine -like '*streamlit*run*app.py*' -and $_.CommandLine -like '*--server.address*127.0.0.1*') -or
            $_.CommandLine -like '*-m services.auth.server*' -or
            ($_.ExecutablePath -eq $script:Caddy))
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Wait-ZoneflowHealthy {
    # Poll the health check until the services answer (or the time is up). Returns $true when healthy.
    param([int]$Seconds = 120, [switch]$LocalOnly)
    $deadline = (Get-Date).AddSeconds($Seconds)
    $extra = @('--no-data'); if ($LocalOnly) { $extra += '--no-public' }
    do {
        Start-Sleep -Seconds 5
        Invoke-Native { & $script:Python (Join-Path $script:InstallRoot 'tools\zoneflow_health.py') --env-file $script:EnvFile @extra 2>$null | Out-Null }
        if ($LASTEXITCODE -eq 0) { return $true }
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Get-RequirementsHash {
    $file = Join-Path $script:InstallRoot 'deployment\requirements-production.txt'
    if (Test-Path $file) { return (Get-FileHash -Algorithm SHA256 $file).Hash }
    return ''
}

function Install-ZoneflowRequirements {
    & $script:Python -m pip install --disable-pip-version-check -q -r (Join-Path $script:InstallRoot 'deployment\requirements-production.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Installing the Python packages failed (see the messages above).' }
}

function Invoke-Native {
    # Run a native program whose stderr may carry harmless messages: Windows PowerShell 5.1 would turn redirected
    # stderr lines into terminating errors under ErrorActionPreference=Stop. Callers check $LASTEXITCODE.
    param([scriptblock]$Block)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $saved }
}

function Assert-Git { param([string[]]$Arguments)
    Invoke-Native { & git -C $script:InstallRoot @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed" }
}
