"""Argon2id password hashing (argon2-cffi). Only hashes are ever stored; plaintext never leaves the request."""
from __future__ import annotations

import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's RFC 9106 "low memory" profile: Argon2id, 64 MiB, t=3, p=4
_HASHER = PasswordHasher()
# verifying against this when the username is wrong keeps the response time independent of the username
_DUMMY_HASH = _HASHER.hash("zoneflow-dummy-password-for-constant-time")

MIN_LENGTH = 12


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_login(username: str, password: str, expected_username: str, password_hash: str) -> bool:
    """True only for the admin username with the right password. Always runs one Argon2 verification."""
    user_ok = hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
    target = password_hash if user_ok else _DUMMY_HASH
    try:
        password_ok = _HASHER.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_ok = False
    return user_ok and password_ok


def strength_problems(password: str, username: str = "") -> list[str]:
    """Sensible admin password rules (length and variety; not the username)."""
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"at least {MIN_LENGTH} characters")
    classes = sum(any(test(c) for c in password) for test in (str.islower, str.isupper, str.isdigit,
                                                               lambda c: not c.isalnum()))
    if classes < 3:
        problems.append("at least three of: lowercase, uppercase, digits, symbols")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if len(set(password)) < 6:
        problems.append("too repetitive")
    return problems
