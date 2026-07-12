#!/usr/bin/env python3
"""
FilmDB cloud server - Google Sheets version.
"""


from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import os
import time
import threading
import base64
import sys
import traceback

from recommend_engine import (
    DEFAULT_WEIGHTS,
    TEMP_DISLIKE,
    TEMP_LIKE,
    clamp_temperature,
    global_user_stats,
    movie_emotion_atmosphere_tags,
    ranked_movies,
    summarize_profile,
)
from search_synonyms import (
    DEFAULT_SEARCH_SYNONYM_GROUPS,
    build_synonym_map,
    expand_search_terms,
    normalize_synonym_groups,
    text_matches_expanded_query,
)
from user_sync import (
    build_sync_pull_payload,
    merge_client_prefs,
    multi_user_overview,
    normalize_prefs,
    push_is_stale,
    utc_now,
)
from room_sync import (
    build_new_room,
    normalize_room,
    normalize_room_code,
    room_add_member,
    room_public_view,
    rooms_overview,
)




GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDs2IknIRxX_H8DRGR9er_oiBsbQWoYzDw")
SHEETS_CREDS = os.environ.get("SHEETS_CREDS") or """
{
  "type": "service_account",
  "project_id": "premium-weft-495011-d4",
  "private_key_id": "75cca91069cd9cd2c34c69419a6b0a10334f8582",
  "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQDoy5CytRRbakG3\\n/wZKNH2T+Dg6aaABslyae3SSbi5YYshHgYOro1I3Y2MMqRiT+SIIzjH+uAFGhEXr\\nc9mQiaSg9OhfXELbR21tZlKOzd7dTNgGW/qWZvnaRED4EaZxbh+wQprkxFH53dXE\\nXUSLAk+hNPzofHDO0cCOPEolMtqIpwDygsqqwyl80N7xB8mkyXlC4yY9hcyUObEg\\nHNY3HDqm90hLOGCh0TED8UJkL1oAb3C28ivDX1V43njzN7iJ/9LU1kiqYhV9jrgK\\nqVME3snV1cNKgBEMxFFwQqQVHAzLlWe21oZt2Ga1Pie+HxvLSghUw97s1fQjn2y5\\nsoD88WPnAgMBAAECggEAIkpV8pTsvjhtHMKydPy9YK3n7ma/nHBe5px3w9f5+Kf4\\nU1wW/pHMmv8HSIah6a4BXuWshJYrDe2O9Qs4CWvU9aaNkfpfmLgxPLOdRo65nMRk\\nb69dvojFleqG3WOQLlYn0clF0pu+bX1JLycD4SwCeb753+7wmO5ZnDnyO/99JDKZ\\nbCympXDnCvo8N1km9v0t0QvJO5TEgbTknWBEgrYI6MbB3aTwsDw7LY3DxCLUkNmU\\nrrbwpSIEC0iIxdBEr93SoxR9iv64JtCToLf+zEECeU2ifvEHcQPAcA8Bjv3Pf6cJ\\nflWK4aZJaAbDiSWttG/7VwROp5YmwUI0oQJ6/1MfnQKBgQD1bLecz2NzxEztk0a+\\nPH+bgBKZ8OWmREg/7TtDth9Aql399i38sckXslF2/KzH3DINpd331A8vJDrE/5vj\\niNgn5VxKmg6i2GrlDFySlqlZg/UCbwUQ7f6uld0zHnf0drm2kPdqeUWIX+zc6/6I\\n0KJqg3vztpM5hgsZRo+d3jTgGwKBgQDy04gk54SqEaNSoqCJkTQPRAnVrjpyip5q\\nkz2YhjKsjnzstbvK+NnujLJPO3kO+XKcCOGfMEDo8drElT19ujCvHWCY69DWpZkU\\nNW3mW/E9SgnqfW48F2vRZhYAN+8XN/ppBR6n7iAKTniePQGC3abCsSmkmFHBkN1Z\\nQ9LdxLcAJQKBgQCU5eWsJIKxDMqjZLQJ3MiKvjQK44Vgz5KJ/lLzbL4fTH2EA+S4\\np+BaGRyltPzasLRJZXV601R3BGMHfBDHBhImelf5BuiUUfrghhRv9yo9nfp7BIIt\\nWEcpAtFWH0klrxZTNjZ1iafu6kvZaPBfbzzqpGUCYqWFw9Zd+lpNrC+mOwKBgQCh\\nOxkLv/nTXpC+HqNPlG0nsbqB+gRu52GWTBu6+WgOMTH7jhOaCq/Rd/QxLcEM005p\\nEnCU3VpMEcJ7gshogccvjucDwphQ3XWN+If3S5cbZdy9qPkXx0lcqVb0YC9NkGqh\\nbrfTMwZtMXtfPgyR0xCV90I6OrUWPFTsn18UxzfnTQKBgQDOOF0jbTJ9DMOnIGMm\\nKSVc8pGLfxq8uOkLoNEyihnKif77kLg9x8UJhNFAoiUhmZvbF44zfIfXy9RtEjuo\\n1etaLv6Yrn/LYyPIIFaT0RLYq4Ykmnj/dF197FJcaLPnubk0oY0b8SwFu6XvBgZs\\nRszwbF2m/OKO1AV4l+qybY72xw==\\n-----END PRIVATE KEY-----\\n",
  "client_email": "filmdbreader@premium-weft-495011-d4.iam.gserviceaccount.com",
  "client_id": "104010324652851159714",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/filmdbreader%40premium-weft-495011-d4.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
"""
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1sRXiN_W8oshYIZTaDza3A-B1MPgrpTmedoQx8VS9Dsw")
SHEET_NAME = os.environ.get("SHEET_NAME", "films")
CONFIG_SHEET = "config"
USER_PREFS_SHEET = os.environ.get("USER_PREFS_SHEET", "user_prefs")
PUSH_FEED_SHEET = os.environ.get("PUSH_FEED_SHEET", "push_feed")
USER_EVENTS_SHEET = os.environ.get("USER_EVENTS_SHEET", "user_events")
ROOMS_SHEET = os.environ.get("ROOMS_SHEET", "multi_rooms")
PORT = int(os.environ.get("PORT", 8765))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyCMkz2uk_IcRVIoNZNBZ7wQJ6RDdL_KBjI")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "f8abc776cee1400e1fadf2874e1d8c2c")


MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MODEL_FALLBACKS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


PROMPT = """仔細看完這個電影預告片，然後只輸出一個 JSON 物件，絕對不要加任何說明文字或 markdown。
這是一個給展覽觀眾搜尋電影用的資料庫，請產生「好搜尋、可策展、可聯想」的標籤。
不要只給很少的類型詞；請補足題材、情緒、敘事母題、視覺質感、社會議題、角色關係與觀眾可能會搜尋的關鍵詞。

請嚴格按照以下格式：
{
  "title": "電影中文片名",
  "year": "上映年份（四位數字，例如 2024）",
  "desc": "25字內的劇情簡介",
  "scenes_main": ["3到6個主要場景，只填具體地點名稱，如：城市街道、住宅、商場、森林、命案現場、監獄、太空、荒地、密閉空間"],
  "scenes_sub": ["3到6個次要場景，只填具體地點名稱，如：室內、教室、醫院、車廂、辦公室、酒吧、走廊、地下室、心理諮商所"],
  "genres": ["6到10個類型與題材關鍵詞，如：喜劇、恐怖、驚悚、科幻、犯罪、懸疑、青春、荒唐、超自然、女性職場"],
  "emotions": ["4到8個情緒標籤，描述觀眾觀影時的情緒反應，如：緊張、感動、爆笑、憤怒、憂鬱、熱血、恐懼、溫馨、荒謬"],
  "atmospheres": ["4到8個氛圍標籤，描述畫面與聽覺的整體質感，如：黑暗、夢幻、復古、壓抑、華麗、詭譎、寫實、浪漫、霓虹"],
  "cast": ["演員1名稱", "演員2名稱", "演員3名稱"]  // 列表中可以包含多位演員
}
重要規則：
1. scenes_main 和 scenes_sub 只能填「觀眾看得懂的具體地點或空間」，不要填抽象世界觀
2. 禁止場景出現：未知世界、冒險市、奇幻世界、魔法世界、異世界、夢境世界、命運舞台、故事世界
3. genres 不只填片種，也要補題材與可搜尋關鍵詞，但不要亂編不存在的政治或社會議題
4. emotions 只填情緒反應詞；atmospheres 只填氛圍與視聽質感詞，兩者不可混用
5. 每個陣列都要去重，不要重複意思太接近的詞
6. 就算不確定也要根據影片畫面與片名合理推測，但要避免太空泛的詞
7. 所有輸出都必須使用台灣繁體中文，不可以出現簡體中文"""


_token_cache = {"token": None, "expires": 0}
_token_lock = threading.Lock()
_gemini_keys = []
_key_lock = threading.Lock()
_key_index = 0
_sheet_id_cache = None
_search_synonyms_cache = None
_search_synonyms_lock = threading.Lock()

# 使用者喜好：啟動時從 Google Sheets 載入，like/dislike 時寫回
user_behavior = {}
_user_lock = threading.Lock()
_user_prefs_sheet_id_cache = None
_push_feed_cache = {}
_push_feed_lock = threading.Lock()
_rooms_cache = {}
_rooms_lock = threading.Lock()


def get_access_token():
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
            return _token_cache["token"]
        if not SHEETS_CREDS:
            raise Exception("未設定 SHEETS_CREDS")

        creds = json.loads(SHEETS_CREDS)
        now = int(time.time())
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({
                "iss": creds["client_email"],
                "scope": "https://www.googleapis.com/auth/spreadsheets",
                "aud": "https://oauth2.googleapis.com/token",
                "exp": now + 3600,
                "iat": now,
            }).encode()
        ).rstrip(b"=").decode()

        try:
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend
            private_key = serialization.load_pem_private_key(
                creds["private_key"].encode(),
                password=None,
                backend=default_backend(),
            )
            signing_input = f"{header}.{payload}".encode()
            signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
            sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        except ImportError:
            raise Exception("缺少 cryptography 套件")

        jwt_token = f"{header}.{payload}.{sig_b64}"
        token_body = (
            "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
            "&assertion=" + urllib.parse.quote(jwt_token)
        ).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=token_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())
        _token_cache["token"] = token_data["access_token"]
        _token_cache["expires"] = now + token_data.get("expires_in", 3600)
        return _token_cache["token"]




SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"




def sheets_request(method, path, body=None):
    url = f"{SHEETS_BASE}/{SPREADSHEET_ID}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  Sheets HTTP {e.code}: {err[:300]}")
        raise Exception(f"Sheets API 錯誤 {e.code}: {err[:200]}")




def ensure_sheet():
    try:
        info = sheets_request("GET", "")
        names = [s["properties"]["title"] for s in info.get("sheets", [])]
        for name in [SHEET_NAME, CONFIG_SHEET, USER_PREFS_SHEET, PUSH_FEED_SHEET, USER_EVENTS_SHEET, ROOMS_SHEET]:
            if name not in names:
                sheets_request("POST", ":batchUpdate", {
                    "requests": [{"addSheet": {"properties": {"title": name}}}]
                })
    except Exception as e:
        print(f"  ensure_sheet 錯誤: {e}")




def ensure_config_sheet():
    try:
        info = sheets_request("GET", "")
        names = [s["properties"]["title"] for s in info.get("sheets", [])]
        if CONFIG_SHEET not in names:
            sheets_request("POST", ":batchUpdate", {
                "requests": [{"addSheet": {"properties": {"title": CONFIG_SHEET}}}]
            })
    except Exception as e:
        print(f"  ensure_config_sheet 錯誤: {e}")


def read_config_rows():
    try:
        ensure_config_sheet()
        encoded = urllib.parse.quote(f"{CONFIG_SHEET}!A:B")
        return sheets_request("GET", f"/values/{encoded}").get("values", [])
    except Exception as e:
        print(f"  read_config_rows 錯誤: {e}")
        return []


def get_config_json(key: str, default):
    for row in read_config_rows():
        if len(row) >= 2 and row[0] == key and row[1].strip():
            try:
                return json.loads(row[1])
            except Exception:
                return default
    return default


def set_config_json(key: str, value) -> bool:
    try:
        ensure_config_sheet()
        rows = read_config_rows()
        other = [r for r in rows if not (r and r[0] == key)]
        other.append([key, json.dumps(value, ensure_ascii=False)])
        clear_range = urllib.parse.quote(f"{CONFIG_SHEET}!A:Z")
        sheets_request("POST", f"/values/{clear_range}:clear", {})
        start = urllib.parse.quote(f"{CONFIG_SHEET}!A1")
        sheets_request("PUT", f"/values/{start}?valueInputOption=RAW", {"values": other})
        return True
    except Exception as e:
        print(f"  set_config_json({key}) 錯誤: {e}")
        return False


def get_search_synonym_groups():
    global _search_synonyms_cache
    with _search_synonyms_lock:
        if _search_synonyms_cache is not None:
            return _search_synonyms_cache
        raw = get_config_json("search_synonyms", None)
        groups = normalize_synonym_groups(
            raw if raw is not None else DEFAULT_SEARCH_SYNONYM_GROUPS
        )
        _search_synonyms_cache = groups
        return groups


def save_search_synonym_groups(groups) -> bool:
    global _search_synonyms_cache
    normalized = normalize_synonym_groups(groups)
    ok = set_config_json("search_synonyms", normalized)
    if ok:
        with _search_synonyms_lock:
            _search_synonyms_cache = normalized
    return ok


def get_gemini_keys():
    global _gemini_keys
    with _key_lock:
        try:
            encoded = urllib.parse.quote(f"{CONFIG_SHEET}!A:B")
            rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
            keys = [
                row[1].strip()
                for row in rows
                if len(row) >= 2 and row[0] == "gemini_key" and row[1].strip()
            ]
            if keys:
                _gemini_keys = keys
                return keys
        except Exception as e:
            print(f"  讀取 config 失敗: {e}")
        return [GEMINI_API_KEY] if GEMINI_API_KEY else []




def save_gemini_keys(keys):
    global _gemini_keys
    try:
        ensure_config_sheet()
        encoded_all = urllib.parse.quote(f"{CONFIG_SHEET}!A:B")
        all_rows = sheets_request("GET", f"/values/{encoded_all}").get("values", [])
        other_rows = [r for r in all_rows if not (r and r[0] == "gemini_key")]
        new_rows = other_rows + [["gemini_key", k] for k in keys if k.strip()]
        clear_range = urllib.parse.quote(f"{CONFIG_SHEET}!A:Z")
        sheets_request("POST", f"/values/{clear_range}:clear", {})
        if new_rows:
            start = urllib.parse.quote(f"{CONFIG_SHEET}!A1")
            sheets_request("PUT", f"/values/{start}?valueInputOption=RAW", {"values": new_rows})
        with _key_lock:
            _gemini_keys = [k for k in keys if k.strip()]
        return True
    except Exception as e:
        print(f"  儲存 Gemini Keys 失敗: {e}")
        return False




def get_next_key(failed_key=None):
    global _key_index
    keys = get_gemini_keys()
    if not keys:
        return ""
    with _key_lock:
        if failed_key and failed_key in keys:
            _key_index = (keys.index(failed_key) + 1) % len(keys)
        key = keys[_key_index % len(keys)]
        _key_index = (_key_index + 1) % len(keys)
        return key




def db_read():
    try:
        encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        records = []
        for row in rows:
            if row:
                try:
                    records.append(json.loads(row[0]))
                except Exception:
                    pass
        return records
    except Exception as e:
        print(f"  db_read 錯誤: {e}")
        return []




def db_find_row(movie_id):
    try:
        encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        for i, row in enumerate(rows):
            if row:
                try:
                    if json.loads(row[0]).get("id") == movie_id:
                        return i + 1
                except Exception:
                    pass
    except Exception as e:
        print(f"  db_find_row 錯誤: {e}")
    return None


def db_find_row_by_yt_id(yt_id):
    if not yt_id:
        return None, None
    try:
        encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        for i, row in enumerate(rows):
            if row:
                try:
                    film = json.loads(row[0])
                    if film.get("ytId") == yt_id:
                        return i + 1, film
                except Exception:
                    pass
    except Exception as e:
        print(f"  db_find_row_by_yt_id 錯誤: {e}")
    return None, None




def db_append(record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
    return sheets_request(
        "POST",
        f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
        {"values": [[json.dumps(record, ensure_ascii=False)]]},
    )




def db_update_row(row_num, record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A{row_num}")
    return sheets_request(
        "PUT",
        f"/values/{encoded}?valueInputOption=RAW",
        {"values": [[json.dumps(record, ensure_ascii=False)]]},
    )




def get_sheet_id():
    global _sheet_id_cache
    if _sheet_id_cache is not None:
        return _sheet_id_cache
    info = sheets_request("GET", "")
    for s in info.get("sheets", []):
        if s["properties"]["title"] == SHEET_NAME:
            _sheet_id_cache = s["properties"]["sheetId"]
            return _sheet_id_cache
    return 0


def get_user_prefs_sheet_id():
    global _user_prefs_sheet_id_cache
    if _user_prefs_sheet_id_cache is not None:
        return _user_prefs_sheet_id_cache
    info = sheets_request("GET", "")
    for s in info.get("sheets", []):
        if s["properties"]["title"] == USER_PREFS_SHEET:
            _user_prefs_sheet_id_cache = s["properties"]["sheetId"]
            return _user_prefs_sheet_id_cache
    return 0


def user_prefs_read_all():
    try:
        encoded = urllib.parse.quote(f"{USER_PREFS_SHEET}!A:B")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        out = {}
        for row in rows:
            if len(row) < 2:
                continue
            name = str(row[0]).strip()
            if not name or name.lower() == "username":
                continue
            try:
                data = json.loads(row[1])
                out[name] = normalize_prefs(data)
            except Exception:
                pass
        return out
    except Exception as e:
        print(f"  user_prefs_read_all 錯誤: {e}")
        return {}


def user_prefs_find_row(user_name):
    try:
        encoded = urllib.parse.quote(f"{USER_PREFS_SHEET}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        for i, row in enumerate(rows):
            if row and str(row[0]).strip() == user_name:
                return i + 1
    except Exception as e:
        print(f"  user_prefs_find_row 錯誤: {e}")
    return None


def user_prefs_save_one(user_name, prefs):
    ensure_sheet()
    normalized = normalize_prefs(prefs)
    if not normalized.get("updatedAt"):
        normalized["updatedAt"] = utc_now()
    if not normalized.get("lastSyncAt"):
        normalized["lastSyncAt"] = normalized["updatedAt"]
    payload = json.dumps(normalized, ensure_ascii=False)
    row_num = user_prefs_find_row(user_name)
    if row_num:
        encoded = urllib.parse.quote(f"{USER_PREFS_SHEET}!B{row_num}")
        sheets_request(
            "PUT",
            f"/values/{encoded}?valueInputOption=RAW",
            {"values": [[payload]]},
        )
    else:
        encoded = urllib.parse.quote(f"{USER_PREFS_SHEET}!A:B")
        sheets_request(
            "POST",
            f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
            {"values": [[user_name, payload]]},
        )


def load_user_behavior_from_sheets():
    global user_behavior
    loaded = user_prefs_read_all()
    with _user_lock:
        user_behavior = loaded
    print(f"  已載入 {len(loaded)} 位使用者喜好（{USER_PREFS_SHEET}）")


def get_user_prefs(user_name):
    with _user_lock:
        if user_name not in user_behavior:
            user_behavior[user_name] = normalize_prefs({})
        else:
            user_behavior[user_name] = normalize_prefs(user_behavior[user_name])
        return user_behavior[user_name]


def persist_user_prefs(user_name):
    with _user_lock:
        prefs = user_behavior.get(user_name)
    if not prefs:
        return
    try:
        user_prefs_save_one(user_name, normalize_prefs(prefs))
    except Exception as e:
        print(f"  persist_user_prefs 錯誤 ({user_name}): {e}")


def set_user_temperature(user_name, movie_id, temperature):
    """Set thermometer rating 0–100 and sync legacy like/dislike lists."""
    u = get_user_prefs(user_name)
    temps = dict(u.get("temperatures") or {})
    temps[movie_id] = clamp_temperature(temperature)
    u["temperatures"] = temps
    normalized = normalize_prefs(u)
    with _user_lock:
        user_behavior[user_name] = normalized
    persist_user_prefs(user_name)
    return normalized


def movie_to_sheets_card(m, score=None, match_reasons=None):
    # poster / thumb 皆填入解析後 URL，與後台列表一致（APP 讀任一欄即可）
    image_url = resolve_movie_poster(m)
    emotions, atmospheres = movie_emotion_atmosphere_tags(m)
    card = {
        "id": m.get("id", ""),
        "title": m.get("title", ""),
        "year": m.get("year")
        or (str(m.get("publishedAt", ""))[:4] if m.get("publishedAt") else ""),
        "poster": image_url,
        "thumb": image_url,
        "scenes": (m.get("scenesMain") or []) + (m.get("scenesSub") or []),
        "genres": m.get("genres", []),
        "emotions": emotions,
        "atmospheres": atmospheres,
        "moods": m.get("moods", []) or (emotions + atmospheres),
        "actors": m.get("actors") or m.get("cast", ""),
        "url": m.get("url", ""),
        "ytId": m.get("ytId", ""),
        "tmdbId": m.get("tmdbId", ""),
        "mediaType": m.get("mediaType", "movie"),
    }
    if score is not None:
        card["score"] = round(score, 2)
    if match_reasons:
        card["matchReasons"] = match_reasons
    return card


def build_recommend_cards(movies, user_prefs, limit=20):
    ranked, meta = ranked_movies(movies, user_prefs, limit=limit, weights=DEFAULT_WEIGHTS)
    cards = [movie_to_sheets_card(m, score=s, match_reasons=reasons) for s, m, reasons in ranked]
    return cards, meta


def parse_query_string(path_with_query):
    if "?" not in path_with_query:
        return {}
    qs = path_with_query.split("?", 1)[1]
    return {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}


def push_feed_read_all():
    try:
        encoded = urllib.parse.quote(f"{PUSH_FEED_SHEET}!A:B")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        out = {}
        for row in rows:
            if len(row) < 2:
                continue
            name = str(row[0]).strip()
            if not name or name.lower() == "username":
                continue
            try:
                out[name] = json.loads(row[1])
            except Exception:
                pass
        return out
    except Exception as e:
        print(f"  push_feed_read_all 錯誤: {e}")
        return {}


def push_feed_find_row(user_name):
    try:
        encoded = urllib.parse.quote(f"{PUSH_FEED_SHEET}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        for i, row in enumerate(rows):
            if row and str(row[0]).strip() == user_name:
                return i + 1
    except Exception as e:
        print(f"  push_feed_find_row 錯誤: {e}")
    return None


def push_feed_save_one(user_name, feed_doc):
    ensure_sheet()
    payload = json.dumps(feed_doc, ensure_ascii=False)
    row_num = push_feed_find_row(user_name)
    if row_num:
        encoded = urllib.parse.quote(f"{PUSH_FEED_SHEET}!B{row_num}")
        sheets_request(
            "PUT",
            f"/values/{encoded}?valueInputOption=RAW",
            {"values": [[payload]]},
        )
    else:
        encoded = urllib.parse.quote(f"{PUSH_FEED_SHEET}!A:B")
        sheets_request(
            "POST",
            f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
            {"values": [[user_name, payload]]},
        )
    with _push_feed_lock:
        _push_feed_cache[user_name] = feed_doc


def load_push_feed_from_sheets():
    global _push_feed_cache
    loaded = push_feed_read_all()
    with _push_feed_lock:
        _push_feed_cache = loaded
    print(f"  已載入 {len(loaded)} 筆推送快取（{PUSH_FEED_SHEET}）")


def push_feed_get(user_name):
    with _push_feed_lock:
        cached = _push_feed_cache.get(user_name)
    if cached:
        return cached
    all_feeds = push_feed_read_all()
    doc = all_feeds.get(user_name)
    if doc:
        with _push_feed_lock:
            _push_feed_cache[user_name] = doc
    return doc


def rooms_read_all():
    try:
        encoded = urllib.parse.quote(f"{ROOMS_SHEET}!A:B")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        out = {}
        for row in rows:
            if len(row) < 2:
                continue
            code = normalize_room_code(row[0])
            if not code or code.lower() == "code":
                continue
            try:
                doc = normalize_room(json.loads(row[1]))
                doc["code"] = code
                out[code] = doc
            except Exception:
                pass
        return out
    except Exception as e:
        print(f"  rooms_read_all 錯誤: {e}")
        return {}


def rooms_find_row(code):
    code = normalize_room_code(code)
    if not code:
        return None
    try:
        encoded = urllib.parse.quote(f"{ROOMS_SHEET}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        for i, row in enumerate(rows):
            if row and normalize_room_code(row[0]) == code:
                return i + 1
    except Exception as e:
        print(f"  rooms_find_row 錯誤: {e}")
    return None


def rooms_save_one(room_doc):
    ensure_sheet()
    doc = normalize_room(room_doc)
    code = doc["code"]
    if not code:
        raise ValueError("缺少房間代碼")
    payload = json.dumps(doc, ensure_ascii=False)
    row_num = rooms_find_row(code)
    if row_num:
        encoded = urllib.parse.quote(f"{ROOMS_SHEET}!B{row_num}")
        sheets_request(
            "PUT",
            f"/values/{encoded}?valueInputOption=RAW",
            {"values": [[payload]]},
        )
    else:
        existing = rooms_read_all()
        if code in existing:
            raise ValueError(f"房間代碼 {code} 已存在")
        encoded = urllib.parse.quote(f"{ROOMS_SHEET}!A:B")
        sheets_request(
            "POST",
            f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
            {"values": [[code, payload]]},
        )
    with _rooms_lock:
        _rooms_cache[code] = doc
    return doc


def load_rooms_from_sheets():
    global _rooms_cache
    loaded = rooms_read_all()
    with _rooms_lock:
        _rooms_cache = loaded
    print(f"  已載入 {len(loaded)} 個多人房間（{ROOMS_SHEET}）")


def room_get(code):
    code = normalize_room_code(code)
    if not code:
        return None
    with _rooms_lock:
        cached = _rooms_cache.get(code)
    if cached:
        return cached
    all_rooms = rooms_read_all()
    doc = all_rooms.get(code)
    if doc:
        with _rooms_lock:
            _rooms_cache[code] = doc
    return doc


def room_create(room_name="", message="", created_by=""):
    existing = rooms_read_all()
    doc = build_new_room(set(existing.keys()), room_name=room_name, message=message, created_by=created_by)
    return rooms_save_one(doc)


def room_join(code, user_name):
    code = normalize_room_code(code)
    user_name = (user_name or "").strip()
    if not code:
        return None, "缺少 roomCode"
    if not user_name:
        return None, "缺少 userName"
    doc = room_get(code)
    if not doc:
        return None, "房間不存在"
    if doc.get("status") == "closed":
        return None, "房間已關閉"
    updated = room_add_member(doc, user_name)
    saved = rooms_save_one(updated)
    return saved, None


def room_close(code):
    code = normalize_room_code(code)
    doc = room_get(code)
    if not doc:
        return None, "房間不存在"
    doc["status"] = "closed"
    return rooms_save_one(doc), None


def room_publish_all_members(code, limit=20, message=""):
    code = normalize_room_code(code)
    doc = room_get(code)
    if not doc:
        return None, "房間不存在"
    if doc.get("status") == "closed":
        return None, "房間已關閉"
    members = doc.get("members") or []
    if not members:
        return None, "房間尚無成員"
    msg = (message or doc.get("message") or "").strip()
    results = []
    for name in members:
        prefs = get_user_prefs(name)
        if not (prefs.get("like") or prefs.get("temperatures")):
            results.append({
                "userName": name,
                "ok": False,
                "skipped": True,
                "error": "尚無喜好記錄",
            })
            continue
        try:
            pub = admin_publish_push(name, limit=limit, message=msg)
            results.append({
                "userName": name,
                "ok": True,
                "cardCount": pub.get("cardCount", 0),
                "publishedAt": pub.get("publishedAt"),
            })
        except Exception as e:
            results.append({"userName": name, "ok": False, "error": str(e)})
    doc["lastPushAt"] = utc_now()
    if msg:
        doc["message"] = msg
    rooms_save_one(doc)
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "ok": True,
        "roomCode": code,
        "published": ok_n,
        "total": len(results),
        "results": results,
        "lastPushAt": doc["lastPushAt"],
    }, None


def admin_build_push_payload(user_name, limit=20, message=""):
    movies = db_read()
    u = get_user_prefs(user_name)
    cards, meta = build_recommend_cards(movies, u, limit=limit)
    return {
        "userName": user_name,
        "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": (message or "").strip(),
        "limit": limit,
        "coldStart": bool(meta.get("coldStart")),
        "profile": meta.get("profile") or summarize_profile(
            {m["id"]: m for m in movies if m.get("id")}, u
        ),
        "cards": cards,
        "cardCount": len(cards),
    }


def admin_publish_push(user_name, limit=20, message=""):
    doc = admin_build_push_payload(user_name, limit=limit, message=message)
    push_feed_save_one(user_name, doc)
    return doc


def user_events_append(user_name, events, device_id=""):
    if not events:
        return
    ensure_sheet()
    values = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        values.append([
            json.dumps(
                {
                    "at": utc_now(),
                    "userName": user_name,
                    "deviceId": device_id or ev.get("deviceId") or "",
                    "type": ev.get("type") or ev.get("action") or "event",
                    "movieId": ev.get("movieId") or ev.get("movie_id") or "",
                },
                ensure_ascii=False,
            )
        ])
    if not values:
        return
    encoded = urllib.parse.quote(f"{USER_EVENTS_SHEET}!A:A")
    sheets_request(
        "POST",
        f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
        {"values": values},
    )


def user_events_read_recent(limit=50):
    try:
        encoded = urllib.parse.quote(f"{USER_EVENTS_SHEET}!A:A")
        rows = sheets_request("GET", f"/values/{encoded}").get("values", [])
        events = []
        for row in reversed(rows[-limit:]):
            if not row:
                continue
            try:
                events.append(json.loads(row[0]))
            except Exception:
                pass
        return list(reversed(events))
    except Exception as e:
        print(f"  user_events_read_recent 錯誤: {e}")
        return []


def admin_push_dashboard():
    load_user_behavior_from_sheets()
    feeds = push_feed_read_all()
    with _push_feed_lock:
        _push_feed_cache.update(feeds)
    with _user_lock:
        users_snapshot = {k: normalize_prefs(v) for k, v in user_behavior.items()}
    movies = db_read()
    overview = multi_user_overview(
        users_snapshot,
        feeds,
        movies,
        user_events_read_recent(40),
    )
    users = []
    for row in overview.get("users") or []:
        feed = feeds.get(row["userName"]) or {}
        users.append({
            **row,
            "message": feed.get("message", ""),
        })
    return {
        "stats": overview.get("stats"),
        "users": users,
        "stalePushCount": overview.get("stalePushCount", 0),
        "recentEvents": overview.get("recentEvents", []),
        "feedSheet": PUSH_FEED_SHEET,
        "prefsSheet": USER_PREFS_SHEET,
        "eventsSheet": USER_EVENTS_SHEET,
        "roomsSheet": ROOMS_SHEET,
        "rooms": rooms_overview(rooms_read_all()),
    }


def admin_republish_stale_users(limit=20, message=""):
    load_user_behavior_from_sheets()
    feeds = push_feed_read_all()
    results = []
    with _user_lock:
        names = list(user_behavior.keys())
    for name in names:
        prefs = normalize_prefs(user_behavior.get(name) or {})
        feed = feeds.get(name)
        if not push_is_stale(prefs, feed):
            results.append({"userName": name, "ok": False, "skipped": True, "reason": "推送仍為最新"})
            continue
        if not prefs.get("like"):
            results.append({"userName": name, "ok": False, "skipped": True, "reason": "尚無喜歡"})
            continue
        try:
            doc = admin_publish_push(name, limit=limit, message=message)
            results.append({
                "userName": name,
                "ok": True,
                "cardCount": doc.get("cardCount", 0),
            })
        except Exception as e:
            results.append({"userName": name, "ok": False, "error": str(e)})
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "published": ok_n, "total": len(results), "results": results}


def handle_sync_pull(body):
    user_name = (body.get("userName") or "").strip()
    if not user_name:
        return 400, {"ok": False, "error": "缺少 userName"}
    include_live = bool(body.get("includeLiveRecommend"))
    limit = int(body.get("limit") or 20)
    prefs = get_user_prefs(user_name)
    feed = push_feed_get(user_name)
    movies = db_read()
    live_cards = None
    live_meta = None
    if include_live:
        live_cards, live_meta = build_recommend_cards(movies, prefs, limit=limit)
    payload = build_sync_pull_payload(
        user_name,
        prefs,
        feed,
        movies,
        include_live=include_live,
        live_cards=live_cards,
        live_meta=live_meta,
    )
    return 200, payload


def handle_sync_push(body):
    user_name = (body.get("userName") or "").strip()
    if not user_name:
        return 400, {"ok": False, "error": "缺少 userName"}
    device_id = (body.get("deviceId") or "").strip()
    with _user_lock:
        server_prefs = normalize_prefs(user_behavior.get(user_name) or {})
    merged = merge_client_prefs(server_prefs, body)
    with _user_lock:
        user_behavior[user_name] = merged
    persist_user_prefs(user_name)
    events = body.get("events") or []
    if events:
        user_events_append(user_name, events, device_id)
    room_code = normalize_room_code(body.get("roomCode") or body.get("room") or "")
    room_doc = None
    if room_code:
        room_doc, room_err = room_join(room_code, user_name)
        if room_err:
            return 400, {"ok": False, "error": room_err}
    auto_publish = bool(body.get("autoPublishRecommend"))
    limit = int(body.get("limit") or 20)
    message = (body.get("message") or "").strip()
    published = None
    if auto_publish and merged.get("like"):
        published = admin_publish_push(user_name, limit=limit, message=message)
    feed = push_feed_get(user_name)
    movies = db_read()
    payload = build_sync_pull_payload(user_name, merged, feed, movies)
    payload["merged"] = True
    if room_doc:
        payload["room"] = room_public_view(room_doc)
    if published:
        payload["published"] = True
        payload["pushFeed"] = published
        payload["pushStale"] = False
    return 200, payload


def admin_publish_push_all(limit=20, message=""):
    load_user_behavior_from_sheets()
    results = []
    with _user_lock:
        names = list(user_behavior.keys())
    for name in names:
        prefs = user_behavior.get(name) or {}
        if not (prefs.get("like")):
            results.append({
                "userName": name,
                "ok": False,
                "skipped": True,
                "error": "尚無喜歡記錄",
            })
            continue
        try:
            doc = admin_publish_push(name, limit=limit, message=message)
            results.append({
                "userName": name,
                "ok": True,
                "cardCount": doc.get("cardCount", 0),
                "publishedAt": doc.get("publishedAt"),
            })
        except Exception as e:
            results.append({"userName": name, "ok": False, "error": str(e)})
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"ok": True, "published": ok_n, "total": len(results), "results": results}




def db_delete_row(row_num):
    return sheets_request("POST", ":batchUpdate", {
        "requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId": get_sheet_id(),
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex": row_num,
                }
            }
        }]
    })




def uid():
    import random
    import string
    return "u" + str(int(time.time())) + "".join(random.choices(string.ascii_lowercase, k=4))




def clean_movie_title(title):
    title = (title or "").strip()
    if not title:
        return ""

    book_title_matches = re.findall(r"[\u300a]([^\u300a\u300b]*[\u3400-\u9fff][^\u300a\u300b]*)[\u300b]", title)
    if book_title_matches:
        picked = book_title_matches[-1]
        picked = re.sub(r"(?:\u96fb\u5f71)?(?:\u6b63\u5f0f)?(?:\u5b98\u65b9)?(?:\u4e2d\u6587)?(?:\u9810\u544a|\u9810\u544a\u7247|\u5148\u5c0e\u9810\u544a|\u7d42\u6975\u9810\u544a|\u771f\u4eba\u7248|\u7247\u6bb5|clip|trailer)", "", picked, flags=re.I)
        return picked.strip()

    bracket_matches = re.findall(r"[\u3010\[]([^\u3010\u3011\[\]]*[\u3400-\u9fff][^\u3010\u3011\[\]]*)[\u3011\]]", title)
    if bracket_matches:
        picked = bracket_matches[-1]
        picked = re.sub(r"(?:\u96fb\u5f71)?(?:\u6b63\u5f0f)?(?:\u5b98\u65b9)?(?:\u4e2d\u6587)?(?:\u9810\u544a|\u9810\u544a\u7247|\u5148\u5c0e\u9810\u544a|\u7d42\u6975\u9810\u544a|\u771f\u4eba\u7248|\u7247\u6bb5|clip|trailer)", "", picked, flags=re.I)
        picked = re.sub(r"[|\uff5c:\uff1a\-_\u2013\u2014]+", " ", picked)
        return picked.strip()

    cleaned = re.sub(r"\s*(?:Official\s*)?(?:Trailer|Clip|Teaser)\s*(?:\(\d{4}\))?", "", title, flags=re.I)
    cleaned = re.sub(r"\s*(?:\u96fb\u5f71)?(?:\u6b63\u5f0f)?(?:\u5b98\u65b9)?(?:\u4e2d\u6587)?(?:\u9810\u544a|\u9810\u544a\u7247|\u5148\u5c0e\u9810\u544a|\u7d42\u6975\u9810\u544a)\s*$", "", cleaned)
    return cleaned.strip()



def has_chinese_text(value):
    return bool(re.search(r"[\u3400-\u9fff]", value or ""))



def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None




PHRASE_TW = {
    "军事基地": "軍事基地",
    "休憩室": "休息室",
    "颁奖台": "頒獎台",
    "办公室": "辦公室",
    "实验室": "實驗室",
    "停车场": "停車場",
    "地下车库": "地下車庫",
    "购物中心": "購物中心",
    "商场": "商場",
    "战场": "戰場",
    "战舰": "戰艦",
    "飞船": "飛船",
    "太空船": "太空船",
    "医院": "醫院",
    "学校": "學校",
    "监狱": "監獄",
    "房间": "房間",
    "隧道": "隧道",
    "间谍": "間諜",
    "侦探": "偵探",
    "悬疑": "懸疑",
    "惊悚": "驚悚",
    "动作": "動作",
    "剧情": "劇情",
    "喜剧": "喜劇",
    "爱情": "愛情",
    "科幻": "科幻",
    "奇幻": "奇幻",
    "战争": "戰爭",
    "灾难": "災難",
    "历史": "歷史",
    "动画": "動畫",
    "纪录": "紀錄",
    "综艺": "綜藝",
    "冒险": "冒險",
    "犯罪": "犯罪",
    "紧张": "緊張",
    "壮阔": "壯闊",
    "热血": "熱血",
    "黑暗": "黑暗",
    "危险": "危險",
    "温馨": "溫馨",
    "烧脑": "燒腦",
    "悲伤": "悲傷",
    "感动": "感動",
    "浪漫": "浪漫",
}


CHAR_TW = str.maketrans({
    "军": "軍", "事": "事", "基": "基", "地": "地", "休": "休", "憩": "憩",
    "颁": "頒", "奖": "獎", "台": "台", "办": "辦", "实": "實", "验": "驗",
    "车": "車", "场": "場", "购": "購", "战": "戰", "舰": "艦", "飞": "飛",
    "医": "醫", "学": "學", "监": "監", "狱": "獄", "间": "間", "谍": "諜",
    "侦": "偵", "悬": "懸", "惊": "驚", "动": "動", "剧": "劇", "爱": "愛",
    "争": "爭", "灾": "災", "难": "難", "历": "歷", "画": "畫", "录": "錄",
    "综": "綜", "艺": "藝", "险": "險", "紧": "緊", "张": "張", "壮": "壯",
    "阔": "闊", "热": "熱", "险": "險", "温": "溫", "烧": "燒", "脑": "腦",
    "伤": "傷", "动": "動", "门": "門", "厅": "廳", "楼": "樓", "顶": "頂",
    "馆": "館", "馆": "館", "厂": "廠", "广": "廣", "废": "廢", "旧": "舊",
    "梦": "夢", "异": "異", "龙": "龍", "汉": "漢", "语": "語", "华": "華",
    "国": "國", "万": "萬", "与": "與", "开": "開", "关": "關", "后": "後",
    "里": "裡", "处": "處", "这": "這", "个": "個", "为": "為", "会": "會",
    "现": "現", "发": "發", "声": "聲", "乐": "樂", "气": "氣", "杀": "殺",
    "击": "擊", "枪": "槍", "弹": "彈", "队": "隊", "员": "員", "团": "團",
    "众": "眾", "岛": "島", "桥": "橋", "乡": "鄉", "镇": "鎮", "边": "邊",
    "际": "際", "运": "運", "输": "輸", "轻": "輕", "轨": "軌", "湾": "灣",
    "线": "線", "电": "電", "网": "網", "机": "機", "舰": "艦", "码": "碼",
    "码": "碼", "术": "術", "数": "數", "据": "據", "阴": "陰", "阳": "陽",
    "风": "風", "云": "雲", "无": "無", "马": "馬", "鱼": "魚", "鸟": "鳥",
})




def to_traditional_text(value):
    if isinstance(value, str):
        text = value
        for src, dst in PHRASE_TW.items():
            text = text.replace(src, dst)
        return text.translate(CHAR_TW)
    if isinstance(value, list):
        return [to_traditional_text(v) for v in value]
    if isinstance(value, dict):
        return {k: to_traditional_text(v) for k, v in value.items()}
    return value




def normalize_emotion_fields(record: dict) -> dict:
    emotions, atmospheres = movie_emotion_atmosphere_tags(record)
    record["emotions"] = emotions
    record["atmospheres"] = atmospheres
    record["moods"] = emotions + atmospheres
    return record


def movies_missing_atmospheres(movies=None) -> list[dict]:
    movies = movies if movies is not None else db_read()
    missing = []
    for m in movies:
        _, atmospheres = movie_emotion_atmosphere_tags(m)
        if not atmospheres:
            missing.append(m)
    return missing


_GENRE_ATMOSPHERE_MAP = {
    "恐怖": ["黑暗", "陰森", "壓抑", "詭譎"],
    "驚悚": ["陰暗", "緊繃", "詭譎", "潮濕"],
    "懸疑": ["神秘", "陰鬱", "冷冽", "詭譎"],
    "科幻": ["未來感", "霓虹", "冷冽", "金屬感"],
    "奇幻": ["夢幻", "超現實", "迷幻", "華麗"],
    "愛情": ["浪漫", "柔和", "溫暖", "細膩"],
    "浪漫": ["浪漫", "柔和", "溫暖", "細膩"],
    "喜劇": ["明亮", "輕快", "活潑", "繽紛"],
    "動作": ["硬派", "緊湊", "熱血", "粗獷"],
    "戰爭": ["肅殺", "硝煙", "沉重", "壯闊"],
    "古裝": ["古風", "厚重", "東方美學", "寫實"],
    "武俠": ["江湖", "古風", "飄逸", "寫實"],
    "犯罪": ["陰暗", "寫實", "冷冽", "頹廢"],
    "紀錄": ["寫實", "生活化", "自然光", "紀實感"],
    "動畫": ["繽紛", "夢幻", "童趣", "明亮"],
    "音樂": ["華麗", "節奏感", "舞台感", "熱烈"],
    "家庭": ["溫馨", "日常", "柔和", "治癒"],
    "青春": ["清新", "明亮", "校園感", "青澀"],
}

_SCENE_ATMOSPHERE_HINTS = [
    "雨夜", "霓虹", "復古", "潮濕", "炎熱", "雪國", "海邊", "都市", "鄉村",
    "密室", "廢墟", "太空", "森林", "監獄", "醫院", "學校", "酒吧", "教堂",
]

_EMOTION_NOT_ATMOSPHERE = {
    "感動", "緊張", "興奮", "害怕", "快樂", "悲傷", "憤怒", "驚喜", "無聊",
}


def heuristic_atmospheres_for_movie(movie: dict) -> list[str]:
    """Fallback atmosphere tags from genres, scenes, and title/desc keywords."""
    found: list[str] = []
    seen: set[str] = set()

    def add(term: str):
        t = to_traditional_text(str(term).strip())
        if not t or t in seen or t in _EMOTION_NOT_ATMOSPHERE:
            return
        seen.add(t)
        found.append(t)

    genres = movie.get("genres") or []
    for g in genres:
        gs = str(g)
        for key, tags in _GENRE_ATMOSPHERE_MAP.items():
            if key in gs:
                for t in tags:
                    add(t)

    scenes = list(movie.get("scenesMain") or []) + list(movie.get("scenesSub") or []) + list(movie.get("scenes") or [])
    for sc in scenes:
        ss = str(sc)
        for hint in _SCENE_ATMOSPHERE_HINTS:
            if hint in ss:
                add(hint)

    blob = " ".join([
        str(movie.get("title") or ""),
        str(movie.get("desc") or ""),
        " ".join(genres),
        " ".join(scenes),
    ])
    for hint in _SCENE_ATMOSPHERE_HINTS:
        if hint in blob:
            add(hint)

    if len(found) < 4:
        for t in ["寫實", "電影感", "敘事感", "沉浸"]:
            add(t)
            if len(found) >= 4:
                break
    return found[:8]


def call_gemini_atmospheres_for_movie(movie: dict) -> dict:
    """Generate atmosphere tags from existing movie metadata (text-only, no video)."""
    emotions, existing = movie_emotion_atmosphere_tags(movie)
    if existing:
        return {"ok": True, "atmospheres": existing, "skipped": True}

    scenes_main = movie.get("scenesMain") or []
    scenes_sub = movie.get("scenesSub") or []
    if not scenes_main and not scenes_sub:
        scenes_main = movie.get("scenes") or []

    text_prompt = f"""請根據以下電影資料，只輸出氛圍標籤 JSON（不要 markdown、不要說明）。
片名：{movie.get("title", "")}
簡介：{movie.get("desc", "")}
類型：{", ".join(movie.get("genres") or [])}
情緒：{", ".join(emotions)}
主要場景：{", ".join(scenes_main)}
次要場景：{", ".join(scenes_sub)}

只輸出：
{{"atmospheres": ["4到8個氛圍標籤，描述畫面與聽覺的整體質感"]}}

規則：
1. 只填氛圍與視聽質感（如：黑暗、夢幻、復古、壓抑、華麗、詭譎、霓虹、潮濕、寫實）
2. 不要情緒詞（如感動、緊張、興奮）
3. 不要類型詞（如喜劇、恐怖、愛情）
4. 繁體中文，去重"""

    payload = {
        "contents": [{"parts": [{"text": text_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }
    out = gemini_generate_with_retry(payload, timeout=90)
    if not out.get("ok"):
        return out
    data = out.get("data") or {}
    atmospheres = data.get("atmospheres") or []
    if isinstance(atmospheres, str):
        atmospheres = [x.strip() for x in re.split(r"[,，、]", atmospheres) if x.strip()]
    atmospheres = [to_traditional_text(x) for x in atmospheres if str(x).strip()]
    if not atmospheres:
        return {"ok": False, "error": "Gemini 未回傳氛圍標籤"}
    return {"ok": True, "atmospheres": atmospheres, "model": out.get("model")}


def save_movie_atmospheres(movie: dict, atmospheres: list[str]) -> dict:
    row_num = db_find_row(movie.get("id"))
    if not row_num:
        raise ValueError("找不到電影列")
    updated = dict(movie)
    updated["atmospheres"] = [str(x).strip() for x in atmospheres if str(x).strip()]
    normalize_emotion_fields(updated)
    db_update_row(row_num, updated)
    return updated


def fill_missing_atmospheres(limit=20, movie_ids=None, allow_heuristic=True, mode="auto") -> dict:
    missing = movies_missing_atmospheres()
    if movie_ids:
        id_set = {str(x).strip() for x in movie_ids if str(x).strip()}
        missing = [m for m in missing if m.get("id") in id_set]
    batch = missing[: max(1, min(int(limit or 20), 100))]
    results = []
    filled = 0
    for m in batch:
        title = m.get("title") or m.get("id") or "?"
        try:
            _, existing = movie_emotion_atmosphere_tags(m)
            if existing:
                results.append({"id": m.get("id"), "title": title, "ok": True, "skipped": True, "count": len(existing)})
                continue

            source = "gemini"
            atmospheres: list[str] = []
            if mode == "heuristic":
                atmospheres = heuristic_atmospheres_for_movie(m)
                source = "heuristic"
            else:
                gen = call_gemini_atmospheres_for_movie(m)
                if gen.get("ok") and not gen.get("skipped"):
                    atmospheres = gen.get("atmospheres") or []
                elif allow_heuristic and mode != "gemini":
                    atmospheres = heuristic_atmospheres_for_movie(m)
                    source = "heuristic"
                elif gen.get("skipped"):
                    results.append({"id": m.get("id"), "title": title, "ok": True, "skipped": True, "count": len(gen.get("atmospheres") or [])})
                    continue
                else:
                    results.append({"id": m.get("id"), "title": title, "ok": False, "error": gen.get("error")})
                    continue

            if not atmospheres:
                results.append({"id": m.get("id"), "title": title, "ok": False, "error": "無法產生氛圍標籤"})
                continue

            save_movie_atmospheres(m, atmospheres)
            filled += 1
            results.append({
                "id": m.get("id"),
                "title": title,
                "ok": True,
                "source": source,
                "count": len(atmospheres),
                "atmospheres": atmospheres,
            })
        except Exception as e:
            results.append({"id": m.get("id"), "title": title, "ok": False, "error": str(e)})
    remaining = len(movies_missing_atmospheres())
    return {
        "ok": True,
        "processed": len(batch),
        "filled": filled,
        "remaining": remaining,
        "results": results,
    }


def normalize_analysis_result(result):
    for key in ["title", "desc", "scenes_main", "scenes_sub", "genres", "emotions", "atmospheres", "moods", "cast"]:
        if key in result:
            result[key] = to_traditional_text(result[key])
    emotions = result.get("emotions") or []
    atmospheres = result.get("atmospheres") or []
    legacy = result.get("moods") or []
    if not emotions and not atmospheres and legacy:
        emotions = legacy
    result["emotions"] = emotions
    result["atmospheres"] = atmospheres
    result.pop("moods", None)
    if result.get("year") is not None:
        y = re.sub(r"\D", "", str(result.get("year", "")))[:4]
        result["year"] = y if len(y) == 4 else ""
    return result


def normalize_movie_record(record):
    """統一 year 欄位（四位數字），可從 publishedAt 推斷；儲存前優先補 TMDB 海報。"""
    normalize_emotion_fields(record)
    y = str(record.get("year") or "").strip()
    if re.fullmatch(r"\d{4}", y):
        record["year"] = y
    else:
        record.pop("year", None)
        pub = str(record.get("publishedAt") or "")
        m = re.match(r"^(\d{4})", pub)
        if m:
            record["year"] = m.group(1)
    enrich_movie_poster(record)
    return record


def extract_yt_id(url):
    if not url:
        return ""
    m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else ""


def is_youtube_video_id(yt_id):
    if not yt_id or str(yt_id).startswith("tmdb-"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", str(yt_id)))


_tmdb_poster_cache = {}


def fetch_tmdb_poster_by_id(tmdb_id, media_type="movie"):
    if not tmdb_id or not TMDB_API_KEY:
        return ""
    key = f"{media_type}-{tmdb_id}"
    if key in _tmdb_poster_cache:
        return _tmdb_poster_cache[key]
    try:
        data = tmdb_request(f"/{media_type}/{tmdb_id}")
        path = data.get("poster_path") or ""
        if not path:
            path = data.get("backdrop_path") or ""
        url = f"https://image.tmdb.org/t/p/w500{path}" if path else ""
        _tmdb_poster_cache[key] = url
        return url
    except Exception as e:
        print(f"  fetch_tmdb_poster_by_id 錯誤: {e}")
        _tmdb_poster_cache[key] = ""
        return ""


def search_tmdb_poster_by_title(title, year=""):
    """Search TMDB by title/year; return dict with poster URL or None."""
    query = clean_movie_title(title) or (title or "").strip()
    if not query or not TMDB_API_KEY:
        return None
    year_s = str(year or "").strip()
    for media_type in ("movie", "tv"):
        params = {"query": query}
        if year_s.isdigit() and len(year_s) == 4 and media_type == "movie":
            params["year"] = year_s
        try:
            data = tmdb_request(f"/search/{media_type}", params)
        except Exception as e:
            print(f"  search_tmdb_poster_by_title 錯誤: {e}")
            continue
        results = data.get("results") or []
        if year_s.isdigit() and len(year_s) == 4:
            for hit in results:
                date = (hit.get("release_date") or hit.get("first_air_date") or "")
                if date.startswith(year_s) and hit.get("poster_path"):
                    path = hit["poster_path"]
                    return {
                        "tmdbId": hit["id"],
                        "mediaType": media_type,
                        "poster": f"https://image.tmdb.org/t/p/w500{path}",
                    }
        for hit in results:
            path = hit.get("poster_path") or ""
            if path:
                return {
                    "tmdbId": hit["id"],
                    "mediaType": media_type,
                    "poster": f"https://image.tmdb.org/t/p/w500{path}",
                }
    return None


def enrich_movie_poster(record):
    """On save: prefer TMDB poster; YouTube thumbnail only as fallback."""
    if not isinstance(record, dict):
        return record

    poster = (record.get("poster") or "").strip()
    thumb = (record.get("thumb") or "").strip()
    if "image.tmdb.org" in poster or "image.tmdb.org" in thumb:
        url = poster if "image.tmdb.org" in poster else thumb
        record["poster"] = record["thumb"] = url
        return record

    media_type, parsed_id = parse_tmdb_from_yt_id(record.get("ytId"))
    tmdb_id = record.get("tmdbId") or parsed_id
    media_type = record.get("mediaType") or media_type or "movie"
    url = ""

    if tmdb_id:
        url = fetch_tmdb_poster_by_id(tmdb_id, media_type)

    if not url:
        hit = search_tmdb_poster_by_title(record.get("title") or "", record.get("year") or "")
        if hit:
            url = hit["poster"]
            record["tmdbId"] = hit["tmdbId"]
            record["mediaType"] = hit["mediaType"]

    if url:
        record["poster"] = url
        record["thumb"] = url
        return record

    yt_id = record.get("ytId") or ""
    if is_youtube_video_id(yt_id):
        yp = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        record["poster"] = yp
        record["thumb"] = yp
    return record


def parse_tmdb_from_yt_id(yt_id):
    m = re.match(r"^tmdb-(movie|tv)-(\d+)$", str(yt_id or ""))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def resolve_movie_poster(movie):
    """Resolve display poster: TMDB first, then stored TMDB, then YouTube."""
    media_type, parsed_id = parse_tmdb_from_yt_id(movie.get("ytId"))
    tmdb_id = movie.get("tmdbId") or parsed_id
    media_type = movie.get("mediaType") or media_type or "movie"
    if tmdb_id:
        url = fetch_tmdb_poster_by_id(tmdb_id, media_type)
        if url:
            return url

    for field in (movie.get("poster"), movie.get("thumb")):
        poster = (field or "").strip()
        if not poster or "img.youtube.com/vi/tmdb-" in poster:
            continue
        if poster.startswith("/"):
            return f"https://image.tmdb.org/t/p/w500{poster}"
        if poster.startswith("http"):
            if "image.tmdb.org" in poster:
                return poster
            if "img.youtube.com" not in poster:
                return poster

    yt_id = movie.get("ytId") or ""
    if is_youtube_video_id(yt_id):
        return f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
    return ""


def gemini_friendly_error(raw):
    text = raw or ""
    low = text.lower()
    if "location is not supported" in low:
        return (
            "Gemini API 回報目前地區不可用（User location is not supported）。"
            "請在 Google AI Studio 建立新的 API Key（建議美國/支援地區），"
            "並在網站「API Key 設定」更新。"
        )
    if "quota" in low or "exceeded" in low or '"code": 429' in text:
        return (
            "Gemini API 配額已用完或免費額度為 0。"
            "請到 Google AI Studio 檢查配額/帳單，或新增可用的 API Key 後在網站更新。"
        )
    return text[:400]


def fetch_youtube_meta(yt_url):
    yt_id = extract_yt_id(yt_url)
    if not yt_id:
        return None
    params = {"part": "snippet", "id": yt_id, "key": YOUTUBE_API_KEY}
    api_url = f"https://www.googleapis.com/youtube/v3/videos?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(api_url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        items = data.get("items", [])
        if not items:
            return None
        snippet = items[0].get("snippet", {})
        return {
            "ytId": yt_id,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "description": (snippet.get("description") or "")[:1200],
            "url": f"https://www.youtube.com/watch?v={yt_id}",
        }
    except Exception as e:
        print(f"  fetch_youtube_meta 錯誤: {e}")
        return None


def gemini_models_to_try():
    models = [MODEL] + [m for m in MODEL_FALLBACKS if m != MODEL]
    seen = set()
    out = []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def gemini_http_post(payload, api_key, model, timeout=120):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        err_text = e.read().decode("utf-8", errors="replace")
        return e.code, None, err_text
    except Exception as e:
        return 0, None, str(e)


def gemini_parse_candidate(data):
    if not data:
        return None, "Gemini 回傳為空"
    if data.get("error"):
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return None, gemini_friendly_error(msg)
    candidates = data.get("candidates") or []
    if not candidates:
        return None, "Gemini 沒有產生內容"
    parts = candidates[0].get("content", {}).get("parts") or []
    text = next((p.get("text", "") for p in parts if p.get("text")), "")
    if not text:
        return None, "Gemini 回傳文字為空"
    result = extract_json(text)
    if not result:
        return None, f"無法解析 JSON: {text[:200]}"
    return result, ""


def gemini_generate_with_retry(payload, timeout=120):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}

    last_error = "Gemini 分析失敗"
    region_keys: set[str] = set()
    quota_keys: set[str] = set()
    current_key = None
    max_rounds = min(max(len(keys), 2), 6)

    for round_i in range(max_rounds):
        current_key = get_next_key(failed_key=current_key)
        key_suffix = current_key[-6:]
        for model in gemini_models_to_try():
            status, data, err_text = gemini_http_post(payload, current_key, model, timeout=timeout)
            if status == 200:
                result, parse_err = gemini_parse_candidate(data)
                if result:
                    return {"ok": True, "data": normalize_analysis_result(result), "model": model}
                last_error = parse_err
                continue

            print(f"!!! Gemini HTTP {status} key=...{key_suffix} model={model} round={round_i + 1}/{max_rounds}")
            print(f"!!! {(err_text or '')[:500]}")
            last_error = gemini_friendly_error(err_text or f"HTTP {status}")
            err_low = (err_text or "").lower()

            if "location is not supported" in err_low:
                region_keys.add(current_key)
                break
            if status in (429, 403) or "quota" in err_low:
                quota_keys.add(current_key)
                time.sleep(0.5)
                break
            if status == 503:
                time.sleep(3)
                break
            if status == 404:
                continue
        else:
            time.sleep(1)

        if len(region_keys) >= len(keys):
            return {"ok": False, "error": last_error, "code": "GEMINI_REGION"}
        if len(quota_keys) >= len(keys) and not region_keys:
            return {"ok": False, "error": last_error, "code": "GEMINI_QUOTA"}
        if len(region_keys | quota_keys) >= len(keys):
            return {
                "ok": False,
                "error": "所有 Gemini Key 都失敗：部分配額用盡、部分地區受限。請在 Google AI Studio 新增可用 Key 並更新網站設定。",
                "code": "GEMINI_KEYS_BAD",
            }

    if quota_keys and not region_keys:
        return {"ok": False, "error": last_error, "code": "GEMINI_QUOTA"}
    if region_keys:
        return {"ok": False, "error": last_error, "code": "GEMINI_REGION"}
    return {"ok": False, "error": last_error}


def call_gemini_analyze_text(meta):
    text_prompt = f"""請根據以下 YouTube 預告片資訊，產生展覽用電影資料 JSON（只能輸出 JSON，不要 markdown）。
片名：{meta.get('title', '')}
頻道：{meta.get('channel', '')}
說明：{meta.get('description', '')}

{PROMPT}"""
    payload = {
        "contents": [{"parts": [{"text": text_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    out = gemini_generate_with_retry(payload, timeout=90)
    if out.get("ok"):
        out["data"].setdefault("title", clean_movie_title(meta.get("title", "")) or meta.get("title", ""))
        out["mode"] = "text"
    return out


def call_gemini_analyze_video(yt_url):
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"file_data": {"file_uri": yt_url}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    out = gemini_generate_with_retry(payload, timeout=180)
    if out.get("ok"):
        out["mode"] = "video"
    return out


def call_gemini_analyze(yt_url):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}

    yt_id = extract_yt_id(yt_url)
    if yt_id:
        yt_url = f"https://www.youtube.com/watch?v={yt_id}"

    meta = fetch_youtube_meta(yt_url)
    if meta:
        print("  使用 YouTube 標題／說明進行文字分析…")
        text_result = call_gemini_analyze_text(meta)
        if text_result.get("ok"):
            return text_result
        if text_result.get("code") in ("GEMINI_REGION", "GEMINI_QUOTA", "GEMINI_KEYS_BAD"):
            return text_result

    print("  文字分析未成功，嘗試直接分析 YouTube 影片…")
    return call_gemini_analyze_video(yt_url)


def call_gemini_tmdb(item):
    trailer_url = (item.get("url") or "").strip()
    if trailer_url and ("youtube.com" in trailer_url or "youtu.be" in trailer_url):
        video_result = call_gemini_analyze(trailer_url)
        if video_result.get("ok") and isinstance(video_result.get("data"), dict):
            data = video_result["data"]
            if item.get("title"):
                data["title"] = item.get("title")
            return {"ok": True, "data": data}

    media_label = "影劇" if item.get("mediaType") == "tv" else "電影"
    text_prompt = f"""請根據以下 TMDB {media_label}資料，產生給展覽觀眾搜尋用的電影資料 JSON。
只能輸出 JSON，不要 markdown，不要說明文字。
請產生「好搜尋、可策展、可聯想」的標籤，不要只給很少的類型詞。

片名：{item.get("title", "")}
類型：{", ".join(item.get("tmdbGenres", []) or [])}
日期：{item.get("publishedAt", "")}
簡介：{item.get("desc", "")}

請輸出：
{{
  "title": "中文片名",
  "desc": "25字內簡介",
  "scenes_main": ["3到6個主要場景，只填具體地點名稱"],
  "scenes_sub": ["3到6個次要場景，只填具體地點名稱"],
  "genres": ["6到10個類型與題材關鍵詞"],
  "emotions": ["4到8個情緒標籤，描述觀眾觀影時的情緒反應"],
  "atmospheres": ["4到8個氛圍標籤，描述畫面與聽覺的整體質感"],
  "cast": ["演員1名稱", "演員2名稱", "演員3名稱"]
}}

重要規則：
1. scenes_main 和 scenes_sub 只能填具體地點或空間，不要填抽象世界觀
2. 禁止場景出現：未知世界、冒險市、奇幻世界、魔法世界、異世界、夢境世界、命運舞台、故事世界
3. genres 不只填片種，也要補題材與可搜尋關鍵詞
4. emotions 只填情緒反應詞；atmospheres 只填氛圍與視聽質感詞，兩者不可混用
5. 每個陣列都要去重，不要重複意思太接近的詞
6. 所有輸出都必須使用台灣繁體中文，不可以出現簡體中文"""

    payload = {
        "contents": [{"parts": [{"text": text_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    out = gemini_generate_with_retry(payload, timeout=90)
    if out.get("ok"):
        d = out["data"]
        d.setdefault("title", item.get("title", ""))
        d.setdefault("desc", item.get("desc", ""))
        d.setdefault("scenes_main", [])
        d.setdefault("scenes_sub", [])
        d.setdefault("genres", item.get("tmdbGenres", []))
        d.setdefault("emotions", [])
        d.setdefault("atmospheres", [])
    return out





def tmdb_request(path, params=None):
    if not TMDB_API_KEY:
        raise Exception("未設定 TMDB_API_KEY")
    params = dict(params or {})
    params["api_key"] = TMDB_API_KEY
    params.setdefault("language", "zh-TW")
    url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))




def tmdb_genres(media_type):
    try:
        data = tmdb_request(f"/genre/{media_type}/list")
        return {g["id"]: g["name"] for g in data.get("genres", [])}
    except Exception:
        return {}




def tmdb_trailer(media_type, tmdb_id):
    try:
        data = tmdb_request(f"/{media_type}/{tmdb_id}/videos")
        videos = data.get("results", [])
        preferred = [
            v for v in videos
            if v.get("site") == "YouTube" and v.get("type") in ["Trailer", "Teaser"]
        ]
        chosen = preferred[0] if preferred else None
        if not chosen:
            return "", ""
        yt_id = chosen.get("key", "")
        return yt_id, f"https://www.youtube.com/watch?v={yt_id}" if yt_id else ""
    except Exception:
        return "", ""




def tmdb_to_result(item, media_type, genre_map, existing_ids):
    title = to_traditional_text(item.get("title") or item.get("name") or "")
    date = item.get("release_date") or item.get("first_air_date") or ""
    year = date[:4] if len(date) >= 4 and date[:4].isdigit() else ""
    poster_path = item.get("poster_path") or ""
    backdrop_path = item.get("backdrop_path") or ""
    poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
    thumb = poster or (f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else "")
    tmdb_id = item.get("id")
    yt_id, trailer_url = tmdb_trailer(media_type, tmdb_id)
    tmdb_key = f"tmdb-{media_type}-{tmdb_id}"
    genres = [to_traditional_text(genre_map.get(gid, "")) for gid in item.get("genre_ids", [])]
    genres = [g for g in genres if g]
    return {
        "source": "tmdb",
        "mediaType": media_type,
        "tmdbId": tmdb_id,
        "ytId": yt_id or tmdb_key,
        "url": trailer_url,
        "title": title,
        "desc": to_traditional_text(item.get("overview", "")),
        "channel": "TMDB",
        "publishedAt": date,
        "year": year,
        "thumb": thumb,
        "poster": poster or thumb,
        "tmdbGenres": genres,
        "inDb": tmdb_key in existing_ids,
    }




class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  {format % args}")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/ping":
            self.send_json(200, {"ok": True, "model": MODEL})

        # APP 專用：全部電影卡片
        elif path == "/api/sheets_card":
            movies = db_read()
            sheets_card = [movie_to_sheets_card(m) for m in movies]
            self.send_json(200, sheets_card)

        elif path == "/api/user/stats":
            movies = db_read()
            with _user_lock:
                snapshot = dict(user_behavior)
            self.send_json(200, {"ok": True, **global_user_stats(snapshot, movies)})

        elif path in ("/api/admin/push/list", "/api/admin/multi/overview"):
            try:
                self.send_json(200, {"ok": True, **admin_push_dashboard()})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        elif path == "/api/admin/missing-atmospheres":
            try:
                missing = movies_missing_atmospheres()
                preview = [
                    {"id": m.get("id"), "title": m.get("title") or ""}
                    for m in missing[:30]
                ]
                self.send_json(200, {
                    "ok": True,
                    "count": len(missing),
                    "totalMovies": len(db_read()),
                    "preview": preview,
                })
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        elif path == "/api/sync/pull":
            qs = parse_query_string(self.path)
            body = {
                "userName": qs.get("userName") or qs.get("user") or "",
                "includeLiveRecommend": qs.get("includeLive") in ("1", "true", "yes"),
                "limit": qs.get("limit") or 20,
            }
            code, payload = handle_sync_pull(body)
            self.send_json(code, payload)
            return

        elif path == "/api/push/feed":
            qs = parse_query_string(self.path)
            user_name = (qs.get("userName") or qs.get("user") or "").strip()
            if not user_name:
                self.send_json(400, {"ok": False, "error": "缺少 userName"})
                return
            feed = push_feed_get(user_name)
            if not feed or not feed.get("cards"):
                self.send_json(200, {
                    "ok": True,
                    "userName": user_name,
                    "hasFeed": False,
                    "cards": [],
                    "message": "尚無已發布的推送，請聯繫展覽人員",
                })
                return
            self.send_json(200, {"ok": True, "hasFeed": True, **feed})

        elif path == "/api/room/list":
            try:
                rooms = rooms_overview(rooms_read_all())
                self.send_json(200, {"ok": True, "rooms": rooms, "count": len(rooms), "roomsSheet": ROOMS_SHEET})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})

        elif path == "/api/room":
            qs = parse_query_string(self.path)
            code = normalize_room_code(qs.get("code") or qs.get("roomCode") or "")
            if not code:
                self.send_json(400, {"ok": False, "error": "缺少 code"})
                return
            doc = room_get(code)
            if not doc:
                self.send_json(404, {"ok": False, "error": "房間不存在"})
                return
            self.send_json(200, {"ok": True, "room": room_public_view(doc)})

        elif path == "/db":
            self.send_json(200, {"ok": True, "data": db_read()})

        elif path == "/admin":
            admin_file = "admin_push.html" if os.path.exists("admin_push.html") else "admin.html"
            if os.path.exists(admin_file):
                with open(admin_file, "r", encoding="utf-8") as f:
                    self.send_html(f.read())
            else:
                self.send_json(404, {"ok": False, "error": "admin_push.html not found"})
        elif path == "/config/keys":
            keys = get_gemini_keys()
            masked = [k[:8] + "..." + k[-4:] if len(k) > 12 else k[:4] + "..." for k in keys]
            self.send_json(200, {"ok": True, "keys": masked, "count": len(keys)})
        elif path == "/api/search/synonyms":
            qs = parse_query_string(self.path)
            if qs.get("defaults") in ("1", "true", "yes"):
                from search_synonyms import DEFAULT_SEARCH_SYNONYM_GROUPS
                groups = normalize_synonym_groups(DEFAULT_SEARCH_SYNONYM_GROUPS)
                self.send_json(200, {"ok": True, "groups": groups, "count": len(groups)})
            else:
                groups = get_search_synonym_groups()
                self.send_json(200, {"ok": True, "groups": groups, "count": len(groups)})
        elif path in ("/api/search/synonyms/defaults", "/synonyms_defaults.json"):
            from search_synonyms import DEFAULT_SEARCH_SYNONYM_GROUPS
            groups = normalize_synonym_groups(DEFAULT_SEARCH_SYNONYM_GROUPS)
            self.send_json(200, {"ok": True, "groups": groups, "count": len(groups)})
        elif path in ["/", "/index.html"]:
            if os.path.exists("index.html"):
                with open("index.html", "r", encoding="utf-8") as f:
                    self.send_html(f.read())
            else:
                self.send_json(404, {"ok": False, "error": "index.html 不存在"})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self.read_body()

        if path == "/api/search/synonyms":
            groups = body.get("groups")
            if not isinstance(groups, list):
                self.send_json(400, {"ok": False, "error": "缺少 groups（陣列）"})
                return
            ok = save_search_synonym_groups(groups)
            if ok:
                saved = get_search_synonym_groups()
                self.send_json(200, {"ok": True, "groups": saved, "count": len(saved)})
            else:
                self.send_json(500, {"ok": False, "error": "儲存相近詞字典失敗"})
            return

        # ========== 多人同步：APP 上傳喜好 ==========
        if path == "/api/sync/push":
            code, payload = handle_sync_push(body)
            self.send_json(code, payload)
            return

        if path == "/api/sync/pull":
            code, payload = handle_sync_pull(body)
            self.send_json(code, payload)
            return

        # ========== 多人房間 ==========
        if path == "/api/room/create":
            try:
                room_name = (body.get("roomName") or body.get("name") or "").strip()
                message = (body.get("message") or "").strip()
                created_by = (body.get("createdBy") or body.get("userName") or "").strip()
                doc = room_create(room_name=room_name, message=message, created_by=created_by)
                self.send_json(200, {"ok": True, "room": room_public_view(doc)})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/room/join":
            code = normalize_room_code(body.get("roomCode") or body.get("code") or body.get("room") or "")
            user_name = (body.get("userName") or "").strip()
            doc, err = room_join(code, user_name)
            if err:
                self.send_json(404 if err == "房間不存在" else 400, {"ok": False, "error": err})
                return
            self.send_json(200, {"ok": True, "room": room_public_view(doc)})
            return

        if path == "/api/room/publish":
            code = normalize_room_code(body.get("roomCode") or body.get("code") or "")
            limit = int(body.get("limit") or 20)
            message = (body.get("message") or "").strip()
            result, err = room_publish_all_members(code, limit=limit, message=message)
            if err:
                self.send_json(404 if "不存在" in err else 400, {"ok": False, "error": err})
                return
            self.send_json(200, result)
            return

        if path == "/api/room/close":
            code = normalize_room_code(body.get("roomCode") or body.get("code") or "")
            doc, err = room_close(code)
            if err:
                self.send_json(404, {"ok": False, "error": err})
                return
            self.send_json(200, {"ok": True, "room": room_public_view(doc)})
            return

        if path == "/api/admin/fill-atmospheres":
            limit = int(body.get("limit") or 20)
            movie_ids = body.get("movieIds") or body.get("ids")
            allow_heuristic = body.get("allowHeuristic", True) is not False
            mode = (body.get("mode") or "auto").strip().lower()
            try:
                self.send_json(200, fill_missing_atmospheres(
                    limit=limit, movie_ids=movie_ids, allow_heuristic=allow_heuristic, mode=mode
                ))
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        # ========== 後台：同步過期推薦 ==========
        if path == "/api/admin/multi/republish_stale":
            limit = int(body.get("limit") or 20)
            message = (body.get("message") or "").strip()
            try:
                self.send_json(200, admin_republish_stale_users(limit=limit, message=message))
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        # ========== APP 溫度計評分 ==========
        if path == "/api/user/rate":
            userName = (body.get("userName") or "").strip()
            movieId = (body.get("movieId") or "").strip()
            if not userName or not movieId:
                self.send_json(400, {"ok": False, "error": "缺少 userName 或 movieId"})
                return
            if "temperature" not in body and "temp" not in body:
                self.send_json(400, {"ok": False, "error": "缺少 temperature（0–100）"})
                return
            temp = clamp_temperature(body.get("temperature", body.get("temp")))
            u = set_user_temperature(userName, movieId, temp)
            user_events_append(
                userName,
                [{"type": "rate", "movieId": movieId, "temperature": temp}],
                body.get("deviceId", ""),
            )
            self.send_json(200, {"ok": True, "user": u, "temperature": temp})
            return

        # ========== APP 喜歡（相容 → 85°） ==========
        if path == "/api/user/like":
            userName = (body.get("userName") or "").strip()
            movieId = (body.get("movieId") or "").strip()
            if not userName or not movieId:
                self.send_json(400, {"ok": False, "error": "缺少 userName 或 movieId"})
                return
            u = set_user_temperature(userName, movieId, TEMP_LIKE)
            user_events_append(userName, [{"type": "like", "movieId": movieId}], body.get("deviceId", ""))
            self.send_json(200, {"ok": True, "user": u, "temperature": TEMP_LIKE})
            return

        # ========== APP 取得使用者 ==========
        if path == "/api/user/get":
            user_name = body.get("userName", "").strip()
            if not user_name:
                self.send_json(400, {"ok": False, "error": "缺少 userName"})
                return
            u = get_user_prefs(user_name)
            movies = db_read()
            profile = summarize_profile(
                {m["id"]: m for m in movies if m.get("id")},
                u,
            )
            self.send_json(200, {"ok": True, "user": u, "profile": profile})
            return

        # ========== APP 不喜歡 ==========
        if path == "/api/user/dislike":
            userName = (body.get("userName") or "").strip()
            movieId = (body.get("movieId") or "").strip()
            if not userName or not movieId:
                self.send_json(400, {"ok": False, "error": "缺少 userName 或 movieId"})
                return
            u = set_user_temperature(userName, movieId, TEMP_DISLIKE)
            user_events_append(userName, [{"type": "dislike", "movieId": movieId}], body.get("deviceId", ""))
            self.send_json(200, {"ok": True, "user": u, "temperature": TEMP_DISLIKE})
            return

        # ========== 喜好分析（後台／展覽用） ==========
        if path == "/api/user/analyze":
            user_name = (body.get("userName") or "").strip()
            limit = int(body.get("limit") or 20)
            if not user_name:
                self.send_json(400, {"ok": False, "error": "缺少 userName"})
                return
            u = get_user_prefs(user_name)
            movies = db_read()
            cards, meta = build_recommend_cards(movies, u, limit=limit)
            self.send_json(
                200,
                {
                    "ok": True,
                    "userName": user_name,
                    "user": u,
                    "profile": meta.get("profile") or summarize_profile(
                        {m["id"]: m for m in movies if m.get("id")}, u
                    ),
                    "coldStart": meta.get("coldStart", False),
                    "recommendations": cards,
                },
            )
            return

        # ========== 後台：預覽推送（不寫入 Sheets） ==========
        if path == "/api/admin/push/preview":
            user_name = (body.get("userName") or "").strip()
            limit = int(body.get("limit") or 20)
            message = (body.get("message") or "").strip()
            if not user_name:
                self.send_json(400, {"ok": False, "error": "缺少 userName"})
                return
            try:
                doc = admin_build_push_payload(user_name, limit=limit, message=message)
                self.send_json(200, {"ok": True, "preview": True, **doc})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        # ========== 後台：發布推送到 APP ==========
        if path == "/api/admin/push/publish":
            user_name = (body.get("userName") or "").strip()
            limit = int(body.get("limit") or 20)
            message = (body.get("message") or "").strip()
            if not user_name:
                self.send_json(400, {"ok": False, "error": "缺少 userName"})
                return
            try:
                doc = admin_publish_push(user_name, limit=limit, message=message)
                self.send_json(200, {"ok": True, "published": True, **doc})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        if path == "/api/admin/push/publish_all":
            limit = int(body.get("limit") or 20)
            message = (body.get("message") or "").strip()
            try:
                result = admin_publish_push_all(limit=limit, message=message)
                self.send_json(200, result)
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
            return

        # ========== APP 個人化推薦 ==========
        if path == "/api/sheets_card/recommend":
            userName = (body.get("userName") or "").strip()
            limit = int(body.get("limit") or 20)
            movies = db_read()
            u = get_user_prefs(userName) if userName else {"like": [], "dislike": []}
            cards, _meta = build_recommend_cards(movies, u, limit=limit)
            for c in cards:
                c.pop("score", None)
                c.pop("matchReasons", None)
            self.send_json(200, cards)
            return

        # 原本舊的 POST 路由
        print(f"  POST 收到路徑: {path}")
        if path == "/analyze":
            self.handle_analyze(body)
        elif path == "/db":
            self.handle_db_add(body)
        elif path == "/config/keys":
            self.handle_save_keys(body)
        elif path == "/config/keys/add":
            self.handle_add_key(body)
        elif path == "/youtube/search":
            self.handle_youtube_search(body)
        elif path == "/youtube/info":
            self.handle_youtube_info(body)
        elif path == "/tmdb/search":
            self.handle_tmdb_search(body)
        elif path == "/tmdb/analyze":
            self.handle_tmdb_analyze(body)
        elif path == "/youtube/batch-analyze":
            self.handle_batch_analyze(body)
        elif path == "/ping":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": f"未知路徑: {path}"})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/db/"):
            movie_id = path[4:]
            row_num = db_find_row(movie_id)
            if row_num is None:
                self.send_json(404, {"ok": False, "error": "找不到此 ID"})
            else:
                db_delete_row(row_num)
                self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def handle_analyze(self, body):
        yt_url = body.get("url", "").strip()
        if not yt_url:
            self.send_json(400, {"ok": False, "error": "缺少 url"})
            return
        try:
            self.send_json(200, call_gemini_analyze(yt_url))
        except Exception as e:
            traceback.print_exc()
            self.send_json(200, {"ok": False, "error": f"分析程序錯誤: {e}"})

    def handle_db_add(self, body):
        if not body.get("title") or not body.get("ytId"):
            self.send_json(400, {"ok": False, "error": "缺少 title 或 ytId"})
            return
        try:
            row_num = None
            if body.get("id"):
                row_num = db_find_row(body["id"])
            if not row_num and body.get("ytId"):
                row_num, existing = db_find_row_by_yt_id(body["ytId"])
                if existing and not body.get("id"):
                    body["id"] = existing.get("id") or uid()
            if not body.get("id"):
                body["id"] = uid()
            normalize_movie_record(body)
            if row_num:
                db_update_row(row_num, body)
            else:
                db_append(body)
            self.send_json(200, {"ok": True, "data": body})
        except Exception as e:
            print(f"  handle_db_add 錯誤: {e}")
            traceback.print_exc()
            self.send_json(200, {"ok": False, "error": f"寫入資料庫失敗: {str(e)}"})

    def handle_save_keys(self, body):
        keys = body.get("keys", [])
        if not isinstance(keys, list) or not keys:
            self.send_json(400, {"ok": False, "error": "請提供 keys 陣列"})
            return
        keys = [k.strip() for k in keys if k.strip()]
        ok = save_gemini_keys(keys)
        self.send_json(200, {"ok": ok, "count": len(keys)} if ok else {"ok": False, "error": "儲存失敗"})

    def handle_add_key(self, body):
        incoming = body.get("keys")
        if incoming is None:
            incoming = [body.get("key", "")]
        if not isinstance(incoming, list):
            incoming = [str(incoming)]

        new_keys = []
        for key in incoming:
            key = str(key).strip()
            if key.startswith("AIza") and key not in new_keys:
                new_keys.append(key)

        if not new_keys:
            self.send_json(400, {"ok": False, "error": "請提供有效的 Gemini API Key"})
            return

        existing = [k.strip() for k in get_gemini_keys() if k.strip()]
        combined = existing[:]
        added = 0
        for key in new_keys:
            if key not in combined:
                combined.append(key)
                added += 1

        ok = save_gemini_keys(combined)
        self.send_json(200, {
            "ok": ok,
            "added": added,
            "count": len(combined),
        } if ok else {"ok": False, "error": "新增失敗"})

    def handle_youtube_search(self,body):
        query = body.get("query", "").strip()
        max_results = min(int(body.get("max_results", 12)), 50)
        page_token = body.get("page_token", "").strip()
        exclude_ids = set(body.get("exclude_ids") or [])
        if not query:
            self.send_json(400, {"ok": False, "error": "請輸入搜尋關鍵字"})
            return
        params = {
            "part": "snippet",
            "type": "video",
            "videoDuration": "short",
            "q": query,
            "maxResults": str(max_results),
            "key": YOUTUBE_API_KEY,
            "relevanceLanguage": "zh-TW",
            "regionCode": "TW",
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            
            existing_yt = {m.get("ytId") for m in db_read() if m.get("ytId")}
            results = []
            for item in data.get("items", []):
                vid_id = item.get("id", {}).get("videoId", "")
                if not vid_id or vid_id in exclude_ids:
                    continue
                snippet = item.get("snippet", {})
                pub = snippet.get("publishedAt", "")[:10]
                pub_year = pub[:4] if len(pub) >= 4 and pub[:4].isdigit() else ""
                results.append({
                    "ytId": vid_id,
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "publishedAt": pub,
                    "year": pub_year,
                    "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "inDb": vid_id in existing_yt,
                })
            
            # 直接發送所有結果
            self.send_json(200, {
                "ok": True,
                "data": results,
                "total": len(results),
                "nextPageToken": data.get("nextPageToken", ""),
            })
            return # 確保直接回傳
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            self.send_json(200, {"ok": False, "error": f"YouTube API 錯誤: {err[:200]}"})
        except Exception as e:
            self.send_json(200, {"ok": False, "error": str(e)})

    def handle_youtube_info(self, body):
        yt_id = body.get("ytId", "").strip()
        url = body.get("url", "").strip()
        if not yt_id and url:
            m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
            yt_id = m.group(1) if m else ""
        if not yt_id:
            self.send_json(400, {"ok": False, "error": "missing ytId"})
            return

        params = {
            "part": "snippet",
            "id": yt_id,
            "key": YOUTUBE_API_KEY,
        }
        api_url = f"https://www.googleapis.com/youtube/v3/videos?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            items = data.get("items", [])
            if not items:
                self.send_json(404, {"ok": False, "error": "video not found"})
                return
            snippet = items[0].get("snippet", {})
            pub = snippet.get("publishedAt", "")[:10]
            pub_year = pub[:4] if len(pub) >= 4 and pub[:4].isdigit() else ""
            self.send_json(200, {
                "ok": True,
                "ytId": yt_id,
                "title": snippet.get("title", ""),
                "cleanTitle": clean_movie_title(snippet.get("title", "")),
                "channel": snippet.get("channelTitle", ""),
                "publishedAt": pub,
                "year": pub_year,
                "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={yt_id}",
            })
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            self.send_json(200, {"ok": False, "error": f"YouTube API error: {err[:200]}"})
        except Exception as e:
            self.send_json(200, {"ok": False, "error": str(e)})

    def handle_tmdb_search(self, body):
        query = body.get("query", "").strip()
        media_type = body.get("media_type", "movie")
        if media_type not in ["movie", "tv"]:
            media_type = "movie"
        page = max(1, int(body.get("page", 1) or 1))
        year = str(body.get("year", "")).strip()
        max_results = min(int(body.get("max_results", 20) or 20), 50)
        exclude_ids = set(body.get("exclude_ids") or [])

        try:
            if query:
                params = {"query": query, "page": page, "include_adult": "false"}
                if year:
                    if media_type == "movie":
                        params["year"] = year
                    else:
                        params["first_air_date_year"] = year
                data = tmdb_request(f"/search/{media_type}", params)
            else:
                params = {
                    "page": page,
                    "include_adult": "false",
                    "sort_by": "popularity.desc",
                }
                if year:
                    if media_type == "movie":
                        params["primary_release_year"] = year
                    else:
                        params["first_air_date_year"] = year
                data = tmdb_request(f"/discover/{media_type}", params)

            existing_ids = {
                f"tmdb-{m.get('mediaType')}-{m.get('tmdbId')}"
                for m in db_read()
                if m.get("tmdbId") and m.get("mediaType")
            }
            genre_map = tmdb_genres(media_type)
            results = []
            for item in data.get("results", []):
                result = tmdb_to_result(item, media_type, genre_map, existing_ids)
                if not has_chinese_text(result.get("title", "")):
                    continue
                key = f"tmdb-{media_type}-{result['tmdbId']}"
                if key not in exclude_ids and not result["inDb"]:
                    results.append(result)
                if len(results) >= max_results:
                    break

            self.send_json(200, {
                "ok": True,
                "data": results,
                "total": data.get("total_results", len(results)),
                "page": page,
                "nextPage": page + 1 if page < data.get("total_pages", page) else None,
            })
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            self.send_json(200, {"ok": False, "error": f"TMDB API 錯誤: {err[:200]}"})
        except Exception as e:
            self.send_json(200, {"ok": False, "error": str(e)})

    def handle_tmdb_analyze(self, body):
        item = body.get("item") or {}
        if not item.get("title"):
            self.send_json(400, {"ok": False, "error": "缺少 TMDB 作品資料"})
            return
        try:
            self.send_json(200, call_gemini_tmdb(item))
        except Exception as e:
            traceback.print_exc()
            self.send_json(200, {"ok": False, "error": f"分析程序錯誤: {e}"})

    def handle_batch_analyze(self, body):
        urls = body.get("urls", [])
        if not urls:
            self.send_json(400, {"ok": False, "error": "缺少 urls"})
            return
        results = []
        for i, url_info in enumerate(urls):
            yt_url = url_info.get("url", "") or (
                f"https://www.youtube.com/watch?v={url_info.get('ytId', '')}" if url_info.get("ytId") else ""
            )
            yt_id = url_info.get("ytId", "")
            try:
                result = call_gemini_analyze(yt_url)
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            if result.get("ok"):
                p = result["data"]
                sm = p.get("scenes_main", [])
                ss = p.get("scenes_sub", [])
                entry = {
                    "id": uid(),
                    "ytId": yt_id,
                    "url": yt_url,
                    "title": clean_movie_title(url_info.get("title", "")) or url_info.get("title", "") or p.get("title", ""),
                    "desc": p.get("desc", ""),
                    "year": url_info.get("year") or p.get("year") or "",
                    "publishedAt": url_info.get("publishedAt") or "",
                    "scenesMain": sm,
                    "scenesSub": ss,
                    "scenes": sm + ss,
                    "genres": p.get("genres", []),
                    "emotions": p.get("emotions", []),
                    "atmospheres": p.get("atmospheres", []),
                }
                normalize_movie_record(entry)
                existing = db_read()
                dup = next((m for m in existing if m.get("ytId") == yt_id), None)
                if dup:
                    row = db_find_row(dup["id"])
                    if row:
                        entry["id"] = dup["id"]
                        db_update_row(row, entry)
                else:
                    db_append(entry)
                results.append({"ytId": yt_id, "ok": True, "title": entry["title"]})
            else:
                results.append({"ytId": yt_id, "ok": False, "error": result.get("error", "分析失敗")})
            if i < len(urls) - 1:
                time.sleep(2)
        ok_count = sum(1 for r in results if r.get("ok"))
        self.send_json(200, {"ok": True, "results": results, "success": ok_count, "total": len(urls)})




class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True




def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    print("=" * 52)
    print("FilmDB server starting")
    print(f"PORT  : {PORT}")
    print(f"SHEET : {SPREADSHEET_ID}")
    print(f"MODEL : {MODEL}")
    print("=" * 52)
    ensure_sheet()
    load_user_behavior_from_sheets()
    load_push_feed_from_sheets()
    load_rooms_from_sheets()
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"Server running on 0.0.0.0:{PORT}")
    server.serve_forever()




if __name__ == "__main__":
    main()
