import sqlite3
import os

# 資料庫檔案名稱
DB_NAME = "movies.db"

def get_db():
    """
    獲取資料庫連接。
    設置 row_factory 為 sqlite3.Row，這樣可以通過列名訪問數據（如 row['title']）。
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    初始化資料庫，創建所需的表結構。
    如果表已經存在，則不會重複創建。
    """
    conn = get_db()
    
    # 創建電影表 (movies)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            genre TEXT,
            year INTEGER,
            poster TEXT
        )
    ''')
    
    # 創建評分表 (ratings)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            movie_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,  -- 1=不喜歡, 2=喜歡
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("資料庫初始化完成。")

def add_movie(title, genre, year, poster=""):
    """
    向資料庫中添加一部新電影。
    
    參數:
        title (str): 電影標題
        genre (str): 電影類型
        year (int): 上映年份
        poster (str): 海報URL (可選)
    """
    conn = get_db()
    conn.execute(
        "INSERT INTO movies (title, genre, year, poster) VALUES (?, ?, ?, ?)",
        (title, genre, year, poster)
    )
    conn.commit()
    conn.close()

def add_rating(user_id, movie_id, rating):
    """
    記錄用戶對電影的評分。
    如果用戶已經評分過，則更新評分；否則添加新記錄。
    
    參數:
        user_id (str): 用戶ID
        movie_id (int): 電影ID
        rating (int): 評分 (1 或 2)
    """
    conn = get_db()
    
    # 檢查是否已存在該用戶對該電影的評分
    existing = conn.execute(
        "SELECT id FROM ratings WHERE user_id=? AND movie_id=?",
        (user_id, movie_id)
    ).fetchone()

    if existing:
        # 如果存在，則更新評分
        conn.execute(
            "UPDATE ratings SET rating=? WHERE user_id=? AND movie_id=?",
            (rating, user_id, movie_id)
        )
    else:
        # 如果不存在，則插入新記錄
        conn.execute(
            "INSERT INTO ratings (user_id, movie_id, rating) VALUES (?, ?, ?)",
            (user_id, movie_id, rating)
        )
    
    conn.commit()
    conn.close()

def get_all_movies():
    """
    獲取資料庫中所有電影的列表。
    
    返回:
        list: 包含所有電影信息的列表，每個元素是一個 sqlite3.Row 對象。
    """
    conn = get_db()
    movies = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
    conn.close()
    return movies

def get_user_ratings(user_id):
    """
    獲取特定用戶的所有評分記錄，並關聯電影信息。
    
    參數:
        user_id (str): 用戶ID
    
    返回:
        list: 包含該用戶所有評分記錄的列表。
    """
    conn = get_db()
    ratings = conn.execute('''
        SELECT r.movie_id, r.rating, m.title, m.genre
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC
    ''', (user_id,)).fetchall()
    conn.close()
    return ratings

def get_all_ratings():
    """
    獲取資料庫中所有的評分記錄，並關聯電影信息。
    主要用於後台管理和推薦演算法。
    
    返回:
        list: 包含所有評分記錄的列表。
    """
    conn = get_db()
    ratings = conn.execute('''
        SELECT r.user_id, r.movie_id, r.rating, m.title, m.genre
        FROM ratings r
        JOIN movies m ON r.movie_id = m.id
    ''').fetchall()
    conn.close()
    return ratings

def get_stats():
    """
    獲取資料庫的統計數據。
    
    返回:
        dict: 包含總電影數、總評分數、喜歡數、不喜歡數的字典。
    """
    conn = get_db()
    total_movies = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    total_ratings = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
    total_likes = conn.execute("SELECT COUNT(*) FROM ratings WHERE rating=2").fetchone()[0]
    total_dislikes = conn.execute("SELECT COUNT(*) FROM ratings WHERE rating=1").fetchone()[0]
    conn.close()
    
    return {
        "total_movies": total_movies,
        "total_ratings": total_ratings,
        "total_likes": total_likes,
        "total_dislikes": total_dislikes
    }
