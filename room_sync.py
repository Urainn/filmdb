"""
Multi-player room codes: random unique push codes with persisted room records.
"""

from __future__ import annotations

import secrets
from typing import Any

from user_sync import utc_now

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6
MAX_CODE_ATTEMPTS = 200


def normalize_room_code(code: str) -> str:
    return (code or "").strip().upper()


def generate_room_code(existing: set[str]) -> str:
    """Return a random room code not present in existing (case-insensitive)."""
    taken = {normalize_room_code(c) for c in existing if c}
    for _ in range(MAX_CODE_ATTEMPTS):
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
        if code not in taken:
            return code
    raise RuntimeError("無法產生唯一房間代碼，請稍後再試")


def normalize_room(doc: dict | None) -> dict[str, Any]:
    if not doc:
        doc = {}
    members = []
    seen: set[str] = set()
    for name in doc.get("members") or []:
        n = str(name).strip()
        if n and n not in seen:
            seen.add(n)
            members.append(n)
    code = normalize_room_code(doc.get("code") or "")
    return {
        "code": code,
        "roomName": (doc.get("roomName") or "").strip(),
        "createdAt": doc.get("createdAt") or utc_now(),
        "status": (doc.get("status") or "active").strip() or "active",
        "members": members,
        "memberCount": len(members),
        "message": (doc.get("message") or "").strip(),
        "lastPushAt": doc.get("lastPushAt"),
        "createdBy": (doc.get("createdBy") or "").strip(),
    }


def build_new_room(
    existing_codes: set[str],
    *,
    room_name: str = "",
    message: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    code = generate_room_code(existing_codes)
    return normalize_room(
        {
            "code": code,
            "roomName": room_name,
            "message": message,
            "createdBy": created_by,
            "createdAt": utc_now(),
            "status": "active",
            "members": [],
        }
    )


def room_add_member(room: dict, user_name: str) -> dict[str, Any]:
    doc = normalize_room(room)
    name = str(user_name or "").strip()
    if not name:
        return doc
    if name not in doc["members"]:
        doc["members"] = sorted(doc["members"] + [name])
        doc["memberCount"] = len(doc["members"])
    return doc


def room_public_view(room: dict) -> dict[str, Any]:
    doc = normalize_room(room)
    return {
        "code": doc["code"],
        "roomName": doc["roomName"],
        "createdAt": doc["createdAt"],
        "status": doc["status"],
        "memberCount": doc["memberCount"],
        "members": list(doc["members"]),
        "message": doc["message"],
        "lastPushAt": doc["lastPushAt"],
        "createdBy": doc["createdBy"],
    }


def rooms_overview(rooms: dict[str, dict]) -> list[dict[str, Any]]:
    rows = [room_public_view(doc) for doc in rooms.values()]
    rows.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    return rows
