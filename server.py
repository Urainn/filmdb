#!/usr/bin/env python3
"""
FilmDB 雲端伺服器 — Google Sheets 版
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

# ── 環境變數設定 ──────────────────────────────────────────────────
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")  # 初始 Key（可在網頁設定覆蓋）
SHEETS_CREDS    = os.environ.get("SHEETS_CREDS", "")
SPREADSHEET_ID  = os.environ.get("SPREADSHEET_ID", "1sRXiN_W8oshYIZTaDza3A-B1MPgrpTmedoQx8VS9Dsw")
SHEET_NAME      = os.environ.get("SHEET_NAME", "films")
CONFIG_SHEET    = "config"   # 設定存在這個工作表
PORT            = int(os.environ.get("PORT", 8765))
# ─────────────────────────────────────────────────────────────────

# 執行時的 Key 列表（從 Sheets config 讀取，優先於環境變數）
_gemini_keys = []
_key_lock = threading.Lock()

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
1. scenes_main 和 scenes_sub 只填純粹的地點名稱，不加任何形容詞（例如只寫「商場」不寫「廢棄商場」，只寫「空間」不寫「詭異黃色空間」）
2. 每個陣列至少填 2 個值
3. 就算不確定也要根據影片畫面猜測填入"""

# ── Google Sheets OAuth ───────────────────────────────────────────
_token_cache = {"token": None, "expires": 0}
_token_lock = threading.Lock()

def get_access_token():
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
            return _token_cache["token"]

        creds = json.loads(SHEETS_CREDS)
        now = int(time.time())

        # 建立 JWT
        header = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b'=').decode()
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + 3600,
            "iat": now
        }).encode()).rstrip(b'=').decode()

        # 用 RSA 簽名
        import hashlib, hmac
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
            sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        except ImportError:
            raise Exception("需要安裝 cryptography 套件")

        jwt_token = f"{header}.{payload}.{sig_b64}"

        # 換取 access token
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt_token
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_data = json.loads(resp.read())

        _token_cache["token"] = token_data["access_token"]
        _token_cache["expires"] = now + token_data.get("expires_in", 3600)
        return _token_cache["token"]

# ── Config 管理 ──────────────────────────────────────────────────
def get_gemini_keys():
    """從 Sheets config 取得 Key 列表，若無則用環境變數"""
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
            print(f"  ⚠ 讀取 config 失敗：{e}")
        # fallback 到環境變數
        if GEMINI_API_KEY:
            return [GEMINI_API_KEY]
        return []

def save_gemini_keys(keys):
    """把 Key 列表存到 Sheets config"""
    try:
        ensure_config_sheet()
        # 先清空舊的 gemini_key 行
        all_rows = sheets_request("GET", f"/values/{urllib.parse.quote(CONFIG_SHEET+'!A:B')}").get("values", [])
        # 找出非 gemini_key 的行
        other_rows = [r for r in all_rows if not (r and r[0] == "gemini_key")]
        # 加入新的 Keys
        new_rows = other_rows + [["gemini_key", k] for k in keys if k.strip()]
        # 清空再寫入
        sheets_request("DELETE", f"/values/{urllib.parse.quote(CONFIG_SHEET+'!A:B')}:clear")
        if new_rows:
            sheets_request("PUT", f"/values/{urllib.parse.quote(CONFIG_SHEET+'!A1')}?valueInputOption=RAW", {"values": new_rows})
        global _gemini_keys
        with _key_lock:
            _gemini_keys = [k for k in keys if k.strip()]
        print(f"  ✓ 已儲存 {len(_gemini_keys)} 組 Gemini Key")
        return True
    except Exception as e:
        print(f"  ✗ 儲存 Key 失敗：{e}")
        return False

def ensure_config_sheet():
    try:
        info = sheets_request("GET", "")
        sheets = [s["properties"]["title"] for s in info.get("sheets", [])]
        if CONFIG_SHEET not in sheets:
            sheets_request("POST", ":batchUpdate", {
                "requests": [{"addSheet": {"properties": {"title": CONFIG_SHEET}}}]
            })
    except Exception:
        pass

# ── Google Sheets 操作 ────────────────────────────────────────────
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

def sheets_request(method, path, body=None):
    token = get_access_token()
    url = f"{SHEETS_BASE}/{SPREADSHEET_ID}{path}"
    print(f"  📡 Sheets {method} {url[:80]}")
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')
        print(f"  ✗ Sheets HTTP {e.code} 錯誤：{err[:300]}")
        raise Exception(f"Sheets API 錯誤 {e.code}：{err[:200]}")

def ensure_sheet():
    """確保工作表存在，沒有就建立"""
    try:
        info = sheets_request("GET", "")
        sheets = [s["properties"]["title"] for s in info.get("sheets", [])]
        for name in [SHEET_NAME, CONFIG_SHEET]:
            if name not in sheets:
                sheets_request("POST", ":batchUpdate", {
                    "requests": [{"addSheet": {"properties": {"title": name}}}]
                })
                print(f"  ✓ 建立工作表：{name}")
    except Exception as e:
        print(f"  ⚠ ensure_sheet 錯誤：{e}")

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
        print(f"  ✗ db_read 錯誤：{e}")
        return []

def db_find_row(movie_id):
    """找到某個 id 在第幾行（1-based）"""
    try:
        encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
        result = sheets_request("GET", f"/values/{encoded}")
        rows = result.get("values", [])
        for i, row in enumerate(rows):
            if row:
                try:
                    record = json.loads(row[0])
                    if record.get("id") == movie_id:
                        return i + 1  # 1-based
                except Exception:
                    pass
    except Exception as e:
        print(f"  ✗ db_find_row 錯誤：{e}")
    return None

def db_append(record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A:A")
    result = sheets_request("POST", f"/values/{encoded}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS", {
        "values": [[json.dumps(record, ensure_ascii=False)]]
    })
    print(f"  📝 Sheets append 回應：{result}")
    return result

def db_update_row(row_num, record):
    encoded = urllib.parse.quote(f"{SHEET_NAME}!A{row_num}")
    sheets_request("PUT", f"/values/{encoded}?valueInputOption=RAW", {
        "values": [[json.dumps(record, ensure_ascii=False)]]
    })

def db_delete_row(row_num):
    sheets_request("POST", ":batchUpdate", {
        "requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId": get_sheet_id(),
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex": row_num
                }
            }
        }]
    })

_sheet_id_cache = None
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

def uid():
    import random, string
    return 'u' + str(int(time.time())) + ''.join(random.choices(string.ascii_lowercase, k=4))

# ── JSON 解析 ─────────────────────────────────────────────────────
def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
    return None

# ── HTTP Handler ──────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  {format % args}")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(code)
            self.cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def send_html(self, html):
        body = html.encode('utf-8')
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.cors()
            self.end_headers()
        except Exception:
            pass

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == "/ping":
            self.send_json(200, {"ok": True, "model": MODEL})
        elif path == "/db":
            self.send_json(200, {"ok": True, "data": db_read()})
        elif path == "/config/keys":
            keys = get_gemini_keys()
            # 回傳遮罩後的 Key（只顯示前8碼）
            masked = [k[:8] + "..." + k[-4:] if len(k) > 12 else k[:4]+"..." for k in keys]
            self.send_json(200, {"ok": True, "keys": masked, "count": len(keys)})

        elif path == "/" or path == "/index.html":
            if os.path.exists("index.html"):
                with open("index.html", 'r', encoding='utf-8') as f:
                    self.send_html(f.read())
            else:
                self.send_json(404, {"error": "index.html 不存在"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split('?')[0]
        print(f"  POST 收到路徑：{path}")
        if path == "/analyze":
            self.handle_analyze()
        elif path == "/db":
            self.handle_db_add()
        elif path == "/config/keys":
            self.handle_save_keys()
        elif path == "/ping":
            self.send_json(200, {"ok": True})
        else:
            print(f"  ⚠ 未知 POST 路徑：{path}")
            self.send_json(404, {"ok": False, "error": f"路徑不存在：{path}"})

    def do_DELETE(self):
        path = self.path.split('?')[0]
        if path.startswith("/db/"):
            movie_id = path[4:]
            row_num = db_find_row(movie_id)
            if row_num is None:
                self.send_json(404, {"ok": False, "error": "找不到此 ID"})
            else:
                db_delete_row(row_num)
                print(f"  🗑 刪除電影 ID：{movie_id}")
                self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def handle_save_keys(self):
        body = self.read_body()
        keys = body.get("keys", [])
        if not isinstance(keys, list) or not keys:
            self.send_json(400, {"ok": False, "error": "請提供 keys 陣列"})
            return
        # 過濾空白
        keys = [k.strip() for k in keys if k.strip()]
        ok = save_gemini_keys(keys)
        if ok:
            self.send_json(200, {"ok": True, "count": len(keys)})
        else:
            self.send_json(200, {"ok": False, "error": "儲存失敗"})

    def handle_db_add(self):
        import sys
        body = self.read_body()
        print(f"  📥 handle_db_add 收到：{body.get('title')}", flush=True)
        if not body.get('title') or not body.get('ytId'):
            self.send_json(400, {"ok": False, "error": "缺少必要欄位"})
            return
        if not body.get('id'):
            body['id'] = uid()

        try:
            row_num = db_find_row(body['id'])
            if row_num:
                db_update_row(row_num, body)
                print(f"  ✏️  更新電影：{body.get('title')}")
            else:
                result = db_append(body)
                print(f"  ✅ 新增電影：{body.get('title')} | 回應：{str(result)[:100]}")
            self.send_json(200, {"ok": True, "data": body})
        except Exception as e:
            print(f"  ✗ 寫入 Sheets 失敗：{e}")
            self.send_json(200, {"ok": False, "error": f"寫入資料庫失敗：{str(e)}"})

    def handle_analyze(self):
        body = self.read_body()
        yt_url = body.get("url", "").strip()
        if not yt_url:
            self.send_json(400, {"ok": False, "error": "缺少 url 參數"})
            return

        print(f"  → 分析影片：{yt_url}")
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [
                {"file_data": {"file_uri": yt_url}},
                {"text": PROMPT}
            ]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json"
            }
        }

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            req = urllib.request.Request(
                gemini_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read().decode('utf-8')
                data = json.loads(raw)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"  ← Gemini 回傳：\n{text}\n---")
                result = extract_json(text)
                if not result:
                    raise Exception(f"無法解析 JSON：{text[:200]}")
                result.setdefault("title", "")
                result.setdefault("desc", "")
                result.setdefault("scenes_main", [])
                result.setdefault("scenes_sub", [])
                result.setdefault("genres", [])
                result.setdefault("moods", [])
                print(f"  ✓ 完成：{result.get('title')} | {result.get('genres')} | {result.get('scenes_main')}")
                self.send_json(200, {"ok": True, "data": result})
                return
            except urllib.error.HTTPError as e:
                err = e.read().decode('utf-8', errors='replace')
                if e.code == 503 and attempt < max_retries:
                    wait = 5 * attempt
                    print(f"  ⚠ 503，等 {wait} 秒重試（{attempt}/{max_retries}）...")
                    time.sleep(wait)
                else:
                    print(f"  ✗ Gemini 錯誤 {e.code}：{err[:200]}")
                    self.send_json(200, {"ok": False, "error": f"Gemini API 錯誤 {e.code}：{err[:300]}"})
                    return
            except Exception as e:
                print(f"  ✗ 錯誤：{e}")
                self.send_json(200, {"ok": False, "error": str(e)})
                return

class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def main():
    import sys
    # 強制 stdout 不緩衝，確保 Render Logs 能看到
    sys.stdout.reconfigure(line_buffering=True)
    print()
    print("=" * 52)
    print("  FilmDB 雲端伺服器（Google Sheets 版）")
    print("=" * 52)
    print(f"  PORT  : {PORT}")
    print(f"  綁定  : 0.0.0.0:{PORT}")
    print(f"  SHEET : {SPREADSHEET_ID}")
    print(f"  Model : {MODEL}")
    print("=" * 52)

    if not SHEETS_CREDS:
        print("  ✗ 缺少 SHEETS_CREDS 環境變數！")
        return
    if not GEMINI_API_KEY:
        print("  ✗ 缺少 GEMINI_API_KEY 環境變數！")
        return

    ensure_sheet()
    ensure_config_sheet()
    keys = get_gemini_keys()
    print(f"  ✓ Google Sheets 連線成功")
    print(f"  ✓ Gemini Keys：{len(keys)} 組")
    print()

    print(f"  正在啟動伺服器於 0.0.0.0:{PORT}...")
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    try:
        print(f"  ✓ 伺服器已啟動，等待請求...")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  伺服器已停止")
        server.server_close()

if __name__ == "__main__":
    main()
