"""
Multi-user sync: receive APP state, aggregate stats, align recommendation push.
"""

from __future__ import annotations

import time
from typing import Any

from recommend_engine import (
    TEMP_DISLIKE,
    TEMP_LIKE,
    clamp_temperature,
    global_user_stats,
    summarize_profile,
    sync_like_dislike_from_temperatures,
    temperature_map_from_prefs,
)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_prefs(data: dict | None) -> dict[str, Any]:
    if not data:
        data = {}
    temps = temperature_map_from_prefs(data)
    like, dislike = sync_like_dislike_from_temperatures(temps)
    return {
        "like": like,
        "dislike": dislike,
        "temperatures": {k: round(v, 1) for k, v in temps.items()},
        "updatedAt": data.get("updatedAt"),
        "lastSyncAt": data.get("lastSyncAt"),
        "deviceId": (data.get("deviceId") or "").strip(),
    }


def merge_client_prefs(server_prefs: dict, client_body: dict) -> dict[str, Any]:
    """Merge APP upload (full lists, temperature map, and/or incremental events)."""
    merged = normalize_prefs(server_prefs)
    temps = dict(merged.get("temperatures") or {})

    if isinstance(client_body.get("temperatures"), dict):
        for mid, val in client_body["temperatures"].items():
            mid_s = str(mid).strip()
            if mid_s:
                temps[mid_s] = clamp_temperature(val)

    if client_body.get("like") is not None:
        for mid in client_body.get("like") or []:
            mid_s = str(mid).strip()
            if mid_s:
                temps[mid_s] = float(TEMP_LIKE)
    if client_body.get("dislike") is not None:
        for mid in client_body.get("dislike") or []:
            mid_s = str(mid).strip()
            if mid_s:
                temps[mid_s] = float(TEMP_DISLIKE)

    for ev in client_body.get("events") or []:
        if not isinstance(ev, dict):
            continue
        mid = (ev.get("movieId") or ev.get("movie_id") or "").strip()
        if not mid:
            continue
        action = (ev.get("type") or ev.get("action") or "").lower()
        if action in ("rate", "temperature", "temp"):
            temps[mid] = clamp_temperature(
                ev.get("temperature", ev.get("temp", TEMP_LIKE))
            )
        elif action == "like":
            temps[mid] = float(TEMP_LIKE)
        elif action == "dislike":
            temps[mid] = float(TEMP_DISLIKE)

    like, dislike = sync_like_dislike_from_temperatures(temps)
    now = utc_now()
    return {
        "like": like,
        "dislike": dislike,
        "temperatures": {k: round(v, 1) for k, v in temps.items()},
        "updatedAt": (client_body.get("clientUpdatedAt") or "").strip() or now,
        "lastSyncAt": now,
        "deviceId": (client_body.get("deviceId") or merged.get("deviceId") or "").strip(),
    }


def push_is_stale(prefs: dict, feed: dict | None) -> bool:
    """True when user prefs changed after last published push feed."""
    temps = temperature_map_from_prefs(prefs)
    if not temps:
        return False
    warm = any(t > 50 for t in temps.values())
    if not feed or not feed.get("publishedAt"):
        return warm
    updated = prefs.get("updatedAt") or ""
    published = feed.get("publishedAt") or ""
    if updated and published:
        return updated > published
    return warm and not feed.get("cards")


def build_sync_pull_payload(
    user_name: str,
    prefs: dict,
    feed: dict | None,
    movies: list[dict],
    *,
    include_live: bool = False,
    live_cards: list | None = None,
    live_meta: dict | None = None,
) -> dict[str, Any]:
    movies_by_id = {m["id"]: m for m in movies if m.get("id")}
    normalized = normalize_prefs(prefs)
    profile = summarize_profile(movies_by_id, normalized)
    stale = push_is_stale(normalized, feed)
    out: dict[str, Any] = {
        "ok": True,
        "userName": user_name,
        "serverTime": utc_now(),
        "prefs": normalized,
        "profile": profile,
        "pushFeed": feed if feed and feed.get("cards") else None,
        "pushStale": stale,
        "hasPublishedPush": bool(feed and feed.get("cards")),
    }
    if include_live and live_cards is not None:
        out["liveRecommendations"] = live_cards
        out["liveMeta"] = live_meta or {}
    return out


def multi_user_overview(
    all_prefs: dict[str, dict],
    all_feeds: dict[str, dict],
    movies: list[dict],
    recent_events: list[dict] | None = None,
) -> dict[str, Any]:
    stats = global_user_stats(all_prefs, movies)
    users = []
    stale_count = 0
    for user_name in sorted(all_prefs.keys()):
        prefs = normalize_prefs(all_prefs[user_name])
        feed = all_feeds.get(user_name) or {}
        stale = push_is_stale(prefs, feed)
        if stale:
            stale_count += 1
        temps = prefs.get("temperatures") or {}
        users.append({
            "userName": user_name,
            "likeCount": len(prefs["like"]),
            "dislikeCount": len(prefs["dislike"]),
            "ratedCount": len(temps),
            "avgTemperature": (
                round(sum(temps.values()) / len(temps), 1) if temps else None
            ),
            "updatedAt": prefs.get("updatedAt"),
            "lastSyncAt": prefs.get("lastSyncAt"),
            "deviceId": prefs.get("deviceId"),
            "publishedAt": feed.get("publishedAt"),
            "cardCount": feed.get("cardCount", len(feed.get("cards") or [])),
            "hasPush": bool(feed.get("cards")),
            "pushStale": stale,
        })
    return {
        "stats": stats,
        "users": users,
        "stalePushCount": stale_count,
        "recentEvents": recent_events or [],
        "userCount": len(users),
    }
