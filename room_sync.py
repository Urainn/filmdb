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
MAX_ROOM_MEMBERS = 16


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
    raw_members = doc.get("members")
    # Sheets / 舊資料可能誤存成單一字串，避免被當成字元迭代
    if isinstance(raw_members, str):
        raw_members = [raw_members] if raw_members.strip() else []
    elif not isinstance(raw_members, (list, tuple)):
        raw_members = []
    for name in raw_members:
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


def _unique_members(*member_lists) -> list[str]:
    """Union member names from one or more lists; preserves insertion then sorts."""
    seen: set[str] = set()
    out: list[str] = []
    for lst in member_lists:
        if isinstance(lst, str):
            lst = [lst] if lst.strip() else []
        elif not isinstance(lst, (list, tuple)):
            continue
        for name in lst:
            n = str(name).strip()
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return sorted(out)


def room_merge_snapshots(*rooms: dict | None) -> dict[str, Any]:
    """
    Merge multiple room snapshots (cache + sheet) without dropping members.
    Uses the first non-empty metadata fields; members are a sorted union.
    """
    base: dict[str, Any] | None = None
    member_lists: list = []
    for raw in rooms:
        if not raw:
            continue
        doc = normalize_room(raw)
        member_lists.append(doc["members"])
        if base is None:
            base = doc
            continue
        # Prefer non-empty / newer-looking metadata from later snapshots
        for key in ("roomName", "message", "createdBy", "status", "createdAt", "lastPushAt"):
            val = doc.get(key)
            if val not in (None, ""):
                base[key] = val
        if doc.get("code"):
            base["code"] = doc["code"]
    if base is None:
        return normalize_room(None)
    members = _unique_members(*member_lists)
    base["members"] = members
    base["memberCount"] = len(members)
    return base


def room_add_member(room: dict, user_name: str) -> dict[str, Any]:
    """Append user to members (idempotent). Does not overwrite existing members."""
    doc = normalize_room(room)
    name = str(user_name or "").strip()
    if not name:
        return doc
    if name not in doc["members"]:
        if len(doc["members"]) >= MAX_ROOM_MEMBERS:
            raise ValueError(f"房間人數已滿（最多 {MAX_ROOM_MEMBERS} 人）")
        doc["members"] = _unique_members(doc["members"], [name])
        doc["memberCount"] = len(doc["members"])
    return doc


def room_remove_member(room: dict, user_name: str) -> dict[str, Any]:
    """Remove user from members; other members are preserved."""
    doc = normalize_room(room)
    name = str(user_name or "").strip()
    if not name:
        return doc
    if name in doc["members"]:
        doc["members"] = [m for m in doc["members"] if m != name]
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
        "maxMembers": MAX_ROOM_MEMBERS,
    }


def rooms_overview(rooms: dict[str, dict]) -> list[dict[str, Any]]:
    rows = [room_public_view(doc) for doc in rooms.values()]
    rows.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    return rows
