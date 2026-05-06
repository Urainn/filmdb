#!/usr/bin/env python3
"""
FilmDB 雲端伺服器 - Google Sheets 版
資料永久儲存在 Google Sheets，重新部署不會消失
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
                "iat": now
            }).encode()
        ).rstrip(b"=").decode()

        try:
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend

            private_key = serialization.load_pem_private_key(
                creds["private_key"].encode(),
                password=None,
                backend=default_backend()
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
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())

        _token_cache["token"] = token_data["access_token"]
        _token_cache["expires"] = now + token_data.get("expires_in", 3600)
        return _token_cache["token"]


SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def sheets_request(method, path, body=None):
    token = get_access_token()
    url = f"{SHEETS_BASE}/{SPREADSHEET_ID}{path}"
    print(f"  Sheets {method} {url[:90]}")

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  Sheets HTTP {e.code} 錯誤：{err[:300]}")
        raise Exception(f"Sheets API 錯誤 {e.code}：{err[:200]}")


def ensure_sheet():
    try:
        info = sheets_request("GET", "")
        names = [s["properties"]["title"] for s in info.get("sheets", [])]
        for name in [SHEET_NAME, CONFIG_SHEET]:
            if name not in names:
                sheets_request("POST", ":batchUpdate", {
                    "requests": [{"addSheet": {"properties": {"title": name}}}]
                })
                print(f"  建立工作表：{name}")
    except Exception as e:
        print(f"  ensure_sheet 錯誤：{e}")


def ensure_config_sheet():
    try:
        info = sheets_request("GET", "")
        names = [s["properties"]["title"] for s in info.get("sheets", [])]
        if CONFIG_SHEET not in names:
            sheets_request("POST", ":batchUpdate", {
                "requests": [{"addSheet": {"properties": {"title": CONFIG_SHEET}}}]
            })
    except Exception as e:
        print(f"  ensure_config_sheet 錯誤：{e}")


def get_gemini_keys():
    global _gemini_keys

    with _key_lock:
        try:
            encoded = urllib.parse.quote(f"{CONFIG_SHEET}!A:B")
            result = sheets_request("GET", f"/values/{encoded}")
            rows = result.get("values", [])
            keys = []

            for row in rows:
                if len(row) >= 2 and row[0] == "gemini_key" and row[1].strip():
                    keys.append(row[1].strip())

            if keys:
                _gemini_keys = keys
                return keys
        except Exception as e:
            print(f"  讀取 config 失敗：{e}")

        if GEMINI_API_KEY:
            return [GEMINI_API_KEY]

        return []


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
        print(f"  儲存 Gemini Keys 失敗：{e}")
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
        result = sheets_request("GET", f"/values/{encoded}")
        rows = result.get("values", [])
        records = []

        for row in rows:
            if row:
                try:
                    records.append(json.loads(row[0]))
                except Exception:
                    pass

        return records
    except Exception as e:
        print(f"  db_read 錯誤：{e}")
        return []


def db_find_row(movie_id):
    try:
        encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
        result = sheets_request("GET", f"/values/{encoded}")
        rows = result.get("values", [])

        for i, row in enumerate(rows):
            if row:
                try:
                    record = json.loads(row[0])
                    if record.get("id") == movie_id:
                        return i + 1
                except Exception:
                    pass
    except Exception as e:
        print(f"  db_find_row 錯誤：{e}")

    return None


def db_append(record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
    return sheets_request(
        "POST",
        f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
        {"values": [[json.dumps(record, ensure_ascii=False)]]}
    )


def db_update_row(row_num, record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A{row_num}")
    return sheets_request(
        "PUT",
        f"/values/{encoded}?valueInputOption=RAW",
        {"values": [[json.dumps(record, ensure_ascii
