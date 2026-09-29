# Zoneflow on the Windows server — step-by-step guide

This guide puts Zoneflow on the Windows server that already runs MetaTrader 5, behind a private login and HTTPS.
You do not need to write code. Copy each command exactly as shown.

> **Safety.** Zoneflow only *reads* MT5 data files. Trading and execution stay **disabled**: there is no order
> placement for MT5 or Binance, and no webhooks. These steps never change MetaTrader 5, its login, or your
> Remote Desktop (RDP) access.

## How it fits together

```
Browser ──HTTPS 443──► Caddy (automatic certificate)
                          ├─ /zoneflow-auth/*  ──► login service   127.0.0.1:8601
                          └─ everything else   ──► login check ──► Zoneflow (Streamlit) 127.0.0.1:8501
```

* Only ports **443** (and **80**, used for the certificate) are open to the internet. Ports 8501 and 8601 listen on
  the server itself and are also blocked in Windows Firewall.
* Every page, data request and live connection needs a valid login first. Without one, you only ever see the login
  page.
* **Sessions.** A login lasts at most 12 hours. It also ends after 2 hours without use, or when you click
  **Log out**.
* **Failed logins.** After 5 wrong attempts, the login is paused for 30 seconds. The pause doubles with each further
  wrong attempt, up to 15 minutes. The error message never says which part was wrong.
* **Password storage.** The password is never stored. Only a one-way Argon2id hash is kept, in a private settings
  file that is not in Git.

| Folder | What is in it | Changed by |
|---|---|---|
| `C:\Zoneflow` | the program (Git checkout) and its Python environment `.venv` | install / update / rollback |
| `C:\ZoneflowData\zoneflow.env` | private settings: login hash, secrets, domain | install, `New-ZoneflowAdmin.ps1` |
| `C:\ZoneflowData\workspace` | chart data extended from MT5 (separate from research data) | Zoneflow itself |
| `C:\ZoneflowData\logs` | logs (each capped at 5–10 MB, older ones rotated) | the services |
| `C:\ZoneflowData\backups` | a backup made before every update (the newest 10 are kept) | update |

## Before you start (one-time)

1. **Domain.** Choose a name, for example `zoneflow.yourdomain.com`. At your domain provider, create a **DNS A
   record** pointing that name to the server's public IP address. Wait until
   `nslookup zoneflow.yourdomain.com` shows that IP.
2. **AWS security group.** Allow inbound **TCP 443** and **TCP 80** from anywhere. Do not open 8501 or 8601. Leave
   the existing RDP rule as it is.
3. On the server, install:
   * **Git for Windows**: https://git-scm.com/download/win (the default options are fine).
   * **Python 3.12 (64-bit)**: https://www.python.org/downloads/windows/. Tick *"Add python.exe to PATH"*.

## Install

Open **PowerShell as administrator**: Start menu → type *PowerShell* → right-click → *Run as administrator*.

```powershell
git clone --branch feature/tradingview-mode https://github.com/bRahul2000/Backtesting-Workspace.git C:\Zoneflow
powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Install-Zoneflow.ps1 -Domain zoneflow.yourdomain.com
```

If Git asks you to sign in to GitHub, sign in: the repository is private.

The installer:

1. installs the pinned packages, including Streamlit 1.37.1;
2. downloads Caddy and checks its checksum;
3. finds MetaTrader 5's data folder;
4. **asks you to create the admin login**. Type a username, then a password twice. The password is not shown while
   you type. It needs at least 12 characters and a mix of letters, numbers and symbols.
5. sets up the firewall and three start-at-boot tasks, then starts everything.

Then open `https://zoneflow.yourdomain.com` and log in.

> Never send the password (or the contents of `zoneflow.env`) through chat or e-mail, and never add them to Git.

## Everyday commands (administrator PowerShell)

Every script is in `C:\Zoneflow\deployment\windows\`. Run each one like this:
`powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\<script>`

| Script | What it does |
|---|---|
| `Get-ZoneflowStatus.ps1` | Shows whether everything is running, plus the code version and data freshness. Changes nothing. |
| `Start-Zoneflow.ps1` / `Stop-Zoneflow.ps1` | Starts or stops Zoneflow. MT5 and RDP are not affected. |
| `Update-Zoneflow.ps1` | Backs up, fetches the latest code and restarts. It **goes back automatically** if the new version is unhealthy. |
| `Rollback-Zoneflow.ps1` | Returns to the version from before the last update (or `-Commit <version>`). |
| `Backup-Zoneflow.ps1` | Makes a backup now. |
| `New-ZoneflowAdmin.ps1` | Changes the username or password. This logs everyone out. |
| `Uninstall-ZoneflowTasks.ps1` | Removes the start-at-boot tasks and firewall rules. Code and data are kept. |

Zoneflow starts by itself after a reboot. If any part crashes, it restarts within a minute.

## Updating

```powershell
powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Update-Zoneflow.ps1
```

The update:

1. backs up the code version, settings and workspace data;
2. downloads the new code (fast-forward only, so history is never rewritten);
3. reinstalls packages only if they changed;
4. restarts Zoneflow and waits up to 3 minutes for it to become healthy.

If it is not healthy, the update returns to the previous version by itself. Workspace data is never deleted or
rebuilt by an update.

## Rollback

```powershell
powershell -ExecutionPolicy Bypass -File C:\Zoneflow\deployment\windows\Rollback-Zoneflow.ps1
```

* With no options, it returns to the version recorded in the newest backup.
* Add `-Commit 4cbc1da` to choose a specific version.
* Add `-RestoreSettings` to also put back that backup's `zoneflow.env`.
* Workspace data is left as it is. An older version reads it fine. Each backup also holds a copy in its `workspace`
  folder, which you can copy back by hand if ever needed.

## Logs and health

* **Logs** are in `C:\ZoneflowData\logs`:
  * `auth.log`: logins, failures and lockouts. It never contains passwords.
  * `app.stderr.log`: Zoneflow.
  * `proxy.stderr.log`: Caddy and certificates.
  * `caddy-access.log`: web requests. Cookies are hidden by Caddy.
* **Health.** `Get-ZoneflowStatus.ps1` prints a report and ends with `"healthy": true` when the login service,
  Zoneflow and the public HTTPS address all answer correctly. It also checks that the app refuses visitors who are
  not logged in, and shows how current each MT5 dataset is.

## Troubleshooting

| Problem | What to check |
|---|---|
| The browser says the site can't be reached | Is the DNS A record pointing to this server? Is port 443 open in the AWS security group? Run `Get-ZoneflowStatus.ps1`. |
| Certificate or HTTPS error | Port 80 must also be open for the first certificate. See `proxy.stderr.log`. |
| "Too many attempts" | Wait for the time shown (at most 15 minutes), then try again. |
| Forgot the password | Run `New-ZoneflowAdmin.ps1` on the server to set a new one. |
| Charts show old MT5 data | Is MetaTrader 5 running with the Zoneflow export EA? Check `TV_MT5_COMMON_FILES` in `zoneflow.env`. |

## Settings file reference

The settings file is `C:\ZoneflowData\zoneflow.env`. See the template in `deployment\.env.example`.

The installer and `New-ZoneflowAdmin.ps1` fill it in, so you normally never edit it by hand. It must stay out of Git
and must never be shared.
