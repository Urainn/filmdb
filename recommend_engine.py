"""
Content-based recommendation from thermometer-weighted movie tag profiles.
Used by server.py for /api/sheets_card/recommend and /api/user/analyze.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

DEFAULT_WEIGHTS = {
    "like_genre": 3,
    "like_emotion": 2,
    "like_atmosphere": 2,
    "like_scene": 1,
    "dislike_genre": 5,
    "dislike_emotion": 3,
    "dislike_atmosphere": 3,
    "dislike_scene": 2,
}

# 溫度計：0=冷（不喜歡）… 50=中性 … 100=熱（喜歡）
TEMP_NEUTRAL = 50
TEMP_LIKE = 85
TEMP_DISLIKE = 15
TEMP_HOT = 67
TEMP_COLD = 33
TEMP_BLOCK = 20


def clamp_temperature(value) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return float(TEMP_NEUTRAL)


def warm_cold_weights(temperature: float) -> tuple[float, float]:
    """Return (warm_weight, cold_weight) each in 0..1 from thermometer reading."""
    t = clamp_temperature(temperature)
    warm = max(0.0, (t - TEMP_NEUTRAL) / 50.0)
    cold = max(0.0, (TEMP_NEUTRAL - t) / 50.0)
    return warm, cold


def temperature_map_from_prefs(user_prefs: dict) -> dict[str, float]:
    """Build movieId -> temperature; migrate legacy like/dislike lists."""
    temps: dict[str, float] = {}
    raw = user_prefs.get("temperatures") or {}
    if isinstance(raw, dict):
        for mid, val in raw.items():
            mid_s = str(mid).strip()
            if mid_s:
                temps[mid_s] = clamp_temperature(val)
    for mid in user_prefs.get("like") or []:
        mid_s = str(mid).strip()
        if mid_s and mid_s not in temps:
            temps[mid_s] = float(TEMP_LIKE)
    for mid in user_prefs.get("dislike") or []:
        mid_s = str(mid).strip()
        if mid_s and mid_s not in temps:
            temps[mid_s] = float(TEMP_DISLIKE)
    return temps


def sync_like_dislike_from_temperatures(temps: dict[str, float]) -> tuple[list[str], list[str]]:
    like = [mid for mid, t in temps.items() if t >= TEMP_HOT]
    dislike = [mid for mid, t in temps.items() if t <= TEMP_COLD and mid not in like]
    return like, dislike


def _tag_list(value) -> list[str]:
    return [str(x).strip() for x in (value or []) if str(x).strip()]


def movie_emotion_atmosphere_tags(movie: dict) -> tuple[list[str], list[str]]:
    """Read emotions / atmospheres; fall back to legacy moods field."""
    emotions = _tag_list(movie.get("emotions"))
    atmospheres = _tag_list(movie.get("atmospheres"))
    legacy = _tag_list(movie.get("moods"))
    if not emotions and not atmospheres and legacy:
        emotions = legacy
    return emotions, atmospheres


def _movie_tags(movie: dict) -> dict[str, list[str]]:
    scenes = list(movie.get("scenesMain") or []) + list(movie.get("scenesSub") or [])
    if not scenes and movie.get("scenes"):
        scenes = list(movie.get("scenes") or [])
    emotions, atmospheres = movie_emotion_atmosphere_tags(movie)
    return {
        "genres": _tag_list(movie.get("genres")),
        "emotions": emotions,
        "atmospheres": atmospheres,
        "scenes": _tag_list(scenes),
    }


def build_tag_profile(
    movies_by_id: dict[str, dict],
    movie_ids: list[str],
    weight: float = 1.0,
) -> dict[str, Counter]:
    profile = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    for mid in movie_ids:
        movie = movies_by_id.get(mid)
        if not movie:
            continue
        tags = _movie_tags(movie)
        for key in profile:
            for tag in tags[key]:
                profile[key][tag] += weight
    return profile


def build_temperature_profiles(
    movies_by_id: dict[str, dict],
    temp_map: dict[str, float],
) -> tuple[dict[str, Counter], dict[str, Counter]]:
    """Warm profile from hot ratings; cold profile from cold ratings."""
    warm = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    cold = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    for mid, temp in temp_map.items():
        movie = movies_by_id.get(mid)
        if not movie:
            continue
        warm_w, cold_w = warm_cold_weights(temp)
        tags = _movie_tags(movie)
        if warm_w > 0:
            for key in warm:
                for tag in tags[key]:
                    warm[key][tag] += warm_w
        if cold_w > 0:
            for key in cold:
                for tag in tags[key]:
                    cold[key][tag] += cold_w
    return warm, cold


def _top_items(counter: Counter, n: int = 8) -> list[dict[str, Any]]:
    return [{"tag": tag, "weight": round(float(w), 2)} for tag, w in counter.most_common(n)]


def summarize_profile(movies_by_id: dict[str, dict], user_prefs: dict) -> dict:
    temp_map = temperature_map_from_prefs(user_prefs)
    warm_prof, cold_prof = build_temperature_profiles(movies_by_id, temp_map)

    rated_entries = []
    for mid, temp in temp_map.items():
        if mid not in movies_by_id:
            continue
        rated_entries.append({
            "movieId": mid,
            "title": movies_by_id[mid].get("title", mid),
            "temperature": round(temp, 1),
        })
    rated_entries.sort(key=lambda x: -x["temperature"])

    hot = [e for e in rated_entries if e["temperature"] >= TEMP_HOT]
    cold = [e for e in rated_entries if e["temperature"] <= TEMP_COLD]
    avg_temp = (
        round(sum(e["temperature"] for e in rated_entries) / len(rated_entries), 1)
        if rated_entries
        else None
    )

    like_ids, dislike_ids = sync_like_dislike_from_temperatures(temp_map)

    return {
        "ratedCount": len(rated_entries),
        "avgTemperature": avg_temp,
        "hotCount": len(hot),
        "coldCount": len(cold),
        "neutralCount": len(rated_entries) - len(hot) - len(cold),
        "topRated": rated_entries[:12],
        "bottomRated": list(reversed(rated_entries))[:8],
        "likeCount": len(like_ids),
        "dislikeCount": len(dislike_ids),
        "likedTitles": [e["title"] for e in hot[:20]],
        "dislikedTitles": [e["title"] for e in cold[:20]],
        "topGenres": _top_items(warm_prof["genres"]),
        "topEmotions": _top_items(warm_prof["emotions"]),
        "topAtmospheres": _top_items(warm_prof["atmospheres"]),
        "topMoods": _top_items(warm_prof["emotions"] + warm_prof["atmospheres"]),
        "topScenes": _top_items(warm_prof["scenes"]),
        "avoidGenres": _top_items(cold_prof["genres"], 5),
        "temperatureScale": {
            "min": 0,
            "neutral": TEMP_NEUTRAL,
            "max": 100,
            "hotThreshold": TEMP_HOT,
            "coldThreshold": TEMP_COLD,
        },
    }


def score_movie(
    movie: dict,
    warm_profile: dict[str, Counter],
    cold_profile: dict[str, Counter],
    user_prefs: dict,
    weights: dict | None = None,
) -> tuple[float, list[str]]:
    weights = weights or DEFAULT_WEIGHTS
    mid = movie.get("id", "")
    temp_map = temperature_map_from_prefs(user_prefs)
    if mid in temp_map:
        t = temp_map[mid]
        return -1000.0, [f"已評分（{int(t)}°）"]

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
        w = warm_profile["genres"].get(g, 0) * weights["like_genre"]
        if w:
            score += w
            add_reason("類型", g, w)
    for e in tags["emotions"]:
        w = warm_profile["emotions"].get(e, 0) * weights["like_emotion"]
        if w:
            score += w
            add_reason("情緒", e, w)
    for a in tags["atmospheres"]:
        w = warm_profile["atmospheres"].get(a, 0) * weights["like_atmosphere"]
        if w:
            score += w
            add_reason("氛圍", a, w)
    for s in tags["scenes"]:
        w = warm_profile["scenes"].get(s, 0) * weights["like_scene"]
        if w:
            score += w
            add_reason("場景", s, w)

    for g in tags["genres"]:
        w = cold_profile["genres"].get(g, 0) * weights["dislike_genre"]
        if w:
            score -= w
    for e in tags["emotions"]:
        w = cold_profile["emotions"].get(e, 0) * weights["dislike_emotion"]
        if w:
            score -= w
    for a in tags["atmospheres"]:
        w = cold_profile["atmospheres"].get(a, 0) * weights["dislike_atmosphere"]
        if w:
            score -= w
    for s in tags["scenes"]:
        w = cold_profile["scenes"].get(s, 0) * weights["dislike_scene"]
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
    temp_map = temperature_map_from_prefs(user_prefs)
    warm_ids = [mid for mid, t in temp_map.items() if t > TEMP_NEUTRAL]
    meta: dict[str, Any] = {
        "coldStart": not warm_ids,
        "profile": summarize_profile(movies_by_id, user_prefs),
    }

    if not warm_ids:
        rated = set(temp_map.keys())
        pool = [m for m in movies if m.get("id") not in rated]
        return [(0.0, m, []) for m in pool[:limit]], meta

    warm_prof, cold_prof = build_temperature_profiles(movies_by_id, temp_map)
    scored: list[tuple[float, dict, list[str]]] = []

    for movie in movies:
        mid = movie.get("id")
        if not mid or mid in temp_map:
            continue
        s, reasons = score_movie(movie, warm_prof, cold_prof, user_prefs, weights)
        if s > 0:
            scored.append((s, movie, reasons))

    scored.sort(key=lambda x: -x[0])
    meta["candidateCount"] = len(scored)
    return scored[:limit], meta


def global_user_stats(all_users: dict[str, dict], movies: list[dict]) -> dict:
    movies_by_id = {m["id"]: m for m in movies if m.get("id")}
    total_likes = 0
    total_dislikes = 0
    total_rated = 0
    total_hot = 0
    total_cold = 0
    temp_sum = 0.0
    genre_counter: Counter = Counter()

    for prefs in all_users.values():
        temp_map = temperature_map_from_prefs(prefs)
        like_ids, dislike_ids = sync_like_dislike_from_temperatures(temp_map)
        total_likes += len(like_ids)
        total_dislikes += len(dislike_ids)
        total_rated += len(temp_map)
        temp_sum += sum(temp_map.values())
        total_hot += sum(1 for t in temp_map.values() if t >= TEMP_HOT)
        total_cold += sum(1 for t in temp_map.values() if t <= TEMP_COLD)
        warm_prof, _ = build_temperature_profiles(movies_by_id, temp_map)
        genre_counter.update(warm_prof["genres"])

    return {
        "userCount": len(all_users),
        "totalLikes": total_likes,
        "totalDislikes": total_dislikes,
        "totalRated": total_rated,
        "totalHot": total_hot,
        "totalCold": total_cold,
        "totalNeutral": max(0, total_rated - total_hot - total_cold),
        "avgTemperature": round(temp_sum / total_rated, 1) if total_rated else None,
        "temperatureDistribution": {
            "cold": total_cold,
            "neutral": max(0, total_rated - total_hot - total_cold),
            "hot": total_hot,
        },
        "topGenresAcrossUsers": _top_items(genre_counter, 12),
        "users": [
            {
                "userName": name,
                **(_user_stat_row(p)),
            }
            for name, p in sorted(all_users.items())
        ],
    }


def _user_stat_row(prefs: dict) -> dict[str, Any]:
    temp_map = temperature_map_from_prefs(prefs)
    like_ids, dislike_ids = sync_like_dislike_from_temperatures(temp_map)
    hot = sum(1 for t in temp_map.values() if t >= TEMP_HOT)
    cold = sum(1 for t in temp_map.values() if t <= TEMP_COLD)
    return {
        "likeCount": len(like_ids),
        "dislikeCount": len(dislike_ids),
        "ratedCount": len(temp_map),
        "hotCount": hot,
        "coldCount": cold,
        "neutralCount": max(0, len(temp_map) - hot - cold),
        "avgTemperature": (
            round(sum(temp_map.values()) / len(temp_map), 1) if temp_map else None
        ),
    }
