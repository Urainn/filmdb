"""
Moodluma 通用狀態同步：user / room blob 存在 Sheets moodluma_state。
"""

from __future__ import annotations

from typing import Any

DEFAULT_USER_STATE = {
    "favorites": [],
    "history": [],
    "settings": {},
    "feedbacks": {},
    "viewCounts": {},
    "bubbleMode": "normal",
    "tagSearchHistory": [],
}

DEFAULT_ROOM_STATE = {
    "members": [],
    "votes": {},
}


def normalize_sync_scope(scope: str) -> str:
    s = (scope or "").strip().lower()
    if s in ("user", "room"):
        return s
    return ""


def normalize_sync_owner(scope: str, owner: str) -> str:
    raw = (owner or "").strip()
    if not raw:
        return ""
    if scope == "user":
        return raw
    # room：與前端 ROOM-G72NSS 對齊為後端 6 碼
    code = raw.upper().replace(" ", "")
    if code.startswith("ROOM-"):
        code = code[5:]
    return code


def default_state(scope: str) -> dict[str, Any]:
    if scope == "room":
        return dict(DEFAULT_ROOM_STATE)
    out = dict(DEFAULT_USER_STATE)
    return out


def merge_state(existing: dict | None, incoming: dict | None) -> dict[str, Any]:
    """Shallow merge：只覆寫 request.data 有提供的頂層欄位。"""
    base = dict(existing or {})
    if not isinstance(incoming, dict):
        return base
    for key, val in incoming.items():
        base[key] = val
    return base
