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
