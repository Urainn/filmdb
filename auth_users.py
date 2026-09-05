"""
Moodluma 會員帳號：寫入 Google Sheets（密碼以 PBKDF2 雜湊儲存，不存明文）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

from user_sync import utc_now

AUTH_USERS_SHEET_DEFAULT = "moodluma_users"
PBKDF2_ITERATIONS = 120_000
USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff\-.]{2,32}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_username(name: str) -> str:
    return (name or "").strip()


def username_key(name: str) -> str:
    return normalize_username(name).lower()


def validate_username(name: str) -> str | None:
    n = normalize_username(name)
    if not n:
        return "缺少帳號"
    if not USERNAME_RE.match(n):
        return "帳號需 2–32 字，可含中英文、數字、_ - ."
    return None


def validate_email(email: str) -> str | None:
    e = (email or "").strip()
    if not e:
        return "缺少 Email"
    if not EMAIL_RE.match(e):
        return "Email 格式不正確"
    return None


def validate_password(password: str) -> str | None:
    if not password:
        return "缺少密碼"
    if len(password) < 6:
        return "密碼至少需要 6 個字元"
    if len(password) > 128:
        return "密碼過長"
    return None


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return digest, salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    if not password_hash or not salt:
        return False
    digest, _ = hash_password(password, salt)
    return hmac.compare_digest(digest, password_hash)


def public_user(doc: dict | None) -> dict[str, Any]:
    doc = doc or {}
    return {
        "username": normalize_username(doc.get("username") or ""),
        "email": (doc.get("email") or "").strip(),
        "createdAt": doc.get("createdAt") or "",
        "passwordUpdatedAt": doc.get("passwordUpdatedAt") or "",
    }


def normalize_auth_user(doc: dict | None) -> dict[str, Any]:
    if not doc:
        doc = {}
    return {
        "username": normalize_username(doc.get("username") or ""),
        "email": (doc.get("email") or "").strip(),
        "passwordHash": (doc.get("passwordHash") or "").strip(),
        "salt": (doc.get("salt") or "").strip(),
        "createdAt": doc.get("createdAt") or utc_now(),
        "passwordUpdatedAt": doc.get("passwordUpdatedAt") or "",
    }
