from __future__ import annotations
import asyncio
import os
import random
import sys
from collections import deque
from threading import Thread
from typing import Tuple

import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask

# --- .env 読み込み ---
load_dotenv()

# 必須環境変数のチェック
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not DISCORD_TOKEN or not OPENAI_API_KEY:
    print("エラー: DISCORD_TOKEN および OPENAI_API_KEY を .env ファイルに設定してください。", file=sys.stderr)
    sys.exit(1) # プログラムを終了させる

OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID") or None
GUILD_ID_RAW = os.getenv("GUILD_ID") # 特定のギルドに同期する場合

# --- OpenAI SDK 初期化 ---
try:
    from openai import OpenAI
    # SDK v1.x の書き方
    openai_client = OpenAI(api_key=OPENAI_API_KEY, project=OPENAI_PROJECT_ID)
    OpenAIError = Exception # v1.xではopenai.OpenAIErrorが基底クラスではないので汎用的なExceptionに
                            # より厳密には openai.APIStatusError などを使う

    async def complete(model: str, messages: list, max_tokens: int) -> str:
        resp = await asyncio.to_thread(
            openai_client.chat.completions.create, # 同期メソッドを非同期で実行
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
except ImportError:
    # v0.x 系のフォールバック (もし存在すれば)
    import openai # type: ignore
    openai.api_key = OPENAI_API_KEY
    openai.project = OPENAI_PROJECT_ID # v0.xでのproject指定はサポートされていない可能性あり
    OpenAIError = openai.error.OpenAIError # type: ignore

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
print(f"[OpenAI SDK] {('v1.x' if 'openai_client' in locals() else 'v0.x')} detected")


# --- モデル指定 ---
PRIMARY_MODEL = "gpt-4o-mini"
FALLBACK_MODEL = "gpt-3.5-turbo"

# --- 会話履歴保持 ---
# messagesのロールは "user", "assistant", "system"
# 名前は "name" フィールドで指定 (role="user"のみ)
history = deque(maxlen=20)

def get_limits(text: str) -> Tuple[int, int]:
    """メッセージ内容に応じて返答の文字数と最大トークン数を設定"""
    if "レイシオ" in text:
        return (2000, 1500) # レイシオの場合、最大2000文字、1500トークン
    return (200, 200) # 通常は最大200文字、200トークン

# --- Bot定義と初期化 ---
intents = discord.Intents.default()
intents.message_content = True # メッセージの内容を読み取るためのインテント
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# --- 共通の応答生成関数 ---
async def generate_response(user_display_name: str, message_content: str) -> str:
    """
    OpenAI APIを呼び出して応答を生成する
    """
    char_limit, max_tokens = get_limits(message_content)

    system_prompt = (
        "あなたの名前はしき（xhiqi）。"
        "粛やかで丁寧な口調で応答してください。"
        f"{char_limit}文字以内で簡潔に日本語で答えてください。"
        "ただし「レイシオ」という単語が含まれる場合は、できる限り詳細に答えてください。"
    )

    # ユーザーのメッセージを履歴に追加
    history.append({
        "role": "user",
        "name": user_display_name,
        "content": message_content
    })
    
    # APIに送るメッセージリストを構築 (システムプロンプト + 履歴)
    messages_for_api = [{"role": "system", "content": system_prompt}] + list(history)

    try:
        # プライマリモデルで応答を試行
        reply = await complete(PRIMARY_MODEL, messages_for_api, max_tokens)
    except OpenAIError as e:
        print(f"Primary model ({PRIMARY_MODEL}) error: {e}", file=sys.stderr)
        try:
            # プライマリモデルが失敗した場合、フォールバックモデルを試行
            reply = await complete(FALLBACK_MODEL, messages_for_api, max_tokens)
            print(f"Successfully used fallback model ({FALLBACK_MODEL}).")
        except OpenAIError as e_fallback:
            print(f"Fallback model ({FALLBACK_MODEL}) error: {e_fallback}", file=sys.stderr)
            return "APIエラーが発生しました。しばらくしてからもう一度お試しください。"

    # AIの返答を履歴に追加
    history.append({"role": "assistant", "content": reply})

    # 低確率でカニに関する思考を追加
    if "レイシオ" not in message_content and random.random() < 0.15:
        try:
            crab_thought = await complete(
                PRIMARY_MODEL, # カニ思考もメインモデルで
                [
                    {"role": "system", "content": "あなたは時々カニを想います。100字以内で書いてください。"},
                    {"role": "user", "content": "今、何を考えていますか？"},
                ],
                max_tokens=100,
            )
            reply += f"\n\n（ところで、{crab_thought.strip()}）"
        except OpenAIError as e_crab:
            print(f"Crab thought generation error: {e_crab}", file=sys.stderr)
            # カニの思考でエラーが出ても、メインの返信はそのまま続行

    return reply

# --- Discord Botイベントとコマンド ---

# Botがオンラインになった時の処理
@bot.event
async def on_ready():
    print(f"XhiqiBot starting… Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        if GUILD_ID_RAW:
            # 特定のギルドにスラッシュコマンドを同期
            guild = discord.Object(id=int(GUILD_ID_RAW))
            synced = await tree.sync(guild=guild)
            print(f"Slash コマンドをギルドに同期しました ({len(synced)} commands)")
        else:
            # 全てのギルドにスラッシュコマンドを同期 (最大1時間かかる場合あり)
            synced = await tree.sync()
            print(f"Slash コマンドを全体に同期しました ({len(synced)} commands, 最大 1h)")
    except Exception as e:
        print(f"Sync error: {e}", file=sys.stderr)

# /xhiqi スラッシュコマンド
@tree.command(name="xhiqi", description="xhiqi とお話しする")
@app_commands.describe(message="話しかけたい内容")
async def xhiqi(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True) # Botが考えていることを表示
    reply = await generate_response(interaction.user.display_name, message)
    await interaction.followup.send(
        f"**{interaction.user.display_name}：** {message}\n**xhiqi：** {reply}")

# メンションに対する応答
@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot: # Bot自身のメッセージは無視
        return

    # Botへのメンションが含まれているか確認
    if bot.user and bot.user.mentioned_in(msg):
        # メンション部分をメッセージから削除して、純粋なメッセージ内容を取得
        # `@BotName メッセージ` => `メッセージ`
        # 返信 (Reply) の場合は、返信元のメッセージを取得
        message_content = msg.content.replace(f'<@!{bot.user.id}>', '').strip()
        if msg.reference and isinstance(msg.reference.resolved, discord.Message):
            # 返信の場合は、返信元のメッセージ内容を優先
            message_content = msg.reference.resolved.content
        
        if not message_content: # メッセージ内容が空なら処理しない
            return

        async with msg.channel.typing(): # Botが入力中...と表示
            reply = await generate_response(msg.author.display_name, message_content)
        
        # 返信元にリプライする形式でメッセージを送信
        await msg.channel.send(f"**xhiqi：** {reply}", reference=msg.reference)

# --- Flask Webサーバーの設定 (Cloud Runのヘルスチェック用) ---
app = Flask(__name__)

@app.route('/')
def home():
    """Cloud Runのヘルスチェックに応答するエンドポイント"""
    return "Xhiqibot's web server is running.", 200

# --- メイン実行ブロック ---
if __name__ == "__main__":
    # Discord Botを別スレッドで起動
    # Cloud RunがメインプロセスにHTTPポートのリッスンを期待するため、
    # Flaskサーバーをメインプロセスで起動し、Botはサブスレッドで動かす。
    print("Starting Discord Bot in a separate thread...")
    discord_thread = Thread(target=bot.run, args=(DISCORD_TOKEN,))
    discord_thread.start()

    # FlaskアプリをGunicornで実行
    # Cloud Runは環境変数PORTを設定するので、それを取得して使用
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Flask web server with Gunicorn on port {port}...")
    # 'main:app' は、このファイル名が 'main.py' であり、Flaskアプリのインスタンス名が 'app' であることを想定
    # このスクリプトの名前が 'main.py' 以外の場合は、適宜変更してください (例: 'your_file_name:app')
    os.system(f"gunicorn --bind 0.0.0.0:{port} --workers 1 main:app")

    # 注意: os.system はブロックするため、ここより下のコードは実行されません。
    # 実際には、GunicornがFlaskサーバーのプロセスを管理し、このプロセスはCloud Runのコンテナ内で実行され続けます。
