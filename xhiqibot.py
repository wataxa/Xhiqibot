from __future__ import annotations
import asyncio
import os
import random
import sys
from collections import deque
from threading import Thread
from typing import Tuple

import discord # <--- この行だけ残します

# from dotenv import load_dotenv # <-- この行は削除されたままです
from flask import Flask
from openai import APIError

# --- .env 読み込みと必須環境変数チェック ---
# load_dotenv() # <-- この呼び出しは削除されたままです

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID") or None
GUILD_ID_RAW = os.getenv("GUILD_ID") # 特定のギルドにスラッシュコマンドを同期する場合

# 環境変数のチェックは、コンテナが起動しない原因になる可能性があるので削除
# Cloud Runの環境変数設定で確実に設定してください
# if not DISCORD_TOKEN or not OPENAI_API_KEY:
#     print("エラー: DISCORD_TOKEN および OPENAI_API_KEY を .env ファイルに設定してください。", file=sys.stderr)
#     sys.exit(1) # 環境変数がなければプログラムを終了

# --- デバッグ用追加コード (ここから) ---
print("--- 環境変数デバッグ情報 ---", file=sys.stderr)
if DISCORD_TOKEN is None:
    print("デバッグ: DISCORD_TOKEN が None です。", file=sys.stderr)
else:
    print(f"デバッグ: DISCORD_TOKEN の長さ: {len(DISCORD_TOKEN)}", file=sys.stderr)
    print(f"デバッグ: DISCORD_TOKEN の先頭5文字: {DISCORD_TOKEN[:5]}", file=sys.stderr)
    # print(f"デバッグ: DISCORD_TOKEN の末尾5文字: {DISCORD_TOKEN[-5:]}", file=sys.stderr) # セキュリティのため末尾は出力しない

if OPENAI_API_KEY is None:
    print("デバッグ: OPENAI_API_KEY が None です。", file=sys.stderr)
else:
    print(f"デバッグ: OPENAI_API_KEY の長さ: {len(OPENAI_API_KEY)}", file=sys.stderr)
    print(f"デバッグ: OPENAI_API_KEY の先頭5文字: {OPENAI_API_KEY[:5]}", file=sys.stderr)
    # print(f"デバッグ: OPENAI_API_KEY の末尾5文字: {OPENAI_API_KEY[-5:]}", file=sys.stderr) # セキュリティのため末尾は出力しない

if OPENAI_PROJECT_ID is None:
    print("デバッグ: OPENAI_PROJECT_ID が None です。", file=sys.stderr)
else:
    print(f"デバッグ: OPENAI_PROJECT_ID の値: {OPENAI_PROJECT_ID}", file=sys.stderr)

if GUILD_ID_RAW is None:
    print("デバッグ: GUILD_ID_RAW が None です。", file=sys.stderr)
else:
    print(f"デバッグ: GUILD_ID_RAW の値: {GUILD_ID_RAW}", file=sys.stderr)
print("--- 環境変数デバッグ情報ここまで ---", file=sys.stderr)
# --- デバッグ用追加コード (ここまで) ---


# --- OpenAI SDK 初期化とAPI呼び出し関数 ---
try:
    # OpenAI SDK v1.x の場合
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY, project=OPENAI_PROJECT_ID)
    OpenAIException = APIError # エラーハンドリング用の基底クラスとしてAPIErrorを使用

    async def complete_openai_call(model: str, messages: list, max_tokens: int) -> str:
        """OpenAI API (v1.x) を非同期で呼び出す"""
        resp = await asyncio.to_thread( # 同期メソッドを別スレッドで非同期実行
            openai_client.chat.completions.create,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    print("[OpenAI SDK] v1.x detected.")

except ImportError:
    # 古い OpenAI SDK v0.x の場合 (フォールバック)
    import openai # type: ignore
    openai.api_key = OPENAI_API_KEY
    # openai.project = OPENAI_PROJECT_ID # v0.xでのproject指定はサポートされていない可能性あり
    OpenAIException = openai.error.OpenAIError # type: ignore

    async def complete_openai_call(model: str, messages: list, max_tokens: int) -> str:
        """OpenAI API (v0.x) を非同期で呼び出す"""
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
    print("[OpenAI SDK] v0.x detected (fallback).")


# --- モデル指定 ---
PRIMARY_MODEL = "gpt-4o-mini"
FALLBACK_MODEL = "gpt-3.5-turbo"

# --- 会話履歴保持 ---
# messagesのロールは "user", "assistant", "system"
# "name" フィールドは role="user" のみ
history = deque(maxlen=20) # 最新20件の会話を保持

def get_response_limits(text: str) -> Tuple[int, int]:
    """メッセージ内容に応じて返答の文字数と最大トークン数を設定"""
    if "レイシオ" in text:
        return (2000, 1500) # レイシオの場合、最大2000文字、1500トークン
    return (200, 200) # 通常は最大200文字、200トークン

# --- Discord Bot定義と初期化 ---
intents = discord.Intents.default() # <--- discord. を付けました
intents.message_content = True # メッセージ内容の読み取りを有効化
bot = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(bot) # <--- discord. を付けました

# --- 共通の応答生成ロジック ---
async def generate_bot_response(user_display_name: str, message_content: str) -> str:
    """
    OpenAI APIを呼び出して、Discord Botの応答を生成する
    """
    char_limit, max_tokens = get_response_limits(message_content)

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

    reply_content = ""
    try:
        # プライマリモデルで応答を試行
        reply_content = await complete_openai_call(PRIMARY_MODEL, messages_for_api, max_tokens)
    except APIError as e: # ImportError ではなく APIError を直接キャッチ
        print(f"Primary model ({PRIMARY_MODEL}) API error: {e}", file=sys.stderr)
        try:
            # プライマリモデルが失敗した場合、フォールバックモデルを試行
            reply_content = await complete_openai_call(FALLBACK_MODEL, messages_for_api, max_tokens)
            print(f"Successfully used fallback model ({FALLBACK_MODEL}).")
        except APIError as e_fallback: # ImportError ではなく APIError を直接キャッチ
            print(f"Fallback model ({FALLBACK_MODEL}) API error: {e_fallback}", file=sys.stderr)
            return "APIエラーが発生しました。しばらくしてからもう一度お試しください。"

    # AIの返答を履歴に追加
    history.append({"role": "assistant", "content": reply_content})

    # 低確率でカニに関する思考を追加 (「レイシオ」を含まない場合のみ)
    if "レイシオ" not in message_content and random.random() < 0.15:
        try:
            crab_thought = await complete_openai_call(
                PRIMARY_MODEL, # カニ思考もメインモデルで
                [
                    {"role": "system", "content": "あなたは時々カニを想います。100字以内で書いてください。"},
                    {"role": "user", "content": "今、何を考えていますか？"},
                ],
                max_tokens=100,
            )
            reply_content += f"\n\n（ところで、{crab_thought.strip()}）"
        except APIError as e_crab: # ImportError ではなく APIError を直接キャッチ
            print(f"Crab thought generation error: {e_crab}", file=sys.stderr)
            # カニの思考でエラーが出ても、メインの返信はそのまま続行

    return reply_content

# --- Discord Botイベントリスナーとコマンド ---

# Botがオンラインになった時の処理
@bot.event
async def on_ready():
    print(f"XhiqiBot successfully logged in as {bot.user} (ID: {bot.user.id})")
    try:
        if GUILD_ID_RAW:
            # 特定のギルドにスラッシュコマンドを同期
            guild = discord.Object(id=int(GUILD_ID_RAW))
            synced_commands = await tree.sync(guild=guild)
            print(f"Slash コマンドをギルドに同期しました ({len(synced_commands)} コマンド)")
        else:
            # 全てのギルドにスラッシュコマンドを同期 (最大1時間かかる場合あり)
            synced_commands = await tree.sync()
            print(f"Slash コマンドを全体に同期しました ({len(synced_commands)} コマンド, 最大 1h)")
    except Exception as e:
        print(f"Slash コマンド同期エラー: {e}", file=sys.stderr)

# /xhiqi スラッシュコマンドの定義
@tree.command(name="xhiqi", description="xhiqi とお話しする")
@discord.app_commands.describe(message="話しかけたい内容") # <--- discord. を付けました
async def xhiqi_command(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True) # Botが考えていることを表示
    reply_text = await generate_bot_response(interaction.user.display_name, message)
    await interaction.followup.send(
        f"**{interaction.user.display_name}：** {message}\n**xhiqi：** {reply_text}")

# メンションに対する応答
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: # Bot自身のメッセージは無視
        return

    # Botへのメンションが含まれているか確認
    if bot.user and bot.user.mentioned_in(message):
        # メンション部分を削除して、純粋なメッセージ内容を取得
        # 例: `@BotName メッセージ` -> `メッセージ`
        # 返信 (Reply) の場合は、返信元のメッセージを取得
        clean_message_content = message.content.replace(f'<@!{bot.user.id}>', '').strip()
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            # 返信の場合は、返信元のメッセージ内容を優先
            clean_message_content = message.reference.resolved.content
        
        if not clean_message_content: # メッセージ内容が空なら処理しない
            return

        async with message.channel.typing(): # Botが「入力中...」と表示
            reply_text = await generate_bot_response(message.author.display_name, clean_message_content)
        
        # 返信元にリプライする形式でメッセージを送信
        await message.channel.send(f"**xhiqi：** {reply_text}", reference=message.reference)

# --- Flask Webサーバーの設定 (Cloud Runのヘルスチェック用) ---
app = Flask(__name__)

@app.route('/')
def home():
    """Cloud Runのヘルスチェックに応答するエンドポイント"""
    return "Xhiqibot's web server is running and healthy.", 200

# Discord Botの起動をメインの実行フロー（Gunicornの起動とは別）に含める
# xhiqibot.pyがインポートされたときに実行されるようにします。
# CMD ["gunicorn", ...] が xhiqibot:app をロードすると、この部分はGunicornのワーカープロセス内で実行される
print("Discord Botを別スレッドで起動します...")
discord_thread = Thread(target=bot.run, args=(DISCORD_TOKEN,))
discord_thread.start()
