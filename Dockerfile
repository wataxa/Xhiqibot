# Pythonの公式イメージを使用
FROM python:3.10-slim-buster

# ワーキングディレクトリを設定
WORKDIR /app

# 依存関係をインストール
# discord.py と openai を直接指定し、aiohttp も追加
# Cloud Runの推奨事項に従い、システムの依存関係は極力減らす
RUN pip install --no-cache-dir \
    discord.py \
    openai \
    gunicorn \
    flask \
    aiohttp  # <--- この行を追加しました！

# アプリケーションのコードをコンテナにコピー
COPY . .

# アプリケーションがリッスンするポートを定義
ENV PORT 8080

# Gunicornを使ってFlaskアプリとDiscord Botを起動
# gunicorn は xhiqibot.py 内の `app` オブジェクトをWSGIアプリケーションとして起動する
# その後、xhiqibot.py の中で Discord Bot を別スレッドで起動する
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 xhiqibot:app
