# Pythonの公式スリムイメージをベースにする
FROM python:3.10-slim-buster

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# requirements.txt をコピー
COPY requirements.txt .

# python-dotenv を最初に強制的にインストール (キャッシュを無効化)
RUN pip install --no-cache-dir python-dotenv

# その後、requirements.txt の残りの依存関係をインストール
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコピー
COPY . .

# Cloud Runがリッスンするポートを定義
ENV PORT 8080

# コンテナ起動時に実行するコマンド
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "--workers", "1", "xhiqibot:app"]
