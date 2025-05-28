# ベースイメージとして公式の Python を使用
FROM python:3.11-slim

# 作業ディレクトリを作成
WORKDIR /app

# 依存関係のインストール用にファイルをコピー
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# bot ファイルと persona.txt をコピー
COPY xhiqibot.py ./
COPY persona.txt ./

# Discord bot を起動
CMD ["python", "xhiqibot.py"]
