from __future__ import annotations
import os
import discord
from discord.ext import commands
from openai import OpenAI
from flask import Flask, request, jsonify
from multiprocessing import Process
import asyncio

# Flaskアプリケーションの初期化
app = Flask(__name__)

# 環境変数の設定
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
OPENAI_PROJECT_ID = os.environ.get('OPENAI_PROJECT_ID') # OpenAI Project IDはオプション

# 環境変数デバッグ情報出力
print("--- 環境変数デバッグ情報 ---")
print(f"デバッグ: DISCORD_TOKEN の長さ: {len(DISCORD_TOKEN) if DISCORD_TOKEN else 'None'}")
print(f"デバッグ: DISCORD_TOKEN の先頭5文字: {DISCORD_TOKEN[:5] if DISCORD_TOKEN else 'None'}")
print(f"デバッグ: OPENAI_API_KEY の長さ: {len(OPENAI_API_KEY) if OPENAI_API_KEY else 'None'}")
print(f"デバッグ: OPENAI_API_KEY の先頭5文字: {OPENAI_API_KEY[:5] if OPENAI_API_KEY else 'None'}")
print(f"デバッグ: OPENAI_PROJECT_ID が {OPENAI_PROJECT_ID} です。")
# GUILD_ID_RAWはデバッグ用であり、実際の使用はGUILD_IDに集約されます
GUILD_ID_RAW = os.environ.get('GUILD_ID')
print(f"デバッグ: GUILD_ID_RAW の長さ: {len(GUILD_ID_RAW) if GUILD_ID_RAW else 'None'}")
print(f"デバッグ: GUILD_ID_RAW の先頭5文字: {GUILD_ID_RAW[:5] if GUILD_ID_RAW else 'None'}")
print("--- 環境変数デバッグ情報ここまで ---")


# 環境変数が設定されているか確認
if not DISCORD_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("env に DISCORD_TOKEN と OPENAI_API_KEY を設定してください")

# OpenAIクライアントの初期化
openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    project=OPENAI_PROJECT_ID if OPENAI_PROJECT_ID else None
)

# Discord Botの初期化
intents = discord.Intents.all()
intents.message_content = True

# botオブジェクトの初期化
bot = commands.Bot(command_prefix='!', intents=intents)

# グローバルスコープまたはギルドスコープのいずれかでスラッシュコマンドを同期するためのGUILD_ID
GUILD_ID = discord.Object(id=int(os.environ.get('GUILD_ID'))) if os.environ.get('GUILD_ID') else None

# ペルソナ設定をファイルから読み込む
def load_persona(filename="persona.txt"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "あなたは親切なAIアシスタントです。" # デフォルトのペルソナ

persona_prompt = load_persona()

# Botがオンラインになった時のイベント
@bot.event
async def on_ready():
    print(f'{bot.user} successfully logged in as {bot.user.name} (ID: {bot.user.id})')
    try:
        if GUILD_ID:
            # 特定のギルドにスラッシュコマンドを同期
            bot.tree.copy_global_to(guild=GUILD_ID)
            await bot.tree.sync(guild=GUILD_ID)
            print(f"Slash コマンドをギルドに同期しました (1 コマンド)")
        else:
            # グローバルにスラッシュコマンドを同期
            await bot.tree.sync()
            print("Slash コマンドを全体に同期しました (1 コマンド, 最大 1h)")

        # ★★★ ここに常に🕯️だけのステータスを設定 ★★★
        await bot.change_presence(activity=discord.Game(name="🕯️"))
        print(f"Botのステータスを「🕯️」に設定しました。")
        # ★★★ ここまでステータス設定 ★★★

    except Exception as e:
        if GUILD_ID:
            print(f"Slash コマンド同期エラー (ギルドID: {GUILD_ID.id}): {e}")
        else:
            print(f"Slash コマンド同期エラー (グローバル): {e}")


# メッセージを受信した時のイベント
@bot.event
async def on_message(message):
    print(f"DEBUG: Received ANY message from {message.author} in channel {message.channel.name}: {message.content}")

    if message.author.bot:
        print(f"DEBUG: Message author is a bot, skipping.")
        return

    if bot.user.mentioned_in(message):
        print(f"DEBUG: Bot was mentioned in message: {message.content}")
        clean_message_content = message.content.replace(f'<@{bot.user.id}>', '').strip()

        if not clean_message_content:
            await message.channel.send("何か質問がありますか？")
            return

        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": persona_prompt},
                    {"role": "user", "content": clean_message_content}
                ],
                max_tokens=150
            )
            ai_response = response.choices[0].message.content
            await message.channel.send(ai_response)
            print(f"AI Response: {ai_response}")

        except Exception as e:
            print(f"OpenAI API error: {e}")
            await message.channel.send("AIとの通信中にエラーが発生しました。申し訳ありません。")
    else:
        print(f"DEBUG: Message not a direct mention or slash command: {message.content}")

# スラッシュコマンド
@bot.tree.command(name="xhiqi", description="AIに質問します", guild=GUILD_ID)
async def xhiqi_command(interaction: discord.Interaction, message: str):
    await interaction.response.defer()
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": persona_prompt},
                {"role": "user", "content": message}
            ],
            max_tokens=150
        )
        ai_response = response.choices[0].message.content
        await interaction.followup.send(ai_response)
        print(f"Slash Command AI Response: {ai_response}")

    except Exception as e:
        print(f"OpenAI API error (slash command): {e}")
        await interaction.followup.send("AIとの通信中にエラーが発生しました。申し訳ありません。")

# Flaskルートハンドラ
@app.route('/')
def home():
    return jsonify({"status": "ok", "message": "XhiqiBot Flask server is running."})

# Cloud Runのヘルスチェックエンドポイント
@app.route('/_ah/health')
def health_check():
    return jsonify({"status": "ok"})

# Discord Botの実行プロセス
def run_discord_bot():
    print("Discord Botプロセスを開始します...")
    bot.run(DISCORD_TOKEN)

# メイン実行ブロック
if __name__ == '__main__':
    discord_process = Process(target=run_discord_bot)
    discord_process.start()
