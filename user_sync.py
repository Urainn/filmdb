"""
Multi-user sync: receive APP state, aggregate stats, align recommendation push.
"""

from __future__ import annotations

import time
from typing import Any

from recommend_engine import global_user_stats, summarize_profile


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_prefs(data: dict | None) -> dict[str, Any]:
    if not data:
        return {"like": [], "dislike": []}
    like = list(dict.fromkeys(data.get("like") or []))
    dislike = [x for x in dict.fromkeys(data.get("dislike") or []) if x not in like]
    return {
        "like": like,
        "dislike": dislike,
        "updatedAt": data.get("updatedAt"),
        "lastSyncAt": data.get("lastSyncAt"),
        "deviceId": (data.get("deviceId") or "").strip(),
    }


def merge_client_prefs(server_prefs: dict, client_body: dict) -> dict[str, Any]:
    """Merge APP upload (full lists and/or incremental events)."""
    merged = normalize_prefs(server_prefs)
    like = list(merged["like"])
    dislike = list(merged["dislike"])

    if client_body.get("like") is not None:
        like = list(dict.fromkeys(client_body.get("like") or []))
    if client_body.get("dislike") is not None:
        dislike = list(dict.fromkeys(client_body.get("dislike") or []))

    for ev in client_body.get("events") or []:
        if not isinstance(ev, dict):
            continue
        mid = (ev.get("movieId") or ev.get("movie_id") or "").strip()
        if not mid:
            continue
        action = (ev.get("type") or ev.get("action") or "").lower()
        if action == "like":
            if mid not in like:
                like.append(mid)
            if mid in dislike:
                dislike.remove(mid)
        elif action == "dislike":
            if mid not in dislike:
                dislike.append(mid)
            if mid in like:
                like.remove(mid)

    dislike = [x for x in dislike if x not in like]
    now = utc_now()
    return {
        "like": like,
        "dislike": dislike,
        "updatedAt": (client_body.get("clientUpdatedAt") or "").strip() or now,
        "lastSyncAt": now,
        "deviceId": (client_body.get("deviceId") or merged.get("deviceId") or "").strip(),
    }


def push_is_stale(prefs: dict, feed: dict | None) -> bool:
    """True when user prefs changed after last published push feed."""
    if not (prefs.get("like") or prefs.get("dislike")):
        return False
    if not feed or not feed.get("publishedAt"):
        return bool(prefs.get("like"))
    updated = prefs.get("updatedAt") or ""
    published = feed.get("publishedAt") or ""
    if updated and published:
        return updated > published
    return bool(prefs.get("like")) and not feed.get("cards")


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
    profile = summarize_profile(movies_by_id, prefs)
    stale = push_is_stale(prefs, feed)
    out: dict[str, Any] = {
        "ok": True,
        "userName": user_name,
        "serverTime": utc_now(),
        "prefs": normalize_prefs(prefs),
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
        users.append({
            "userName": user_name,
            "likeCount": len(prefs["like"]),
            "dislikeCount": len(prefs["dislike"]),
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
