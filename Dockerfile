# Pythonの公式イメージを使用
FROM python:3.10-slim-buster

# ワーキングディレクトリを設定
WORKDIR /app

# 依存関係をインストール
RUN pip install --no-cache-dir \
    discord.py \
    openai \
    gunicorn \
    flask \
    aiohttp

# アプリケーションのコードをコンテナにコピー
COPY . .

# ここにデバッグ用のコマンドを追加
# ビルドプロセス中に /app ディレクトリのファイルリストを出力します。
RUN echo "--- Listing /app contents ---"
RUN ls -lR /app
RUN echo "--- End of /app contents ---"

# アプリケーションがリッスンするポートを定義
ENV PORT 8080

# Gunicornを使ってFlaskアプリとDiscord Botを起動
# gunicorn は xhiqibot.py 内の `app` オブジェクトをWSGIアプリケーションとして起動する
# その後、xhiqibot.py の中で Discord Bot を別プロセスで起動する
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 xhiqibot:app
