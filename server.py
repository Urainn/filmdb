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

# ========== 繁體轉換核心（已完整保留） ==========
PHRASE_TW = {
    "军事基地": "軍事基地", "休憩室": "休息室", "颁奖台": "頒獎台", "办公室": "辦公室",
    "实验室": "實驗室", "停车场": "停車場", "地下车库": "地下車庫", "购物中心": "購物中心",
    "商场": "商場", "战场": "戰場", "战舰": "戰艦", "飞船": "飛船", "太空船": "太空船",
    "医院": "醫院", "学校": "學校", "监狱": "監獄", "房间": "房間", "隧道": "隧道",
    "间谍": "間諜", "侦探": "偵探", "悬疑": "懸疑", "惊悚": "驚悚", "动作": "動作",
    "剧情": "劇情", "喜剧": "喜劇", "爱情": "愛情", "科幻": "科幻", "奇幻": "奇幻",
    "战争": "戰爭", "灾难": "災難", "历史": "歷史", "动画": "動畫", "纪录": "紀錄",
    "综艺": "綜藝", "冒险": "冒險", "犯罪": "犯罪", "紧张": "緊張", "壮阔": "壯闊",
    "热血": "熱血", "黑暗": "黑暗", "危险": "危險", "温馨": "溫馨", "烧脑": "燒腦",
    "悲伤": "悲傷", "感动": "感動", "浪漫": "浪漫",
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
    "馆": "館", "厂": "廠", "广": "廣", "废": "廢", "旧": "舊",
})

def to_traditional(v):
    if isinstance(v, str):
        for s, t in PHRASE_TW.items():
            v = v.replace(s, t)
        v = v.translate(CHAR_TW)
        return v
    if isinstance(v, list):
        return [to_traditional(i) for i in v]
    if isinstance(v, dict):
        return {k: to_traditional(v[k]) for k in v}
    return v

# ========== 設定 ==========
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyB7kF9sD2xQ8wE5rT1yU3iO7pA4sG6hJ0kL")
SHEETS_CREDS = os.environ.get("SHEETS_CREDS", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1sRXiN_W8oshYIZTaDza3A-B1MPgrpTmedoQx8VS9Dsw")
CONFIG_SHEET = "config"
PORT = int(os.environ.get("PORT", 8765))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyCnX2z8xL4Xg0QdF7hJk9mP2sR5tU8vY1a")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "2dca21d2886540666435864f88656876")

MODEL = "gemini-2.5-flash"

PROMPT = """仔細看完這個電影預告片，然後只輸出一個 JSON 物件，絕對不要加任何說明文字或 markdown。
這是一個給展覽觀眾搜尋電影用的資料庫，請產生「好搜尋、可策展、可聯想」的標籤。
不要只給很少的類型詞；請補足題材、情緒、敘事母題、視覺質感、社會議題、角色關係與觀眾可能會搜尋的關鍵詞。

請嚴格按照以下格式：
{
  "title": "電影中文片名",
  "desc": "25字內的劇情簡介",
  "scenes_main": ["3到6個主要場景，只填具體地點名稱，如：城市街道、住宅、商場、森林、命案現場、監獄、太空、荒地、密閉空間"],
  "scenes_sub": ["3到6個次要場景，只填具體地點名稱，如：室內、教室、醫院、車廂、辦公室、酒吧、走廊、地下室、心理諮商所"],
  "genres": ["6到10個類型與題材關鍵詞，如：喜劇、恐怖、驚悚、科幻、犯罪、懸疑、青春、荒唐、超自然、女性職場"],
  "moods": ["8到14個搜尋關鍵詞，包含情緒、氛圍、敘事母題、角色關係、社會議題或視覺風格，如：緊張、黑暗、熱血、惡趣味、娛樂化暴力、青春驚悚、身份認同、華麗資本主義、友情、反思"],
  "cast": ["演員1名稱", "演員2名稱", "演員3名稱"]
}
重要規則：
1. scenes_main 和 scenes_sub 只能填「觀眾看得懂的具體地點或空間」，不要填抽象世界觀
2. 禁止場景出現：未知世界、冒險市、奇幻世界、魔法世界、異世界、夢境世界、命運舞台、故事世界
3. genres 不只片種，也要補題材與可搜尋關鍵詞，但不要亂編不存在的政治或社會議題
4. moods 可以包含情緒、氛圍、敘事母題、角色關係、社會議題或視覺風格
5. 每個陣列都要去重，不要重複意思太接近的詞
6. 就算不確定也要根據影片畫面與片名合理推測，但避免太空泛的詞
7. 所有輸出必須使用台灣繁體中文，不可以使用簡體中文"""

_token_cache = {"token": None, "expires": 0}
_token_lock = threading.Lock()
_gemini_keys = []
_key_lock = threading.Lock()
_key_index = 0
_sheet_id_cache = None

user_behavior = {}

def get_access_token():
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
            return _token_cache["token"]
        if not SHEETS_CREDS:
            raise Exception("未設定 SHEETS_CREDS 環境變數")

        creds = json.loads(SHEETS_CREDS)
        now = int(time.time())
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + 3600,
            "iat": now
        }).encode()).rstrip(b"=").decode()

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend
            private_key = serialization.load_pem_private_key(
                creds["private_key"].encode(),
                password=None,
                backend=default_backend()
            )
            signing_input = f"{header}.{payload}".encode()
            signature = base64.urlsafe_b64encode(private_key.sign(signing_input, padding.PKCS1v15(), None)).rstrip(b"=").decode()
        except ImportError:
            raise Exception("請安裝套件：pip install cryptography")

        jwt = f"{header}.{payload}.{signature}"
        data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=30) as res:
            token_data = json.load(res)
        _token_cache["token"] = token_data["access_token"]
        _token_cache["expires"] = now + token_data["expires_in"]
        return token_data["access_token"]

SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

def sheets_request(method, path, body=None):
    url = f"{SHEETS_BASE}/{SPREADSHEET_ID}{path}"
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json"
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        print(f"Sheets API {e.code}: {e.read().decode()[:300]}")
        raise Exception(f"Sheets API 錯誤 {e.code}")

# ===================== 【萬用版讀取：掃描所有工作表】 =====================
def db_read():
    try:
        # 先取得試算表裡所有分頁
        spreadsheet_info = sheets_request("GET", "")
        all_records = []
        for sheet in spreadsheet_info.get("sheets", []):
            sheet_name = sheet["properties"]["title"]
            # 讀取每個分頁的 A 欄
            res = sheets_request("GET", f"/values/{sheet_name}!A:A")
            rows = res.get("values", [])
            for row in rows:
                if not row or not row[0].strip():
                    continue
                try:
                    data = json.loads(row[0].strip())
                    if isinstance(data, dict):
                        # 自動補 id
                        if not data.get("id"):
                            data["id"] = data.get("ytId", f"auto_id_{len(all_records)}")
                        all_records.append(data)
                except Exception as e:
                    continue
        return all_records
    except Exception as e:
        print("讀取資料錯誤:", e)
        return []

def db_find_row(movie_id):
    try:
        rows = sheets_request("GET", f"/values/films!A:A")["values"]
        for i, row in enumerate(rows):
            if not row: continue
            try:
                if json.loads(row[0]).get("id") == movie_id:
                    return i + 1
            except:
                continue
    except:
        pass
    return None

def db_append(record):
    return sheets_request("POST", f"/values/films!A1:append?valueInputOption=RAW", {
        "values": [[json.dumps(record, ensure_ascii=False)]]
    })

def db_update_row(row_num, record):
    return sheets_request("PUT", f"/values/films!A{row_num}?valueInputOption=RAW", {
        "values": [[json.dumps(record, ensure_ascii=False)]]
    })

def get_sheet_id():
    global _sheet_id_cache
    if _sheet_id_cache is not None:
        return _sheet_id_cache
    info = sheets_request("GET", "")
    for s in info.get("sheets", []):
        if s["properties"]["title"] == "films":
            _sheet_id_cache = s["properties"]["sheetId"]
            return _sheet_id_cache
    return 0

def db_delete_row(row_num):
    return sheets_request("POST", ":batchUpdate", {
        "requests": [{"deleteDimension": {
            "range": {
                "sheetId": get_sheet_id(),
                "dimension": "ROWS",
                "startRowIndex": row_num - 1,
                "endRowIndex": row_num
            }
        }}]
    })

def uid():
    import random, string
    return "u" + str(int(time.time())) + "".join(random.choices(string.ascii_lowercase, k=4))

def clean_movie_title(t):
    t = t.strip() if t else ""
    if not t: return ""
    m = re.findall(r"【([^】]+)", t) or re.findall(r"《([^》]+)", t)
    if m: t = m[-1]
    t = re.sub(r"電影|預告|官方|HD|完整版|中文|预告|Official|Trailer|Clip", "", t, flags=re.I)
    return t.strip()

def extract_json(text):
    text = re.sub(r"```json|```", "", text).strip()
    try: return json.loads(text)
    except: pass
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try: return json.loads(text[s:e+1])
        except: pass
    return None

def normalize_result(r):
    for k in ["title","desc","scenes_main","scenes_sub","genres","moods","cast"]:
        if k in r: r[k] = to_traditional(r[k])
    return r

def call_gemini_analyze(url):
    keys = get_gemini_keys()
    if not keys: return {"ok":False,"error":"no key"}
    for _ in range(min(3, len(keys)*2)):
        key = get_next_key()
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
                data=json.dumps({"contents":[{"parts":[{"fileData":{"mimeType":"video/*","url":url}},{"text":PROMPT}]}]}).encode(),
                headers={"Content-Type":"application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as res:
                data = json.load(res)
            t = data["candidates"][0]["content"]["parts"][0]["text"]
            r = extract_json(t)
            if not r: return {"ok":False,"error":"no json"}
            return {"ok":True,"data":normalize_result(r)}
        except:
            continue
    return {"ok":False,"error":"failed"}

def call_gemini_tmdb(item):
    url = item.get("url")
    if url and "youtu" in url:
        res = call_gemini_analyze(url)
        if res["ok"]:
            if item.get("title"): res["data"]["title"] = item["title"]
            return res
    keys = get_gemini_keys()
    if not keys: return {"ok":False,"error":"no key"}
    prompt = f"""片名：{item.get('title','')}
類型：{','.join(item.get('tmdbGenres',[]))}
簡介：{item.get('desc','')}
輸出嚴格JSON格式"""
    for _ in range(min(3, len(keys)*2)):
        key = get_next_key()
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
                data=json.dumps({"contents":[{"parts":[{"text":PROMPT+"\n"+prompt}]}]}).encode(),
                headers={"Content-Type":"application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as res:
                data = json.load(res)
            t = data["candidates"][0]["content"]["parts"][0]["text"]
            r = extract_json(t)
            if not r: return {"ok":False,"error":"no json"}
            return {"ok":True,"data":normalize_result(r)}
        except:
            continue
    return {"ok":False,"error":"failed"}

def tmdb_req(path, **params):
    params["api_key"] = TMDB_API_KEY
    params["language"] = "zh-TW"
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"https://api.themoviedb.org/3{path}?{q}", timeout=20) as res:
        return json.load(res)

def tmdb_trailer(mid, t):
    try:
        res = tmdb_req(f"/{t}/{mid}/videos")
        for v in res.get("results",[]):
            if v.get("site")=="YouTube" and v.get("type")in["Trailer","Teaser"]:
                return v.get("key"), f"https://www.youtube.com/watch?v={v.get('key')}"
    except:
        pass
    return "", ""

# ===================== 主伺服器 =====================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, f,*a): pass
    def cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
    def json(self, code, data):
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    def html(self, code, data):
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(data.encode())
    def read_body(self):
        l = int(self.headers.get("Content-Length",0))
        if l<=0: return {}
        try: return json.loads(self.rfile.read(l))
        except: return {}
    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/ping":
            self.json(200,{"ok":True})
        elif p == "/api/sheets_card":
            movies = db_read()
            out = []
            for m in movies:
                out.append({
                    "id": m.get("id",""),
                    "title": m.get("title",""),
                    "poster": m.get("poster") or m.get("thumb",""),
                    "scenes": (m.get("scenesMain",[]) + m.get("scenesSub",[])),
                    "genres": m.get("genres",[]),
                    "moods": m.get("moods",[]),
                    "actors": m.get("cast",[]),
                    "url": m.get("url",""),
                    "ytId": m.get("ytId","")
                })
            self.json(200, out)
        elif p == "/db":
            self.json(200,{"ok":True,"data":db_read()})
        elif p in ["/","/index.html"]:
            if os.path.exists("index.html"):
                with open("index.html","r",encoding="utf-8") as f:
                    self.html(200, f.read())
            else:
                self.json(404,{"ok":False,"error":"no index"})
        else:
            self.json(404,{"ok":False})
    def do_POST(self):
        p = self.path.split("?")[0]
        b = self.read_body()
        if p == "/api/user/like":
            u, mid = b.get("userName"), b.get("movieId")
            if not u or not mid: return self.json(400,{"ok":False})
            if u not in user_behavior: user_behavior[u]={"like":[],"dislike":[]}
            if mid not in user_behavior[u]["like"]: user_behavior[u]["like"].append(mid)
            if mid in user_behavior[u]["dislike"]: user_behavior[u]["dislike"].remove(mid)
            return self.json(200,{"ok":True})
        if p == "/api/user/dislike":
            u, mid = b.get("userName"), b.get("movieId")
            if not u or not mid: return self.json(400,{"ok":False})
            if u not in user_behavior: user_behavior[u]={"like":[],"dislike":[]}
            if mid not in user_behavior[u]["dislike"]: user_behavior[u]["dislike"].append(mid)
            if mid in user_behavior[u]["like"]: user_behavior[u]["like"].remove(mid)
            return self.json(200,{"ok":True})
        if p == "/api/sheets_card/recommend":
            u, lim = b.get("userName"), int(b.get("limit",20))
            all_cards = []
            for m in db_read():
                all_cards.append({
                    "id":m.get("id",""), "title":m.get("title",""),
                    "poster":m.get("poster")or m.get("thumb",""),
                    "scenes":(m.get("scenesMain",[]) + m.get("scenesSub",[])),
                    "genres":m.get("genres",[]), "moods":m.get("moods",[]),
                    "actors":m.get("cast",[]), "url":m.get("url",""), "ytId":m.get("ytId","")
                })
            if not u or u not in user_behavior:
                return self.json(200, all_cards[:lim])
            rec = []
            for c in all_cards:
                score = 0
                if c["id"] in user_behavior[u]["like"]: score += 50
                if c["id"] in user_behavior[u]["dislike"]: score -= 100
                rec.append((-score, c))
            rec.sort()
            self.json(200, [r[1] for r in rec][:lim])
            return
        if p == "/analyze":
            u = b.get("url","").strip()
            if not u: return self.json(400,{"ok":False,"error":"no url"})
            self.json(200, call_gemini_analyze(u))
            return
        if p == "/db":
            if not b.get("title") or not b.get("ytId"):
                return self.json(200,{"ok":False,"msg":"缺少標題或ID"})
            if not b.get("id"): b["id"] = b["ytId"]
            try:
                row = db_find_row(b["id"])
                if row: db_update_row(row, b)
                else: db_append(b)
                self.json(200,{"ok":True,"msg":"成功"})
            except Exception as e:
                self.json(200,{"ok":False,"msg":str(e)})
            return
        if p == "/youtube/search":
            q, lim = b.get("query","").strip(), min(int(b.get("max_results",12)),50)
            if not q: return self.json(400,{"ok":False,"error":"no query"})
            params = {"part":"snippet","q":q,"maxResults":lim,"key":YOUTUBE_API_KEY,"type":"video","videoDuration":"short","regionCode":"TW","relevanceLanguage":"zh-TW"}
            pt = urllib.parse.urlencode(params)
            req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/search?{pt}", method="GET")
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.load(res)
            exist = {m.get("ytId") for m in db_read()}
            out = []
            for it in data.get("items",[]):
                vid = it["id"]["videoId"]
                s = it["snippet"]
                out.append({
                    "ytId":vid, "title":s["title"], "channel":s["channelTitle"],
                    "publishedAt":s["publishedAt"][:10],
                    "thumb":s["thumbnails"]["medium"]["url"],
                    "url":f"https://www.youtube.com/watch?v={vid}",
                    "inDb":vid in exist
                })
            self.json(200,{"ok":True,"data":out})
            return
        if p == "/youtube/info":
            yid = b.get("ytId","").strip()
            if not yid:
                u = b.get("url","")
                m = re.search(r"youtu\.be/([^?&#]+)|youtube\.com.*v=([^?&#]+)", u)
                yid = m.group(1) or m.group(2) if m else ""
            if not yid: return self.json(400,{"ok":False})
            req = urllib.request.Request(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={yid}&key={YOUTUBE_API_KEY}")
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.load(res)
            if not data["items"]: return self.json(404,{"ok":False})
            s = data["items"][0]["snippet"]
            self.json(200,{
                "ok":True, "ytId":yid, "title":s["title"],
                "cleanTitle":clean_movie_title(s["title"]),
                "channel":s["channelTitle"], "publishedAt":s["publishedAt"][:10],
                "thumb":s["thumbnails"]["medium"]["url"],
                "url":f"https://www.youtube.com/watch?v={yid}"
            })
            return
        if p == "/tmdb/search":
            q, t, pg = b.get("query",""), b.get("media_type","movie"), max(1,int(b.get("page",1)))
            if t not in ["movie","tv"]: t="movie"
            try:
                if q:
                    data = tmdb_req(f"/search/{t}", query=q, page=pg, include_adult=False)
                else:
                    data = tmdb_req(f"/discover/{t}", page=pg, include_adult=False)
            except:
                return self.json(200,{"ok":False})
            exist = {m.get("ytId") for m in db_read()}
            out = []
            for it in data.get("results",[])[:min(int(b.get("max_results",20)),50)]:
                mid = it["id"]
                yid, yurl = tmdb_trailer(mid, t)
                out.append({
                    "source":"tmdb", "mediaType":t, "tmdbId":mid,
                    "ytId":yid or f"tmdb-{t}-{mid}", "url":yurl,
                    "title":to_traditional(it.get("title")or it.get("name","")),
                    "desc":to_traditional(it.get("overview","")),
                    "channel":"TMDB", "publishedAt":it.get("release_date")or it.get("first_air_date",""),
                    "thumb":f"https://image.tmdb.org/t/p/w500{it.get('poster_path','')}" if it.get("poster_path") else "",
                    "poster":f"https://image.tmdb.org/t/p/w500{it.get('backdrop_path','')}" if it.get("backdrop_path") else "",
                    "tmdbGenres":[], "inDb":(yid or f"tmdb-{t}-{mid}") in exist
                })
            self.json(200,{"ok":True,"data":out,"page":data.get("page",1),"total_pages":data.get("total_pages",1)})
            return
        if p == "/tmdb/analyze":
            self.json(200, call_gemini_tmdb(b))
            return
        self.json(404,{"ok":False})
    def do_DELETE(self):
        p = self.path.split("?")[0]
        if p.startswith("/db/"):
            mid = p[4:]
            row = db_find_row(mid)
            if not row: return self.json(404,{"ok":False})
            db_delete_row(row)
            self.json(200,{"ok":True})
            return
        self.json(404,{"ok":False})

class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def main():
    ensure_sheet()
    s = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"✅ FilmDB 啟動成功 port:{PORT}")
    s.serve_forever()

if __name__ == "__main__":
    main()
