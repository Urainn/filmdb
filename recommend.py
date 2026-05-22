import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

# 從 database.py 導入獲取所有評分的函數
from database import get_all_ratings

def get_recommendations(user_id, top_n=5):
    """
    基於協同過濾（Collaborative Filtering）的電影推薦演算法。
    
    這個函數會：
    1. 獲取所有用戶的評分數據。
    2. 建立一個「用戶-電影」矩陣。
    3. 計算用戶之間的相似度（使用餘弦相似度）。
    4. 找到與目標用戶最相似的其他用戶。
    5. 推薦這些相似用戶喜歡、但目標用戶還沒看過的電影。
    
    參數:
        user_id (str): 需要獲取推薦的用戶ID。
        top_n (int): 需要返回的推薦電影數量。
        
    返回:
        list: 一個包含推薦電影信息的列表，每個元素是一個字典。
              例如: [{'movie': '星際效應', 'score': 0.95, 'from_user': 'user_abc'}]
    """
    
    # 1. 獲取所有評分數據
    all_ratings = get_all_ratings()
    
    # 如果數據庫中沒有任何評分，則無法進行推薦
    if not all_ratings:
        print("數據庫中沒有評分數據，無法生成推薦。")
        return []

    # 2. 建立用戶-電影矩陣
    # 將評分列表轉換為 pandas DataFrame
    df = pd.DataFrame(all_ratings)
    
    # 使用 pivot_table 創建矩陣：行是用戶，列是電影，值是評分
    # fill_value=0 表示用戶沒有評分過的電影，其分數為0
    user_movie_matrix = df.pivot_table(
        index='user_id',
        columns='title',
        values='rating',
        fill_value=0
    )

    # 如果目標用戶不在矩陣中（例如，他從未評分過），則無法推薦
    if user_id not in user_movie_matrix.index:
        print(f"用戶 '{user_id}' 不在數據中，無法生成推薦。")
        return []

    # 3. 計算用戶之間的相似度
    # 使用餘弦相似度（Cosine Similarity）來衡量用戶品味的相似程度
    # 結果是一個用戶之間的相似度矩陣
    user_similarity = cosine_similarity(user_movie_matrix)
    
    # 將相似度矩陣轉換為更易於使用的 DataFrame
    similarity_df = pd.DataFrame(
        user_similarity,
        index=user_movie_matrix.index,
        columns=user_movie_matrix.index
    )

    # 4. 找到與目標用戶最相似的其他用戶
    # 獲取目標用戶與所有其他用戶的相似度分數，並按降序排列
    similar_users = similarity_df[user_id].sort_values(ascending=False)

    # 5. 生成推薦列表
    recommendations = []
    
    # 獲取目標用戶已經評分過的電影列表
    user_rated_movies = user_movie_matrix.loc[user_id]
    rated_movie_titles = user_rated_movies[user_rated_movies > 0].index.tolist()

    # 遍歷與目標用戶最相似的用戶（從最相似的開始）
    for similar_user_id, similarity_score in similar_users.items():
        # 跳過用戶自己
        if similar_user_id == user_id:
            continue

        # 獲取這個相似用戶的評分記錄
        similar_user_ratings = user_movie_matrix.loc[similar_user_id]
        
        # 遍歷相似用戶喜歡的電影
        for movie_title, rating in similar_user_ratings.items():
            # 如果相似用戶喜歡這部電影（評分>=2），並且目標用戶還沒看過
            if rating >= 2 and movie_title not in rated_movie_titles:
                # 計算推薦分數（相似度 * 評分）
                # 這個分數越高，代表推薦的電影越可靠
                rec_score = similarity_score * rating
                
                recommendations.append({
                    "movie": movie_title,
                    "score": rec_score,
                    "from_user": similar_user_id
                })
    
    # 6. 按推薦分數排序，並返回前 N 個
    # 使用 lambda 函數指定按 'score' 鍵進行排序
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    
    # 去重（防止同一部電影被多個相似用戶推薦）
    unique_recommendations = []
    seen_movies = set()
    for rec in recommendations:
        if rec['movie'] not in seen_movies:
            unique_recommendations.append(rec)
            seen_movies.add(rec['movie'])
            
    return unique_recommendations[:top_n]


