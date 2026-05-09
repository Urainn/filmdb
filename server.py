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


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SHEETS_CREDS = os.environ.get("SHEETS_CREDS", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1sRXiN_W8oshYIZTaDza3A-B1MPgrpTmedoQx8VS9Dsw")
SHEET_NAME = os.environ.get("SHEET_NAME", "films")
CONFIG_SHEET = "config"
PORT = int(os.environ.get("PORT", 8765))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyDs2IknIRxX_H8DRGR9er_oiBsbQWoYzDw")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

MODEL = "gemini-2.5-flash"

PROMPT = """仔細看完這個電影預告片，然後只輸出一個 JSON 物件，絕對不要加任何說明文字或 markdown。
請嚴格按照以下格式，每個陣列都必須填入至少 2 個值：
{
  "title": "電影中文片名",
  "desc": "25字內的劇情簡介",
  "scenes_main": ["主要場景，只填地點名稱，如：城市、雪地、叢林、太空、海洋、沙漠、戰場、屋頂、地下室、商場、學校、森林、宮殿"],
  "scenes_sub": ["次要場景，只填地點名稱，如：室內、實驗室、走廊、監獄、停車場、醫院、車廂、辦公室"],
  "genres": ["電影類型，如：動作、愛情、科幻、懸疑、恐怖、喜劇、奇幻、歷史、動畫、驚悚"],
  "moods": ["情感氛圍，如：緊張、浪漫、感動、壯闊、孤獨、溫馨、黑暗、燒腦、熱血、悲傷"]
}
重要規則：
1. scenes_main 和 scenes_sub 只填純粹的地點名稱，不加任何形容詞
2. 每個陣列至少填 2 個值
3. 就算不確定也要根據影片畫面猜測填入"""

_token_cache = {"token": None, "expires": 0}
_token_lock = threading.Lock()
_gemini_keys = []
_key_lock = threading.Lock()
_key_index = 0
_sheet_id_cache = None


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
        for name in [SHEET_NAME, CONFIG_SHEET]:
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


def call_gemini_analyze(yt_url):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}
    payload = {
        "contents": [{
            "parts": [
                {"file_data": {"file_uri": yt_url}},
                {"text": PROMPT},
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    current_key = get_next_key()
    max_attempts = max(3, len(keys) * 2)
    for attempt in range(1, max_attempts + 1):
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent?key={current_key}"
        )
        req = urllib.request.Request(
            gemini_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = extract_json(text)
            if not result:
                return {"ok": False, "error": f"無法解析 JSON: {text[:200]}"}
            result.setdefault("title", "")
            result.setdefault("desc", "")
            result.setdefault("scenes_main", [])
            result.setdefault("scenes_sub", [])
            result.setdefault("genres", [])
            result.setdefault("moods", [])
            return {"ok": True, "data": result}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                current_key = get_next_key(failed_key=current_key)
                time.sleep(5)
                continue
            if e.code == 503 and attempt < max_attempts:
                time.sleep(8)
                continue
            return {"ok": False, "error": f"Gemini API 錯誤 {e.code}: {err[:300]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Gemini 分析重試次數已用完"}


def call_gemini_tmdb(item):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}

    media_label = "影劇" if item.get("mediaType") == "tv" else "電影"
    text_prompt = f"""請根據以下 TMDB {media_label}資料，產生和預告片分析相同格式的 JSON。
只能輸出 JSON，不要 markdown，不要說明文字。

片名：{item.get("title", "")}
類型：{", ".join(item.get("tmdbGenres", []) or [])}
日期：{item.get("publishedAt", "")}
簡介：{item.get("desc", "")}

請輸出：
{{
  "title": "中文片名",
  "desc": "25字內簡介",
  "scenes_main": ["主要場景"],
  "scenes_sub": ["次要場景"],
  "genres": ["類型"],
  "moods": ["情感氛圍"]
}}"""

    payload = {
        "contents": [{"parts": [{"text": text_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }

    current_key = get_next_key()
    max_attempts = max(3, len(keys) * 2)
    for attempt in range(1, max_attempts + 1):
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent?key={current_key}"
        )
        req = urllib.request.Request(
            gemini_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            result = extract_json(text)
            if not result:
                return {"ok": False, "error": f"無法解析 JSON: {text[:200]}"}
            result.setdefault("title", item.get("title", ""))
            result.setdefault("desc", item.get("desc", ""))
            result.setdefault("scenes_main", [])
            result.setdefault("scenes_sub", [])
            result.setdefault("genres", item.get("tmdbGenres", []))
            result.setdefault("moods", [])
            return {"ok": True, "data": result}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                current_key = get_next_key(failed_key=current_key)
                time.sleep(5)
                continue
            if e.code == 503 and attempt < max_attempts:
                time.sleep(8)
                continue
            return {"ok": False, "error": f"Gemini API 錯誤 {e.code}: {err[:300]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Gemini 分析重試次數已用完"}


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
    title = item.get("title") or item.get("name") or ""
    date = item.get("release_date") or item.get("first_air_date") or ""
    poster_path = item.get("poster_path") or ""
    backdrop_path = item.get("backdrop_path") or ""
    poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
    thumb = poster or (f"https://image.tmdb.org/t/p/w780{backdrop_path}" if backdrop_path else "")
    tmdb_id = item.get("id")
    yt_id, trailer_url = tmdb_trailer(media_type, tmdb_id)
    tmdb_key = f"tmdb-{media_type}-{tmdb_id}"
    genres = [genre_map.get(gid, "") for gid in item.get("genre_ids", [])]
    genres = [g for g in genres if g]
    return {
        "source": "tmdb",
        "mediaType": media_type,
        "tmdbId": tmdb_id,
        "ytId": yt_id or tmdb_key,
        "url": trailer_url,
        "title": title,
        "desc": item.get("overview", ""),
        "channel": "TMDB",
        "publishedAt": date,
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
        elif path == "/db":
            self.send_json(200, {"ok": True, "data": db_read()})
        elif path == "/config/keys":
            keys = get_gemini_keys()
            masked = [k[:8] + "..." + k[-4:] if len(k) > 12 else k[:4] + "..." for k in keys]
            self.send_json(200, {"ok": True, "keys": masked, "count": len(keys)})
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
        print(f"  POST 收到路徑: {path}")
        if path == "/analyze":
            self.handle_analyze()
        elif path == "/db":
            self.handle_db_add()
        elif path == "/config/keys":
            self.handle_save_keys()
        elif path == "/youtube/search":
            self.handle_youtube_search()
        elif path == "/tmdb/search":
            self.handle_tmdb_search()
        elif path == "/tmdb/analyze":
            self.handle_tmdb_analyze()
        elif path == "/youtube/batch-analyze":
            self.handle_batch_analyze()
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

    def handle_analyze(self):
        body = self.read_body()
        yt_url = body.get("url", "").strip()
        if not yt_url:
            self.send_json(400, {"ok": False, "error": "缺少 url"})
            return
        self.send_json(200, call_gemini_analyze(yt_url))

    def handle_db_add(self):
        body = self.read_body()
        if not body.get("title") or not body.get("ytId"):
            self.send_json(400, {"ok": False, "error": "缺少 title 或 ytId"})
            return
        if not body.get("id"):
            body["id"] = uid()
        try:
            row_num = db_find_row(body["id"])
            if row_num:
                db_update_row(row_num, body)
            else:
                db_append(body)
            self.send_json(200, {"ok": True, "data": body})
        except Exception as e:
            self.send_json(200, {"ok": False, "error": f"寫入資料庫失敗: {str(e)}"})

    def handle_save_keys(self):
        body = self.read_body()
        keys = body.get("keys", [])
        if not isinstance(keys, list) or not keys:
            self.send_json(400, {"ok": False, "error": "請提供 keys 陣列"})
            return
        keys = [k.strip() for k in keys if k.strip()]
        ok = save_gemini_keys(keys)
        self.send_json(200, {"ok": ok, "count": len(keys)} if ok else {"ok": False, "error": "儲存失敗"})

    def handle_youtube_search(self):
        body = self.read_body()
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
            existing = {m.get("ytId") for m in db_read()}
            results = []
            for item in data.get("items", []):
                vid_id = item.get("id", {}).get("videoId", "")
                if not vid_id:
                    continue
                snippet = item.get("snippet", {})
                results.append({
                    "ytId": vid_id,
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "publishedAt": snippet.get("publishedAt", "")[:10],
                    "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "inDb": vid_id in existing,
                })
            filtered = [r for r in results if not r["inDb"] and r["ytId"] not in exclude_ids]
            self.send_json(200, {
                "ok": True,
                "data": filtered,
                "total": len(results),
                "filtered": len(results) - len(filtered),
                "nextPageToken": data.get("nextPageToken", ""),
            })
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            self.send_json(200, {"ok": False, "error": f"YouTube API 錯誤: {err[:200]}"})
        except Exception as e:
            self.send_json(200, {"ok": False, "error": str(e)})

    def handle_tmdb_search(self):
        body = self.read_body()
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
            for item in data.get("results", [])[:max_results]:
                result = tmdb_to_result(item, media_type, genre_map, existing_ids)
                key = f"tmdb-{media_type}-{result['tmdbId']}"
                if key not in exclude_ids and not result["inDb"]:
                    results.append(result)

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

    def handle_tmdb_analyze(self):
        body = self.read_body()
        item = body.get("item") or {}
        if not item.get("title"):
            self.send_json(400, {"ok": False, "error": "缺少 TMDB 作品資料"})
            return
        self.send_json(200, call_gemini_tmdb(item))

    def handle_batch_analyze(self):
        body = self.read_body()
        urls = body.get("urls", [])
        if not urls:
            self.send_json(400, {"ok": False, "error": "缺少 urls"})
            return
        results = []
        for i, url_info in enumerate(urls):
            yt_url = url_info.get("url", "")
            yt_id = url_info.get("ytId", "")
            result = call_gemini_analyze(yt_url)
            if result.get("ok"):
                p = result["data"]
                sm = p.get("scenes_main", [])
                ss = p.get("scenes_sub", [])
                entry = {
                    "id": uid(),
                    "ytId": yt_id,
                    "url": yt_url,
                    "title": p.get("title") or url_info.get("title", ""),
                    "desc": p.get("desc", ""),
                    "scenesMain": sm,
                    "scenesSub": ss,
                    "scenes": sm + ss,
                    "genres": p.get("genres", []),
                    "moods": p.get("moods", []),
                }
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
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"Server running on 0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
