# Pythonの公式スリムイメージをベースにする
FROM python:3.10-slim-buster

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# requirements.txt をコピーして依存関係をインストール
# これを先に実行することで、requirements.txt が変更されない限り、
# ビルドキャッシュが利用され、ビルド時間を短縮できる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコピー
COPY . .

# Cloud Runがリッスンするポートを定義
ENV PORT 8080

# コンテナ起動時に実行するコマンド
# Gunicornを使ってFlaskアプリケーションを起動し、
# Discord Botもそのワーカープロセス内で別スレッドとして起動される
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "--workers", "1", "xhiqibot:app"]
