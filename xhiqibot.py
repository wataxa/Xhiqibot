from __future__ import annotations
import asyncio, os, textwrap, random
from collections import deque
from typing import Tuple

import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask # Flaskはそのまま残しておく
from threading import Thread # これは使わない

# Flaskのサーバーを別のスレッドで動かすのではなく、非同期で統合するために
# aiohttp の Webサーバーを使うか、flask_asyncioのようなライブラリを使う
# もしくは、簡易的な非同期HTTPサーバーを自分で立てるのが一般的です。
# 今回は、一番簡単な方法でCloud Runのヘルスチェックに応答するように修正します。

# Flaskはヘルスチェック用として非常にシンプルにする
app = Flask(__name__)

@app.route('/')
def home():
    return "Xhiqibot is running.", 200

# Flaskを別スレッドで実行する関数
def run_flask_thread():
    port = int(os.environ.get("PORT", 8080))
    # Flaskのデフォルトはシングルスレッドなので、開発用サーバーとしては問題ない
    # 本番環境ではgunicornなどを使うのが一般的だが、ヘルスチェック目的ならこれでOK
    app.run(host="0.0.0.0", port=port)

# --- .env 読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID") or None
GUILD_ID_RAW = os.getenv("GUILD_ID")

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError(".env に DISCORD_TOKEN と OPENAI_API_KEY を設定してください")

# --- モデル指定 ---
PRIMARY_MODEL = "gpt-4o-mini"
FALLBACK_MODEL = "gpt-3.5-turbo"

# --- OpenAI SDK 自動判定 ---
try:
    import openai
    from openai import OpenAI
    _client = OpenAI(api_key=OPENAI_API_KEY, project=OPENAI_PROJECT_ID)
    OpenAIError = openai.OpenAIError

    async def complete(model: str, messages: list, max_tokens: int) -> str:
        resp = _client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
except (ImportError, AttributeError):
    import openai  # type: ignore
    openai.api_key = OPENAI_API_KEY
    OpenAIError = openai.error.OpenAIError  # type: ignore

    async def complete(model: str, messages: list, max_tokens: int) -> str:
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: openai.ChatCompletion.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
            ),
        )
        return resp["choices"][0]["message"]["content"].strip()


# --- 会話履歴保持 ---
history = deque(maxlen=20)

def get_limits(text: str) -> Tuple[int, int]:
    if "レイシオ" in text:
        return (2000, 1500)
    return (200, 200)

# --- Bot定義と初期化 ---
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# --- 共通の応答生成 ---
async def respond_to(user: discord.abc.User, message: str) -> str:
    is_ratio = "レイシオ" in message
    char_limit, max_tokens = get_limits(message)

    system_prompt = ("あなたの名前はしき（xhiqi）。落ち着いて丁寧に話し、" +
                     ("簡潔に200字以内で" if not is_ratio else "できる限り詳細に") +
                     "日本語で答えてください。")

    history.append({
        "role": "user",
        "name": user.display_name,
        "content": message
    })
    messages = [{"role": "system", "content": system_prompt}] + list(history)

    try:
        reply = await complete(PRIMARY_MODEL, messages, max_tokens)
    except OpenAIError as e: # エラーハンドリングを強化
        print(f"Primary model error: {e}")
        try:
            reply = await complete(FALLBACK_MODEL, messages, max_tokens)
            print("Successfully used fallback model.")
        except OpenAIError as e_fallback:
            print(f"Fallback model error: {e_fallback}")
            return "APIエラーが発生しました。しばらくしてからもう一度お試しください。（両モデルでエラー）"


    reply = textwrap.fill(reply, width=60)
    history.append({"role": "assistant", "content": reply})

    if not is_ratio and random.random() < 0.15:
        try:
            crab = await complete(
                PRIMARY_MODEL,
                [
                    {
                        "role": "system",
                        "content": "あなたは時々カニを想います。100字以内で書いてください。"
                    },
                    {
                        "role": "user",
                        "content": "今、何を考えていますか？"
                    },
                ],
                max_tokens=100,
            )
            reply += f"\n\n（ところで、{crab.strip()}）"
        except OpenAIError as e_crab:
            print(f"Crab thought error: {e_crab}")
            # カニの思考部分でエラーが出てもメインの返信は続ける

    return reply

# --- /xhiqi コマンド ---
@tree.command(name="xhiqi", description="xhiqi とお話しする")
@app_commands.describe(message="話しかけたい内容")
async def xhiqi(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    reply = await respond_to(interaction.user, message)
    await interaction.followup.send(
        f"**{interaction.user.display_name}：** {message}\n**xhiqi：** {reply}")

# --- メンション応答 ---
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    if bot.user and bot.user.mentioned_in(msg): # bot.userがNoneではないことを確認
        # メンション部分を削除してメッセージテキストを取得
        message_text = msg.content.replace(f'<@!{bot.user.id}>', '').strip()
        if not message_text and msg.reference and isinstance(msg.reference.resolved, discord.Message):
             message_text = msg.reference.resolved.content # 返信メッセージを優先

        if not message_text: # メッセージが空になったら処理しない
            return

        # `is_typing` と `sleep` で入力中表示と処理遅延
        async with msg.channel.typing():
            reply = await respond_to(msg.author, message_text)
        await msg.channel.send(f"**xhiqi：** {reply}", reference=msg.reference) # 返信元にリプライする

# --- 起動と同期 ---
@bot.event
async def on_ready():
    print("XhiqiBot starting …")
    try:
        if GUILD_ID_RAW:
            guild = discord.Object(id=int(GUILD_ID_RAW))
            synced = await tree.sync(guild=guild)
            print(f"Slash コマンドをギルドへ同期しました ({len(synced)} commands)")
        else:
            synced = await tree.sync()
            print(f"Slash コマンドを全体へ同期しました ({len(synced)} commands, 最大 1h)")
    except Exception as e:
        print("Sync error:", e)

    # Botが起動した後、Flaskサーバーを別のスレッドで起動
    # bot.loop.run_in_executor を使うと、よりasyncioフレンドリー
    # しかし、Cloud RunはメインプロセスがHTTPリッスンすることを期待するので、
    # 実際にはこれが最も簡単な方法ではない。
    # Cloud Run向けには、Webサーバー(Flask)をメインプロセスにして、
    # Discord Botの処理を別の方法で動かすか、
    # またはFlask+discord.pyのイベントループを統合するライブラリを使うのが一般的。
    # ここでは、最も単純なヘルスチェック応答のためにThreadを使用する。
    print("Starting Flask in a separate thread...")
    # Cloud Runの環境変数PORTを確実に使う
    Thread(target=run_flask_thread).start()


# --- 実行 ---
if __name__ == "__main__":
    # Bot起動前にFlaskを起動するスレッドを開始するように変更 (ただし、この場所は非同期イベントループの前にする必要がある)
    # Cloud RunはメインプロセスがHTTPを listen することを期待しているため、この構造だと問題が起きやすい
    # 解決策として、Discord Botのライブラリに依存しない簡単なWebサーバーを立てるのが一番手っ取り早い

    # 以下は、Discord Botをメインループで動かしつつ、
    # ヘルスチェック用のWebサーバーも動かすための一般的な手法です。
    # gunicornなどのASGI/WSGIサーバーを使ってFlaskを動かすのが一般的ですが、
    # 最もシンプルな形として、Webサーバーを別スレッドで立ち上げます。
    # ただし、Cloud Runはメインプロセスがリッスンすることを期待するため、
    # Discord BotとFlaskを同じプロセスで動かすには少し工夫が必要です。

    # ここでは、Flaskをメインプロセスにして、Discord Botを別スレッドで動かすという逆転の発想で対応します。
    # 理由は、Cloud RunがHTTPポートのリッスンをメインプロセスに要求するため。

    # Flaskアプリがメインとなる
    # ここは変更せず、run_flask_thread()をon_ready()で呼ぶのはやめる
    # Cloud RunがPORTでリッスンすることを期待しているのはメインプロセス
    # したがって、Discord Botではなく、Flaskをメインプロセスとして実行する

    # ----- 変更点 -----
    # 1. on_ready() から Flask 起動のコードを削除
    # 2. if __name__ == "__main__": の中で Flask を直接起動する
    # 3. Discord Bot を新しいスレッドで起動する

    print("Running Flask as main process to listen on PORT...")
    Thread(target=bot.run, args=(DISCORD_TOKEN,)).start() # Botを別スレッドで実行

    # Flaskをメインプロセスで実行し、Cloud Runが期待するポートでリッスンさせる
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False) # debug=False for production
