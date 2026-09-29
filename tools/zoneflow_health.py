"""Zoneflow health check - prints one JSON report; exit code 0 = healthy, 1 = something needs attention.

    python tools/zoneflow_health.py [--env-file C:\\ZoneflowData\\zoneflow.env] [--no-public]

Checks: the login service and Streamlit answer on 127.0.0.1; through the public HTTPS address (when ZONEFLOW_DOMAIN is
set) the login page loads and the app itself refuses a visitor without a session; and how current each MT5-backed
workspace dataset is. Read-only: it never logs in, refreshes data or changes anything. No secrets are printed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url: str, timeout: float = 5.0) -> tuple[int | None, str]:
    """(status, short body) without following redirects; (None, reason) when nothing answered."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"Accept": "text/html"}), timeout=timeout) as response:
            return response.status, response.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        return None, str(getattr(exc, "reason", exc))


def check_local(env: dict) -> dict:
    auth_port, app_port = env.get("ZONEFLOW_AUTH_PORT") or "8601", env.get("ZONEFLOW_APP_PORT") or "8501"
    auth_status, auth_body = _get(f"http://127.0.0.1:{auth_port}/zoneflow-auth/health")
    app_status, app_body = _get(f"http://127.0.0.1:{app_port}/_stcore/health")
    return {"auth_service": {"ok": auth_status == 200 and '"ok"' in auth_body, "status": auth_status},
            "streamlit": {"ok": app_status == 200 and app_body.strip() == "ok", "status": app_status}}


def check_public(domain: str) -> dict:
    login_status, _ = _get(f"https://{domain}/zoneflow-auth/login", timeout=10)
    app_status, _ = _get(f"https://{domain}/", timeout=10)
    return {"login_page": {"ok": login_status == 200, "status": login_status},
            # without a session the app must redirect to the login (303) or refuse (401) - never serve the page
            "app_requires_login": {"ok": app_status in (303, 401), "status": app_status}}


def check_data() -> dict:
    os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")      # no bare-mode warnings from the data modules
    from services.market_datasets import dataset
    from ui.tradingview_mode.component import workspace_data
    report = {"workspace": str(workspace_data.workspace_root()), "datasets": {}}
    for key in workspace_data.MT5_SOURCES:
        try:
            info = workspace_data.freshness(dataset(key))
            report["datasets"][key] = {k: info[k] for k in ("status", "last_local", "latest_available", "source")}
            if info["problems"]:
                report["datasets"][key]["problems"] = info["problems"][:3]
        except Exception as exc:                                    # a broken dataset must not hide the others
            report["datasets"][key] = {"status": "ERROR", "problems": [f"{type(exc).__name__}: {exc}"]}
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Zoneflow health check (read-only).")
    parser.add_argument("--env-file", default=os.environ.get("ZONEFLOW_ENV_FILE"))
    parser.add_argument("--no-public", action="store_true", help="skip the checks through the public HTTPS address")
    parser.add_argument("--no-data", action="store_true", help="skip the dataset freshness report")
    args = parser.parse_args(argv)
    if args.env_file:
        os.environ["ZONEFLOW_ENV_FILE"] = args.env_file
    from services.auth.config import environment
    env = environment()
    for key in ("TV_WORKSPACE_DATA", "TV_MT5_COMMON_FILES"):       # the data check reads these like the app does
        if env.get(key):
            os.environ[key] = env[key]

    report = {"checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), **check_local(env)}
    domain = env.get("ZONEFLOW_DOMAIN")
    if domain and not args.no_public:
        report["public"] = check_public(domain)
    if not args.no_data:
        report["data"] = check_data()
    services = [report["auth_service"], report["streamlit"], *report.get("public", {}).values()]
    report["healthy"] = all(item["ok"] for item in services)
    print(json.dumps(report, indent=2))
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
