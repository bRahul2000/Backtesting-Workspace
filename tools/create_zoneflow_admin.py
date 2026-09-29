"""Create (or replace) the Zoneflow admin login - run it on the server, never paste passwords into chat or Git.

    python tools/create_zoneflow_admin.py --env-file C:\\ZoneflowData\\zoneflow.env

It asks for a username and a password (typed twice, not shown), checks the password is strong enough, and writes to
the private env file ONLY:

  ZONEFLOW_ADMIN_USERNAME, ZONEFLOW_ADMIN_PASSWORD_HASH (Argon2id), ZONEFLOW_SESSION_SECRET (new random),
  ZONEFLOW_PROXY_TOKEN (new random)

Other settings already in the file are kept. Nothing secret is printed. A new session secret logs out every open
session; restart the Zoneflow services afterwards so the proxy and the app use the new values.
"""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.auth.passwords import hash_password, strength_problems   # noqa: E402

AUTH_KEYS = ("ZONEFLOW_ADMIN_USERNAME", "ZONEFLOW_ADMIN_PASSWORD_HASH", "ZONEFLOW_SESSION_SECRET", "ZONEFLOW_PROXY_TOKEN")


def credential_values(username: str, password: str) -> dict[str, str]:
    problems = strength_problems(password, username)
    if problems:
        raise ValueError("password too weak: " + "; ".join(problems))
    return {"ZONEFLOW_ADMIN_USERNAME": username, "ZONEFLOW_ADMIN_PASSWORD_HASH": hash_password(password),
            "ZONEFLOW_SESSION_SECRET": secrets.token_hex(32), "ZONEFLOW_PROXY_TOKEN": secrets.token_urlsafe(32)}


def write_env(path: Path, values: dict[str, str]) -> None:
    """Replace the auth keys in the env file (creating it), keeping every other line; owner-only permissions."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
        "# Zoneflow private settings - NEVER commit or share this file"]
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in values]
    kept += [f"{key}={value}" for key, value in values.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def valid_username(name: str) -> bool:
    return 3 <= len(name) <= 64 and all(c.isalnum() or c in "._-@" for c in name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the Zoneflow admin login (writes only a password hash).")
    parser.add_argument("--env-file", default=os.environ.get("ZONEFLOW_ENV_FILE", "zoneflow.env"),
                        help="private env file to update (default: $ZONEFLOW_ENV_FILE or ./zoneflow.env)")
    args = parser.parse_args(argv)
    path = Path(args.env_file)
    try:
        repo = Path(__file__).resolve().parents[1]
        path.resolve().relative_to(repo)
        print(f"Refusing to write secrets inside the Git repository ({repo}). Use a path such as "
              "C:\\ZoneflowData\\zoneflow.env.", file=sys.stderr)
        return 2
    except ValueError:
        pass
    username = input("Admin username: ").strip()
    while not valid_username(username):
        username = input("Username (3-64 letters, digits, . _ - @): ").strip()
    while True:
        password = getpass("Password (not shown): ")
        problems = strength_problems(password, username)
        if problems:
            print("Please choose a stronger password: " + "; ".join(problems))
            continue
        if getpass("Repeat password: ") != password:
            print("The passwords do not match.")
            continue
        break
    write_env(path, credential_values(username, password))
    print(f"Admin login saved to {path} (password stored only as an Argon2id hash; new session secret and proxy "
          "token). Restart the Zoneflow services so they pick it up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
