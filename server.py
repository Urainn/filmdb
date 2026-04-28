#!/usr/bin/env python3
"""
FilmDB 雲端伺服器
- 處理 Gemini API 分析
- 讀寫共用 JSON 資料庫
- 所有人連同一個網址即可共用
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.request
import urllib.error
import json
import re
import os
import time
import threading

# ── 設定（Render 上用環境變數，本地用預設值）────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "在這裡填入你的 Gemini Key")
PORT = int(os.environ.get("PORT", 8765))
DB_FILE = os.environ.get("DB_FILE", "film-db.json")
# ────────────────────────────────────────────────────────────────

MODEL = "gemini-2.5-flash"

PROMPT = """仔細看完這個電影預告片，然後只輸出一個 JSON 物件，絕對不要加任何說明文字或 markdown。

請嚴格按照以下格式，每個陣列都必須填入至少 2 個值：
{
  "title": "電影中文片名",
  "desc": "25字內的劇情簡介",
  "scenes_main": ["從預告片畫面判斷的主要場景，如：城市街道、雪地、叢林、太空、海洋、沙漠、戰場、屋頂、地下室"],
  "scenes_sub": ["次要場景，如：室內、實驗室、學校、監獄、宮殿、停車場、醫院"],
  "genres": ["電影類型，如：動作、愛情、科幻、懸疑、恐怖、喜劇、奇幻、歷史、動畫、驚悚"],
  "moods": ["情感氛圍，如：緊張、浪漫、感動、壯闊、孤獨、溫馨、黑暗、燒腦、熱血、悲傷"]
}

重要：就算不確定也要根據影片畫面猜測填入，scenes_main、scenes_sub、genres、moods 每個都至少要有 2 個值。"""

# 資料庫讀寫鎖（防止多人同時寫入衝突）
db_lock = threading.Lock()

# ── 資料庫操作 ────────────────────────────────────────────────────
def db_read():
    with db_lock:
        if not os.path.exists(DB_FILE):
            return []
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

def db_write(data):
    with db_lock:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

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
        # 健康檢查
        if self.path == "/ping":
            self.send_json(200, {"ok": True, "model": MODEL})

        # 讀取全部電影
        elif self.path == "/db":
            self.send_json(200, {"ok": True, "data": db_read()})

        # 提供前端 HTML
        elif self.path == "/" or self.path == "/index.html":
            if os.path.exists("index.html"):
                with open("index.html", 'r', encoding='utf-8') as f:
                    self.send_html(f.read())
            else:
                self.send_json(404, {"error": "index.html 不存在"})

        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        # Gemini 分析影片
        if self.path == "/analyze":
            self.handle_analyze()

        # 新增電影
        elif self.path == "/db":
            self.handle_db_add()

        else:
            self.send_json(404, {"ok": False, "error": "路徑不存在"})

    def do_DELETE(self):
        # 刪除電影 /db/<id>
        if self.path.startswith("/db/"):
            movie_id = self.path[4:]
            data = db_read()
            new_data = [m for m in data if m.get('id') != movie_id]
            if len(new_data) == len(data):
                self.send_json(404, {"ok": False, "error": "找不到此 ID"})
            else:
                db_write(new_data)
                print(f"  🗑 刪除電影：{movie_id}")
                self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})

    def handle_db_add(self):
        body = self.read_body()
        if not body.get('title') or not body.get('ytId'):
            self.send_json(400, {"ok": False, "error": "缺少必要欄位"})
            return
        if not body.get('id'):
            body['id'] = uid()
        data = db_read()
        # 如果是更新（id 已存在）
        existing = next((i for i, m in enumerate(data) if m.get('id') == body['id']), None)
        if existing is not None:
            data[existing] = body
            print(f"  ✏️  更新電影：{body.get('title')}")
        else:
            data.append(body)
            print(f"  ✅ 新增電影：{body.get('title')}")
        db_write(data)
        self.send_json(200, {"ok": True, "data": body})

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
    print()
    print("=" * 52)
    print("  FilmDB 雲端伺服器")
    print("=" * 52)
    print(f"  PORT  : {PORT}")
    print(f"  DB    : {DB_FILE}")
    print(f"  Key   : {GEMINI_API_KEY[:12]}...")
    print(f"  Model : {MODEL}")
    print("=" * 52)
    print()
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  伺服器已停止")
        server.server_close()

if __name__ == "__main__":
    main()
