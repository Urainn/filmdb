import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import init_db, add_rating, get_all_movies, get_user_ratings, get_stats, get_all_ratings, add_movie
from recommend import get_recommendations

# 創建 Flask 應用實例
app = Flask(__name__)

# 應用啟動時初始化資料庫
# 這會創建 movies 和 ratings 表（如果它們不存在）
init_db()

# --- 初始化一些示例電影數據 (僅在首次運行時添加) ---
# 檢查資料庫中是否已有電影，如果沒有，則添加幾部示例電影
if not get_all_movies():
    print("數據庫中沒有電影，正在添加示例數據...")
    add_movie("星際效應", "科幻", 2014)
    add_movie("盜夢空間", "科幻", 2010)
    add_movie("黑暗騎士", "動作", 2008)
    add_movie("阿甘正傳", "劇情", 1994)
    add_movie("楚門的世界", "劇情", 1998)
    add_movie("千與千尋", "動畫", 2001)
    add_movie("你的名字", "動畫", 2016)
    add_movie("鈴芽之旅", "動畫", 2022)
    add_movie("捍衛戰士：獨行俠", "動作", 2022)
    add_movie("媽的多重宇宙", "科幻/喜劇", 2022)
    print("示例數據添加完成！")


# ════════════════════════════════════════════════════════════════════════════════
# 前台路由 (用戶介面)
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """
    首頁路由：顯示所有電影，讓用戶進行喜歡/不喜歡的評分。
    """
    movies = get_all_movies()
    return render_template("index.html", movies=movies)

@app.route("/rate", methods=["POST"])
def rate_movie():
    """
    處理評分提交的路由。
    接收用戶ID、電影ID和評分（1=不喜歡, 2=喜歡）。
    """
    user_id = request.form.get("user_id", "anonymous")
    movie_id = int(request.form.get("movie_id"))
    rating = int(request.form.get("rating"))

    add_rating(user_id, movie_id, rating)
    
    # 評分後重定向回首頁
    return redirect(url_for("index"))

# ════════════════════════════════════════════════════════════════════════════════
# 後台路由 (管理面板)
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/admin")
def admin():
    """
    後台管理面板首頁。
    顯示數據統計和所有評分記錄。
    """
    stats = get_stats()
    all_ratings = get_all_ratings()
    return render_template("admin.html", stats=stats, ratings=all_ratings)

@app.route("/admin/recommendations")
def admin_recommendations():
    """
    後台推薦API：根據指定的用戶ID，返回推薦的電影列表。
    """
    user_id = request.args.get("user_id", "anonymous")
    recs = get_recommendations(user_id, top_n=10)
    return jsonify(recs)

# ════════════════════════════════════════════════════════════════════════════════
# API 路由 (供前端JavaScript調用)
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/api/ratings/<user_id>")
def api_user_ratings(user_id):
    """
    獲取特定用戶的所有評分記錄。
    """
    ratings = get_user_ratings(user_id)
    return jsonify([dict(r) for r in ratings])

@app.route("/api/recommend/<user_id>")
def api_recommend(user_id):
    """
    為特定用戶生成推薦電影列表。
    """
    recs = get_recommendations(user_id)
    return jsonify(recs)


# ════════════════════════════════════════════════════════════════════════════════
# 啟動應用
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 監聽所有網絡接口的8765端口，允許外部訪問
    app.run(host="0.0.0.0", port=8765, debug=True)

