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
