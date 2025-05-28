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

# ここに、もし os.py があれば強制的に削除するコマンドを追加します。
# -L os.py はシンボリックリンクであるか、-f os.py は通常のファイルであるかを確認し、
# どちらかであれば削除を実行します。
# これにより、見えない os.py の問題を回避します。
RUN if [ -L os.py ] || [ -f os.py ]; then echo "Deleting os.py found in /app..."; rm -f os.py; else echo "os.py not found in /app, skipping deletion."; fi

# デバッグ用のファイルリストコマンドは残しておきます（削除後にどうなったかを確認するため）
RUN echo "--- Listing /app contents AFTER DELETION ATTEMPT ---"
RUN ls -lR /app
RUN echo "--- End of /app contents ---"

# アプリケーションがリッスンするポートを定義
ENV PORT 8080

# Gunicornを使ってFlaskアプリとDiscord Botを起動
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 xhiqibot:app
