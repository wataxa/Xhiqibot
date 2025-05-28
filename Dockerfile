# Pythonの公式スリムイメージをベースにする
FROM python:3.10-slim-buster

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリを直接インストール
# --no-cache-dir はキャッシュを使わないことで、ビルド失敗時の再試行をクリーンにする
# gunicorn と discord.py は互いに依存関係が複雑な場合があるので、先にインストール
RUN pip install --no-cache-dir gunicorn discord.py==2.4.0 openai python-dotenv Flask httpx

# アプリケーションのコードをコピー
COPY . .

# Cloud Runがリッスンするポートを定義
ENV PORT 8080

# コンテナ起動時に実行するコマンド
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "--workers", "1", "xhiqibot:app"]
