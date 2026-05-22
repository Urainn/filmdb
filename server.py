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





GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDs2IknIRxX_H8DRGR9er_oiBsbQWoYzDw")
SHEETS_CREDS = os.environ.get("SHEETS_CREDS", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1sRXiN_W8oshYIZTaDza3A-B1MPgrpTmedoQx8VS9Dsw")
SHEET_NAME = os.environ.get("SHEET_NAME", "films")
CONFIG_SHEET = "config"
PORT = int(os.environ.get("PORT", 8765))
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyCMkz2uk_IcRVIoNZNBZ7wQJ6RDdL_KBjI")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "f8abc776cee1400e1fadf2874e1d8c2c")


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
  "moods": ["8到14個搜尋關鍵詞，包含情緒、氛圍、敘事母題、角色關係、社會議題或視覺風格，如：緊張、黑暗、熱血、惡趣味、娛樂化暴力、青春驚悚、身份認同、華麗資本主義、友情、反思"]
  "cast": ["演員1名稱", "演員2名稱", "演員3名稱"]  // 列表中可以包含多位演員
}
重要規則：
1. scenes_main 和 scenes_sub 只能填「觀眾看得懂的具體地點或空間」，不要填抽象世界觀
2. 禁止場景出現：未知世界、冒險市、奇幻世界、魔法世界、異世界、夢境世界、命運舞台、故事世界
3. genres 不只填片種，也要補題材與可搜尋關鍵詞，但不要亂編不存在的政治或社會議題
4. moods 可以包含情緒、氛圍、敘事母題、角色關係、時代感、視覺風格與觀眾搜尋詞
5. 每個陣列都要去重，不要重複意思太接近的詞
6. 就算不確定也要根據影片畫面與片名合理推測，但要避免太空泛的詞
7. 所有輸出都必須使用台灣繁體中文，不可以出現簡體中文"""


_token_cache = {"token": None, "expires": 0}
_token_lock = threading.Lock()
_gemini_keys = []
_key_lock = threading.Lock()
_key_index = 0
_sheet_id_cache = None

# 記憶存放使用者喜好（後端重啟前都有效）
user_behavior = {}


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




def normalize_analysis_result(result):
    for key in ["title", "desc", "scenes_main", "scenes_sub", "genres", "moods"]:
        if key in result:
            result[key] = to_traditional_text(result[key])
    return result




async def call_gemini_analyze(yt_url):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}
    
    import httpx  # ← 新增这行
    
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
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:  # ← 改用 httpx
                resp = await client.post(gemini_url, json=payload)  # ← 非同步请求
                data = resp.json()
            
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
            result = normalize_analysis_result(result)
            return {"ok": True, "data": result}
            
        except httpx.HTTPError as e:  # ← 捕获 httpx 错误
            err = e.response.text
            if e.response.status_code in (403, 429):
                current_key = get_next_key(failed_key=current_key)
                time.sleep(5)
                continue
            if e.response.status_code == 503 and attempt < max_attempts:
                time.sleep(8)
                continue
            return {"ok": False, "error": f"Gemini API 錯誤 {e.response.status_code}: {err[:300]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    return {"ok": False, "error": "Gemini 分析重試次數已用完"}





async def call_gemini_tmdb(item):
    keys = get_gemini_keys()
    if not keys:
        return {"ok": False, "error": "未設定 Gemini API Key"}
    
    import httpx  # ← 新增这行
    
    trailer_url = (item.get("url") or "").strip()
    if trailer_url and ("youtube.com" in trailer_url or "youtu.be" in trailer_url):
        video_result = await call_gemini_analyze(trailer_url)  # ← 等待分析完成
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
  "moods": ["8到14個搜尋關鍵詞，包含情緒、氛圍、敘事母題、角色關係、社會議題或視覺風格"],
  "cast": ["演員1名稱", "演員2名稱", "演員3名稱"]  // 列表中可以包含多位演員
}}

重要規則：
1. scenes_main 和 scenes_sub 只能填具體地點或空間，不要填抽象世界觀
2. 禁止場景出現：未知世界、冒險市、奇幻世界、魔法世界、異世界、夢境世界、命運舞台、故事世界
3. genres 不只填片種，也要補題材與可搜尋關鍵詞
4. moods 可以包含情緒、氛圍、敘事母題、角色關係、時代感、視覺風格與觀眾搜尋詞
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

    current_key = get_next_key()
    max_attempts = max(3, len(keys) * 2)
    
    for attempt in range(1, max_attempts + 1):
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODEL}:generateContent?key={current_key}"
        )
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:  # ← 改用 httpx
                resp = await client.post(gemini_url, json=payload)  # ← 非同步请求
                data = resp.json()
            
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
            result = normalize_analysis_result(result)
            return {"ok": True, "data": result}
            
        except httpx.HTTPError as e:  # ← 捕获 httpx 错误
            err = e.response.text
            if e.response.status_code in (403, 429):
                current_key = get_next_key(failed_key=current_key)
                time.sleep(5)
                continue
            if e.response.status_code == 503 and attempt < max_attempts:
                time.sleep(8)
                continue
            return {"ok": False, "error": f"Gemini API 錯誤 {e.response.status_code}: {err[:300]}"}
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
    title = to_traditional_text(item.get("title") or item.get("name") or "")
    date = item.get("release_date") or item.get("first_air_date") or ""
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

        # APP 專用：全部電影卡片
        elif path == "/api/sheets_card":
            movies = db_read()
            sheets_card = []
            for m in movies:
                card = {
                    "id": m.get("id", ""),
                    "title": m.get("title", ""),
                    "poster": m.get("poster") or m.get("thumb", ""),
                    "scenes": (m.get("scenesMain") or []) + (m.get("scenesSub") or []),
                    "genres": m.get("genres", []),
                    "moods": m.get("moods", []),
                    "actors": m.get("cast", ""),
                    "url": m.get("url", ""),
                    "ytId": m.get("ytId", "")
                }
                sheets_card.append(card)
            self.send_json(200, sheets_card)

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
        body = self.read_body()

        # ========== APP 喜歡 ==========
        if path == "/api/user/like":
            userName = body.get("userName", "")
            movieId = body.get("movieId", "")
            if not userName or not movieId:
                self.send_json(400, {"ok": False})
                return
            if userName not in user_behavior:
                user_behavior[userName] = {"like": [], "dislike": []}
            u = user_behavior[userName]
            if movieId not in u["like"]:
                u["like"].append(movieId)
            if movieId in u["dislike"]:
                u["dislike"].remove(movieId)
            self.send_json(200, {"ok": True})
            return

        # ========== APP 不喜歡 ==========
        if path == "/api/user/dislike":
            userName = body.get("userName", "")
            movieId = body.get("movieId", "")
            if not userName or not movieId:
                self.send_json(400, {"ok": False})
                return
            if userName not in user_behavior:
                user_behavior[userName] = {"like": [], "dislike": []}
            u = user_behavior[userName]
            if movieId not in u["dislike"]:
                u["dislike"].append(movieId)
            if movieId in u["like"]:
                u["like"].remove(movieId)
            self.send_json(200, {"ok": True})
            return

        # ========== APP 個人化推薦 ==========
        if path == "/api/sheets_card/recommend":
            userName = body.get("userName", "")
            limit = int(body.get("limit", 20))
            if not userName or userName not in user_behavior:
                allCards = []
                movies = db_read()
                for m in movies:
                    allCards.append({
                        "id": m.get("id", ""),
                        "title": m.get("title", ""),
                        "poster": m.get("poster") or m.get("thumb", ""),
                        "scenes": (m.get("scenesMain") or []) + (m.get("scenesSub") or []),
                        "genres": m.get("genres", []),
                        "moods": m.get("moods", []),
                        "actors": m.get("cast", ""),
                        "url": m.get("url", ""),
                        "ytId": m.get("ytId", "")
                    })
                self.send_json(200, allCards[:limit])
                return

            u = user_behavior[userName]
            movies = db_read()

            def getScore(m):
                score = 0
                if m["id"] in u["like"]:
                    score += 50
                if m["id"] in u["dislike"]:
                    score -= 100
                for g in m.get("genres", []):
                    if any(gg in u["like"] for gg in g):
                        score += 3
                for s in m.get("scenes", []):
                    if any(ss in u["like"] for ss in s):
                        score += 2
                return score

            listCards = []
            for m in movies:
                card = {
                    "id": m.get("id", ""),
                    "title": m.get("title", ""),
                    "poster": m.get("poster") or m.get("thumb", ""),
                    "scenes": (m.get("scenesMain") or []) + (m.get("scenesSub") or []),
                    "genres": m.get("genres", []),
                    "moods": m.get("moods", []),
                    "actors": m.get("cast", ""),
                    "url": m.get("url", ""),
                    "ytId": m.get("ytId", ""),
                    "score": getScore(m)
                }
                if card["score"] > -50:
                    listCards.append(card)

            listCards.sort(key=lambda x: x["score"], reverse=True)
            res = listCards[:limit]
            for r in res:
                r.pop("score", None)
            self.send_json(200, res)
            return

        # 原本舊的 POST 路由
        print(f"  POST 收到路徑: {path}")
        if path == "/analyze":
            self.handle_analyze()
        elif path == "/db":
            self.handle_db_add()
        elif path == "/config/keys":
            self.handle_save_keys()
        elif path == "/config/keys/add":
            self.handle_add_key()
        elif path == "/youtube/search":
            self.handle_youtube_search(body)
        elif path == "/youtube/info":
            self.handle_youtube_info()
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

    async def handle_analyze(self):
        body = self.read_body()
        yt_url = body.get("url", "").strip()
        if not yt_url:
            self.send_json(400, {"ok": False, "error": "缺少 url"})
            return
        self.send_json(200, await call_gemini_analyze(yt_url))

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

    def handle_add_key(self):
        body = self.read_body()
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
            
            results = []
            for item in data.get("items", []):
                vid_id = item.get("id", {}).get("videoId", "")
                if not vid_id: continue
                snippet = item.get("snippet", {})
                results.append({
                    "ytId": vid_id,
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "publishedAt": snippet.get("publishedAt", "")[:10],
                    "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "inDb": False, # 先暫時設為 False ，確保能顯示
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

    def handle_youtube_info(self):
        body = self.read_body()
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
            self.send_json(200, {
                "ok": True,
                "ytId": yt_id,
                "title": snippet.get("title", ""),
                "cleanTitle": clean_movie_title(snippet.get("title", "")),
                "channel": snippet.get("channelTitle", ""),
                "publishedAt": snippet.get("publishedAt", "")[:10],
                "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={yt_id}",
            })
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            self.send_json(200, {"ok": False, "error": f"YouTube API error: {err[:200]}"})
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

    async def handle_tmdb_analyze(self):
        body = self.read_body()
        item = body.get("item") or {}
        if not item.get("title"):
            self.send_json(400, {"ok": False, "error": "缺少 TMDB 作品資料"})
            return
        self.send_json(200, await call_gemini_tmdb(item))

    async def handle_batch_analyze(self):
        body = self.read_body()
        urls = body.get("urls", [])
        if not urls:
            self.send_json(400, {"ok": False, "error": "缺少 urls"})
            return
        results = []
        for i, url_info in enumerate(urls):
            yt_url = url_info.get("url", "")
            yt_id = url_info.get("ytId", "")
            result = await call_gemini_analyze(yt_url)
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
