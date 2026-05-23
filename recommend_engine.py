"""
Content-based recommendation from like/dislike movie tag profiles.
Used by server.py for /api/sheets_card/recommend and /api/user/analyze.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

DEFAULT_WEIGHTS = {
    "like_genre": 3,
    "like_mood": 2,
    "like_scene": 1,
    "dislike_genre": 5,
    "dislike_mood": 3,
    "dislike_scene": 2,
}


def _movie_tags(movie: dict) -> dict[str, list[str]]:
    scenes = list(movie.get("scenesMain") or []) + list(movie.get("scenesSub") or [])
    if not scenes and movie.get("scenes"):
        scenes = list(movie.get("scenes") or [])
    return {
        "genres": [str(x).strip() for x in (movie.get("genres") or []) if str(x).strip()],
        "moods": [str(x).strip() for x in (movie.get("moods") or []) if str(x).strip()],
        "scenes": [str(x).strip() for x in scenes if str(x).strip()],
    }


def build_tag_profile(
    movies_by_id: dict[str, dict],
    movie_ids: list[str],
    weight: float = 1.0,
) -> dict[str, Counter]:
    profile = {"genres": Counter(), "moods": Counter(), "scenes": Counter()}
    for mid in movie_ids:
        movie = movies_by_id.get(mid)
        if not movie:
            continue
        tags = _movie_tags(movie)
        for key in profile:
            for tag in tags[key]:
                profile[key][tag] += weight
    return profile


def _top_items(counter: Counter, n: int = 8) -> list[dict[str, Any]]:
    return [{"tag": tag, "weight": int(w)} for tag, w in counter.most_common(n)]


def summarize_profile(movies_by_id: dict[str, dict], user_prefs: dict) -> dict:
    like_ids = user_prefs.get("like") or []
    dislike_ids = user_prefs.get("dislike") or []
    like_prof = build_tag_profile(movies_by_id, like_ids, 1.0)
    dislike_prof = build_tag_profile(movies_by_id, dislike_ids, 1.0)
    liked_titles = [
        movies_by_id[mid].get("title", mid)
        for mid in like_ids
        if mid in movies_by_id
    ]
    disliked_titles = [
        movies_by_id[mid].get("title", mid)
        for mid in dislike_ids
        if mid in movies_by_id
    ]
    return {
        "likeCount": len(like_ids),
        "dislikeCount": len(dislike_ids),
        "likedTitles": liked_titles[:20],
        "dislikedTitles": disliked_titles[:20],
        "topGenres": _top_items(like_prof["genres"]),
        "topMoods": _top_items(like_prof["moods"]),
        "topScenes": _top_items(like_prof["scenes"]),
        "avoidGenres": _top_items(dislike_prof["genres"], 5),
    }


def score_movie(
    movie: dict,
    like_profile: dict[str, Counter],
    dislike_profile: dict[str, Counter],
    user_prefs: dict,
    weights: dict | None = None,
) -> tuple[float, list[str]]:
    weights = weights or DEFAULT_WEIGHTS
    mid = movie.get("id", "")
    if mid in (user_prefs.get("dislike") or []):
        return -1000.0, ["已標記不喜歡"]

    tags = _movie_tags(movie)
    score = 0.0
    reasons: list[str] = []
    seen_reasons: set[str] = set()

    def add_reason(prefix: str, tag: str, contrib: float) -> None:
        key = f"{prefix}:{tag}"
        if key in seen_reasons or contrib <= 0:
            return
        seen_reasons.add(key)
        reasons.append(f"{prefix}「{tag}」")

    for g in tags["genres"]:
        w = like_profile["genres"].get(g, 0) * weights["like_genre"]
        if w:
            score += w
            add_reason("類型", g, w)
    for m in tags["moods"]:
        w = like_profile["moods"].get(m, 0) * weights["like_mood"]
        if w:
            score += w
            add_reason("情緒", m, w)
    for s in tags["scenes"]:
        w = like_profile["scenes"].get(s, 0) * weights["like_scene"]
        if w:
            score += w
            add_reason("場景", s, w)

    for g in tags["genres"]:
        w = dislike_profile["genres"].get(g, 0) * weights["dislike_genre"]
        if w:
            score -= w
    for m in tags["moods"]:
        w = dislike_profile["moods"].get(m, 0) * weights["dislike_mood"]
        if w:
            score -= w
    for s in tags["scenes"]:
        w = dislike_profile["scenes"].get(s, 0) * weights["dislike_scene"]
        if w:
            score -= w

    return score, reasons[:6]


def ranked_movies(
    movies: list[dict],
    user_prefs: dict,
    limit: int = 20,
    weights: dict | None = None,
) -> tuple[list[tuple[float, dict, list[str]]], dict]:
    """Return scored candidates and metadata (cold start, profile summary)."""
    movies_by_id = {m["id"]: m for m in movies if m.get("id")}
    like_ids = user_prefs.get("like") or []
    dislike_ids = user_prefs.get("dislike") or []
    meta: dict[str, Any] = {
        "coldStart": not like_ids,
        "profile": summarize_profile(movies_by_id, user_prefs),
    }

    if not like_ids:
        pool = [m for m in movies if m.get("id") not in dislike_ids]
        return [(0.0, m, []) for m in pool[:limit]], meta

    like_prof = build_tag_profile(movies_by_id, like_ids, 1.0)
    dislike_prof = build_tag_profile(movies_by_id, dislike_ids, 1.0)
    scored: list[tuple[float, dict, list[str]]] = []

    for movie in movies:
        mid = movie.get("id")
        if not mid or mid in like_ids or mid in dislike_ids:
            continue
        s, reasons = score_movie(movie, like_prof, dislike_prof, user_prefs, weights)
        if s > 0:
            scored.append((s, movie, reasons))

    scored.sort(key=lambda x: -x[0])
    meta["candidateCount"] = len(scored)
    return scored[:limit], meta


def global_user_stats(all_users: dict[str, dict], movies: list[dict]) -> dict:
    movies_by_id = {m["id"]: m for m in movies if m.get("id")}
    total_likes = 0
    total_dislikes = 0
    genre_counter: Counter = Counter()

    for prefs in all_users.values():
        total_likes += len(prefs.get("like") or [])
        total_dislikes += len(prefs.get("dislike") or [])
        prof = build_tag_profile(movies_by_id, prefs.get("like") or [], 1.0)
        genre_counter.update(prof["genres"])

    return {
        "userCount": len(all_users),
        "totalLikes": total_likes,
        "totalDislikes": total_dislikes,
        "topGenresAcrossUsers": _top_items(genre_counter, 12),
        "users": [
            {
                "userName": name,
                "likeCount": len(p.get("like") or []),
                "dislikeCount": len(p.get("dislike") or []),
            }
            for name, p in sorted(all_users.items())
        ],
    }
