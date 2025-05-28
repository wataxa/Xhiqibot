from __future__ import annotations
import asyncio, os, textwrap, random
from collections import deque
from typing import Tuple

import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

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
    except OpenAIError:
        reply = await complete(FALLBACK_MODEL, messages, max_tokens)

    reply = textwrap.fill(reply, width=60)
    history.append({"role": "assistant", "content": reply})

    if not is_ratio and random.random() < 0.15:
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

    if bot.user in msg.mentions:
        message_text = msg.content
        if msg.reference and isinstance(msg.reference.resolved,
                                        discord.Message):
            message_text = msg.reference.resolved.content

        reply = await respond_to(msg.author, message_text)
        await msg.channel.send(f"**xhiqi：** {reply}")

# --- 起動と同期 ---
@bot.event
async def on_ready():
    print("XhiqiBot starting …")
    try:
        if GUILD_ID_RAW:
            guild = discord.Object(id=int(GUILD_ID_RAW))
            await tree.sync(guild=guild)
            print("Slash コマンドをギルドへ同期しました")
        else:
            await tree.sync()
            print("Slash コマンドを全体へ同期しました (最大 1h)")
    except Exception as e:
        print("Sync error:", e)

# --- Flask 起動 ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Xhiqibot is running.", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- 実行 ---
if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.run(DISCORD_TOKEN)
