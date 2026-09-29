"""The login page (served by the login service before anything of Zoneflow loads). Self-contained HTML: no scripts,
no external requests, no market data."""
from __future__ import annotations

from html import escape

_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0b0e14; color: #d5dbe5;
  font: 14px/1.4 Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.card { width: min(360px, calc(100vw - 32px)); background: #10141b; border: 1px solid #222935; border-radius: 10px;
  padding: 28px 28px 22px; box-shadow: 0 18px 50px rgba(0,0,0,.45); }
h1 { margin: 0; font-size: 20px; letter-spacing: 3px; font-weight: 700; }
.sub { margin: 4px 0 22px; color: #6f7a8c; font-size: 12.5px; }
label { display: block; font-size: 12px; color: #aab3c2; margin: 12px 0 5px; }
input[type=text], input[type=password] { width: 100%; height: 38px; padding: 0 11px; border-radius: 6px;
  border: 1px solid #2a3140; background: #0b0e14; color: #d5dbe5; font: inherit; }
input:focus { outline: none; border-color: #3d8bfd; box-shadow: 0 0 0 3px rgba(61,139,253,.18); }
button { width: 100%; height: 40px; margin-top: 20px; border: 0; border-radius: 6px; background: #3d8bfd; color: #fff;
  font-family: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
button:hover { background: #2f7cf0; }
.error { margin-top: 14px; padding: 8px 10px; border-radius: 6px; background: rgba(242,54,69,.1);
  border: 1px solid rgba(242,54,69,.35); color: #f7a8b0; font-size: 12.5px; }
.note { margin-top: 12px; padding: 8px 10px; border-radius: 6px; background: rgba(61,139,253,.08); color: #aab3c2; font-size: 12.5px; }
.foot { margin-top: 18px; color: #6f7a8c; font-size: 11.5px; text-align: center; }
"""


def login_page(*, csrf: str, next_path: str = "/", error: str | None = None, notice: str | None = None) -> str:
    message = f'<div class="error" role="alert">{escape(error)}</div>' if error else ""
    info = f'<div class="note">{escape(notice)}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Zoneflow · Sign in</title><style>{_STYLE}</style></head>
<body><main class="card">
<h1>ZONEFLOW</h1><div class="sub">Private Trading Research Terminal</div>
<form method="post" action="/zoneflow-auth/login" autocomplete="on">
<input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="next" value="{escape(next_path)}">
<label for="username">Username</label><input id="username" name="username" type="text" autocomplete="username" required autofocus>
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Log in</button>
</form>{message}{info}
<div class="foot">Private system &bull; Authorized access only</div>
</main></body></html>"""
