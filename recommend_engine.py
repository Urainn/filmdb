"""
Content-based recommendation from thermometer-weighted movie tag profiles.
Used by server.py for /api/sheets_card/recommend and /api/user/analyze.
"""

from __future__ import annotations

import math
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

# 多樣性：已選同類型每多一部，分數懲罰係數（略降，避免擠掉高精準命中）
DIVERSITY_GENRE_PENALTY = 0.18
# 正規化後可視為「有匹配」的最低分
SCORE_EPS = 1e-6
# 標籤模糊／跨欄位匹配
PARTIAL_MATCH_FACTOR = 0.82
ALIAS_MATCH_FACTOR = 0.94
CROSS_FAMILY_FACTOR = 0.90

# 常見同義／近似標籤（雙向會在 lookup 時展開）
TAG_ALIASES: dict[str, set[str]] = {
    "復古": {"懷舊"},
    "懷舊": {"復古"},
    "陰暗": {"陰鬱", "黑暗"},
    "陰鬱": {"陰暗", "黑暗"},
    "黑暗": {"陰暗", "陰鬱"},
    "詭譎": {"詭異"},
    "詭異": {"詭譎"},
    "溫暖": {"溫馨", "療癒"},
    "溫馨": {"溫暖", "療癒"},
    "療癒": {"溫馨", "溫暖"},
    "悲傷": {"傷心", "哀傷"},
    "恐怖": {"驚悚"},
    "驚悚": {"恐怖"},
    "孤獨": {"寂寞"},
    "寂寞": {"孤獨"},
    "刺激": {"緊張", "興奮"},
    "浪漫": {"愛情"},
}


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


def prefs_ready_for_push(user_prefs: dict) -> bool:
    """True when user has any warmer-than-neutral rating (aligned with ranked_movies)."""
    temps = temperature_map_from_prefs(user_prefs)
    return any(t > TEMP_NEUTRAL for t in temps.values())


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



def _norm_tag(tag: str) -> str:
    return str(tag or "").strip().lower().replace(" ", "").replace("　", "")


def _alias_norms(tag: str) -> set[str]:
    raw = str(tag or "").strip()
    out = set()
    for key in (raw, _norm_tag(raw)):
        for a in TAG_ALIASES.get(key, set()):
            n = _norm_tag(a)
            if n:
                out.add(n)
    return out


def _flatten_movie_tags(movie: dict) -> list[tuple[str, str]]:
    tags = _movie_tags(movie)
    flat: list[tuple[str, str]] = []
    for family, vals in tags.items():
        for tag in vals:
            if str(tag).strip():
                flat.append((family, str(tag).strip()))
    return flat


def _best_tag_match(
    needle: str,
    movie_tags: list[tuple[str, str]],
    preferred_family: str | None = None,
) -> tuple[float, str, str]:
    """Return (strength 0..1, matched_display_tag, matched_family)."""
    n = _norm_tag(needle)
    if not n or len(n) < 1:
        return 0.0, "", ""
    aliases = _alias_norms(needle)
    best_s = 0.0
    best_tag = ""
    best_fam = ""
    for fam, tag in movie_tags:
        h = _norm_tag(tag)
        if not h:
            continue
        strength = 0.0
        if h == n:
            strength = 1.0
        elif h in aliases or n in _alias_norms(tag):
            strength = ALIAS_MATCH_FACTOR
        elif len(n) >= 2 and len(h) >= 2 and (n in h or h in n):
            shorter, longer = (n, h) if len(n) <= len(h) else (h, n)
            ratio = len(shorter) / max(1, len(longer))
            # 情緒／氛圍：只接受高度重疊，避免「神秘」誤打「神秘酒吧」
            # 類型／場景：允許複合詞（動作 ∈ 科幻動作）
            # 只在「類型／場景 → 類型／場景」允許複合詞部分匹配
            # 避免情緒「神秘」誤打場景「神秘酒吧」
            if preferred_family in ("genres", "scenes") and fam in ("genres", "scenes"):
                if ratio >= 0.45:
                    strength = PARTIAL_MATCH_FACTOR * 0.95
            elif preferred_family in ("emotions", "atmospheres") and fam in ("emotions", "atmospheres"):
                if ratio >= 0.72:
                    strength = PARTIAL_MATCH_FACTOR
            elif ratio >= 0.85:
                strength = PARTIAL_MATCH_FACTOR * 0.9
        if strength <= 0:
            continue
        if preferred_family and fam != preferred_family:
            strength *= CROSS_FAMILY_FACTOR
        if strength > best_s:
            best_s = strength
            best_tag = tag
            best_fam = fam
    return best_s, best_tag, best_fam


def _primary_genre(movie: dict) -> str:
    genres = _movie_tags(movie)["genres"]
    return genres[0] if genres else "其他"


def _l1_normalize_profile(profile: dict[str, Counter]) -> dict[str, Counter]:
    """Normalize each tag family so weights sum to 1 — prevents rating-count inflation."""
    out: dict[str, Counter] = {}
    for key, counter in profile.items():
        total = float(sum(counter.values()))
        if total <= 0:
            out[key] = Counter()
        else:
            out[key] = Counter({tag: float(w) / total for tag, w in counter.items()})
    return out


def _build_catalog_idf(movies: list[dict]) -> dict[str, dict[str, float]]:
    """Rare tags weigh more; ubiquitous tags (e.g. 劇情) are dampened."""
    n = max(1, len(movies))
    df: dict[str, Counter] = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    for movie in movies:
        tags = _movie_tags(movie)
        for key in df:
            for tag in set(tags[key]):
                df[key][tag] += 1
    idf: dict[str, dict[str, float]] = {}
    for key, counter in df.items():
        idf[key] = {
            tag: math.log((n + 1.0) / (cnt + 1.0)) + 1.0
            for tag, cnt in counter.items()
        }
    return idf


def _idf(idf: dict[str, dict[str, float]], key: str, tag: str) -> float:
    return float(idf.get(key, {}).get(tag, 1.0))


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
    *,
    normalize: bool = True,
) -> tuple[dict[str, Counter], dict[str, Counter]]:
    """Warm profile from hot ratings; cold profile from cold ratings.

    Ratings at or below TEMP_BLOCK amplify cold tags (harder avoidance).
    """
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
            # 極冷片：排斥訊號加強，對應 TEMP_BLOCK
            boost = 1.65 if temp <= TEMP_BLOCK else 1.0
            for key in cold:
                for tag in tags[key]:
                    cold[key][tag] += cold_w * boost
    if normalize:
        return _l1_normalize_profile(warm), _l1_normalize_profile(cold)
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
            "blockThreshold": TEMP_BLOCK,
        },
    }


def score_movie(
    movie: dict,
    warm_profile: dict[str, Counter],
    cold_profile: dict[str, Counter],
    user_prefs: dict,
    weights: dict | None = None,
    idf: dict[str, dict[str, float]] | None = None,
) -> tuple[float, list[str]]:
    """Score candidate vs warm/cold tag profiles.

    Precision-oriented:
    - match tags across families (情緒選到「神秘」也能打中氛圍欄)
    - exact > alias > partial
    - boost preference coverage; dampen tag-rich movies' accidental hits
    """
    weights = weights or DEFAULT_WEIGHTS
    idf = idf or {}
    mid = movie.get("id", "")
    temp_map = temperature_map_from_prefs(user_prefs)
    if mid in temp_map:
        t = temp_map[mid]
        return -1000.0, [f"已評分（{int(t)}°）"]

    movie_tags = _flatten_movie_tags(movie)
    if not movie_tags:
        return 0.0, []

    like_reasons: list[str] = []
    avoid_reasons: list[str] = []
    seen_like: set[str] = set()
    seen_avoid: set[str] = set()

    def add_like(prefix: str, tag: str, contrib: float) -> None:
        key = f"{prefix}:{tag}"
        if key in seen_like or contrib <= SCORE_EPS:
            return
        seen_like.add(key)
        like_reasons.append(f"{prefix}「{tag}」")

    def add_avoid(tag: str, contrib: float) -> None:
        if tag in seen_avoid or contrib <= SCORE_EPS:
            return
        seen_avoid.add(tag)
        avoid_reasons.append(f"避開「{tag}」")

    family_meta = (
        ("genres", "類型", "like_genre", "dislike_genre"),
        ("emotions", "情緒", "like_emotion", "dislike_emotion"),
        ("atmospheres", "氛圍", "like_atmosphere", "dislike_atmosphere"),
        ("scenes", "場景", "like_scene", "dislike_scene"),
    )

    raw_pos = 0.0
    raw_neg = 0.0
    total_pref_w = 0.0
    matched_pref_w = 0.0
    matched_count = 0

    for family, prefix, like_key, _dislike_key in family_meta:
        for tag, pref_w in (warm_profile.get(family) or Counter()).items():
            pw = float(pref_w or 0.0)
            if pw <= 0:
                continue
            total_pref_w += pw
            strength, hit_tag, hit_fam = _best_tag_match(tag, movie_tags, preferred_family=family)
            if strength <= 0:
                continue
            idf_fam = hit_fam or family
            contrib = pw * weights[like_key] * _idf(idf, idf_fam, hit_tag or tag) * strength
            if contrib <= SCORE_EPS:
                continue
            raw_pos += contrib
            matched_pref_w += pw * strength
            matched_count += 1
            reason_prefix = {
                "genres": "類型",
                "emotions": "情緒",
                "atmospheres": "氛圍",
                "scenes": "場景",
            }.get(hit_fam or family, prefix)
            add_like(reason_prefix, hit_tag or tag, contrib)

    for family, _prefix, _like_key, dislike_key in family_meta:
        for tag, pref_w in (cold_profile.get(family) or Counter()).items():
            pw = float(pref_w or 0.0)
            if pw <= 0:
                continue
            strength, hit_tag, hit_fam = _best_tag_match(tag, movie_tags, preferred_family=family)
            if strength <= 0:
                continue
            idf_fam = hit_fam or family
            contrib = pw * weights[dislike_key] * _idf(idf, idf_fam, hit_tag or tag) * strength
            if contrib <= SCORE_EPS:
                continue
            raw_neg += contrib
            if family == "genres" or hit_fam == "genres":
                add_avoid(hit_tag or tag, contrib)

    if raw_pos <= SCORE_EPS and raw_neg <= SCORE_EPS:
        return 0.0, []

    coverage = (matched_pref_w / total_pref_w) if total_pref_w > 0 else 0.0
    unique_movie_tags = len({_norm_tag(t) for _f, t in movie_tags if _norm_tag(t)})
    # 標籤很多的片容易「碰巧命中」→ 略為壓低
    richness_dampen = 1.0 / math.sqrt(max(1.0, unique_movie_tags / 5.0))
    # 覆蓋率高（你選的感覺大多有打中）→ 加權
    coverage_boost = 0.42 + 0.58 * coverage
    evidence = 1.0 - math.exp(-matched_count / 2.2) if matched_count else 0.0
    evidence_boost = 0.85 + 0.15 * evidence

    score = (raw_pos * coverage_boost * richness_dampen * evidence_boost) - raw_neg
    reasons = like_reasons[:4] + avoid_reasons[:2]
    return score, reasons



def _tag_richness(movie: dict) -> int:
    tags = _movie_tags(movie)
    return (
        len(tags["genres"])
        + len(tags["emotions"])
        + len(tags["atmospheres"])
        + min(4, len(tags["scenes"]))
    )


def _cold_start_ranked(
    movies: list[dict],
    rated: set[str],
    limit: int,
) -> list[tuple[float, dict, list[str]]]:
    """Diverse exploration: well-tagged films, round-robin by primary genre."""
    pool = [m for m in movies if m.get("id") and m.get("id") not in rated]
    pool.sort(key=_tag_richness, reverse=True)
    by_genre: dict[str, list[dict]] = {}
    for movie in pool:
        by_genre.setdefault(_primary_genre(movie), []).append(movie)

    out: list[tuple[float, dict, list[str]]] = []
    while len(out) < limit and by_genre:
        emptied: list[str] = []
        for genre in list(by_genre.keys()):
            if len(out) >= limit:
                break
            bucket = by_genre[genre]
            if not bucket:
                emptied.append(genre)
                continue
            movie = bucket.pop(0)
            out.append((0.0, movie, ["探索推薦"]))
            if not bucket:
                emptied.append(genre)
        for genre in emptied:
            by_genre.pop(genre, None)
    return out


def _diversify_ranked(
    scored: list[tuple[float, dict, list[str]]],
    limit: int,
) -> list[tuple[float, dict, list[str]]]:
    """Greedy re-rank: keep high scores but avoid flooding one genre."""
    if len(scored) <= limit:
        return scored

    remaining = list(scored)
    picked: list[tuple[float, dict, list[str]]] = []
    genre_counts: Counter = Counter()

    while remaining and len(picked) < limit:
        best_i = 0
        best_adj = float("-inf")
        for i, (s, movie, _reasons) in enumerate(remaining):
            genres = _movie_tags(movie)["genres"] or ["其他"]
            overlap = sum(genre_counts[g] for g in genres)
            adj = s - DIVERSITY_GENRE_PENALTY * overlap * (abs(s) * 0.2 + 1.0)
            if adj > best_adj:
                best_adj = adj
                best_i = i
        item = remaining.pop(best_i)
        picked.append(item)
        for g in (_movie_tags(item[1])["genres"] or ["其他"]):
            genre_counts[g] += 1
    return picked


def warm_profile_from_tag_selections(tag_map: dict | None) -> dict[str, Counter]:
    """Build warm tag profile from Moodluma room member tags.

    tag_map shape: { "療癒": {"tag":"療癒","weight":0.8,"kind":"mood"}, ... }
    """
    profile = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    kind_to_family = {
        "genre": "genres",
        "mood": "emotions",
        "emotion": "emotions",
        "atmosphere": "atmospheres",
        "scene": "scenes",
    }
    if not isinstance(tag_map, dict):
        return profile
    for key, meta in tag_map.items():
        tag = str(key).strip()
        weight = 0.6
        kind = "mood"
        if isinstance(meta, dict):
            tag = str(meta.get("tag") or tag).strip()
            try:
                weight = float(meta.get("weight") or 0.6)
            except (TypeError, ValueError):
                weight = 0.6
            kind = str(meta.get("kind") or "mood").strip().lower()
        elif isinstance(meta, (int, float)):
            weight = float(meta)
        if not tag:
            continue
        family = kind_to_family.get(kind, "emotions")
        profile[family][tag] += max(0.05, min(1.5, weight))
    return _l1_normalize_profile(profile)


def feedbacks_to_temperatures(feedbacks: dict | None) -> dict[str, float]:
    """Convert Moodluma local feedbacks map → FilmDB temperature map."""
    temps: dict[str, float] = {}
    if not isinstance(feedbacks, dict):
        return temps
    for mid, fb in feedbacks.items():
        mid_s = str(mid).strip()
        if not mid_s:
            continue
        if isinstance(fb, dict):
            if "temperature" in fb or "temp" in fb:
                temps[mid_s] = clamp_temperature(fb.get("temperature", fb.get("temp")))
            elif fb.get("rating") == "like":
                temps[mid_s] = float(TEMP_LIKE)
            elif fb.get("rating") == "dislike":
                temps[mid_s] = float(TEMP_DISLIKE)
        elif isinstance(fb, (int, float)):
            temps[mid_s] = clamp_temperature(fb)
    return temps


def ranked_movies_from_warm_profile(
    movies: list[dict],
    warm_prof: dict[str, Counter],
    *,
    exclude_ids: set[str] | None = None,
    limit: int = 20,
    weights: dict | None = None,
    label: str = "標籤偏好",
) -> tuple[list[tuple[float, dict, list[str]]], dict]:
    """Rank by an explicit warm tag profile (e.g. room member selections)."""
    exclude_ids = exclude_ids or set()
    empty_cold = {
        "genres": Counter(),
        "emotions": Counter(),
        "atmospheres": Counter(),
        "scenes": Counter(),
    }
    has_signal = any(warm_prof.get(k) for k in ("genres", "emotions", "atmospheres", "scenes"))
    meta: dict[str, Any] = {
        "coldStart": not has_signal,
        "source": "tags",
        "profile": {
            "topGenres": _top_items(warm_prof.get("genres") or Counter(), 8),
            "topEmotions": _top_items(warm_prof.get("emotions") or Counter(), 8),
            "topAtmospheres": _top_items(warm_prof.get("atmospheres") or Counter(), 8),
            "topScenes": _top_items(warm_prof.get("scenes") or Counter(), 8),
        },
    }
    if not has_signal:
        ranked = _cold_start_ranked(movies, exclude_ids, limit)
        meta["candidateCount"] = len(ranked)
        meta["diversified"] = True
        return ranked, meta

    idf = _build_catalog_idf(movies)
    scored: list[tuple[float, dict, list[str]]] = []
    empty_prefs = {"temperatures": {}, "like": [], "dislike": []}
    for movie in movies:
        mid = movie.get("id")
        if not mid or mid in exclude_ids:
            continue
        s, reasons = score_movie(
            movie, warm_prof, empty_cold, empty_prefs, weights, idf=idf
        )
        if s > SCORE_EPS:
            if not reasons:
                reasons = [label]
            scored.append((s, movie, reasons))
    scored.sort(key=lambda x: -x[0])
    meta["candidateCount"] = len(scored)
    diversified = _diversify_ranked(scored, limit)
    meta["diversified"] = True
    return diversified, meta


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
        "source": "prefs",
    }

    if not warm_ids:
        ranked = _cold_start_ranked(movies, set(temp_map.keys()), limit)
        meta["candidateCount"] = len(ranked)
        meta["diversified"] = True
        return ranked, meta

    warm_prof, cold_prof = build_temperature_profiles(movies_by_id, temp_map)
    idf = _build_catalog_idf(movies)
    scored: list[tuple[float, dict, list[str]]] = []

    for movie in movies:
        mid = movie.get("id")
        if not mid or mid in temp_map:
            continue
        s, reasons = score_movie(
            movie, warm_prof, cold_prof, user_prefs, weights, idf=idf
        )
        if s > SCORE_EPS:
            scored.append((s, movie, reasons))

    scored.sort(key=lambda x: -x[0])
    meta["candidateCount"] = len(scored)
    diversified = _diversify_ranked(scored, limit)
    meta["diversified"] = True
    return diversified, meta


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
