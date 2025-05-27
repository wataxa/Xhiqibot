"""
Xhiqi Discord Bot — SDK 0.x & 1.x 両対応版
=========================================
* `/talk <message>` → 200 文字以内で返答（入力に「レイシオ」があると 1000 文字）。
* `gpt-4o-mini` → 失敗時は `gpt-3.5-turbo` へ自動フォールバック。
* `sk-…`（個人キー）と `sk-proj-…`（プロジェクトキー）の両方をサポート。

.env:
    DISCORD_TOKEN=your_discord_bot_token
    OPENAI_API_KEY=sk-… または sk-proj-…
    # sk-proj- を使う場合だけ設定
    OPENAI_PROJECT_ID=proj_XXXXXXXXXXXXXXXXXXXX
    # 開発中に Slash コマンドを即時反映する場合のみ
    GUILD_ID=123456789012345678

セットアップ:
    pip install --upgrade "openai>=0.28" discord.py python-dotenv
実行:
    python xhiqibot.py
"""
from __future__ import annotations

import asyncio
import os
import textwrap
from typing import Tuple

import discord
from discord import app_commands
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1.  secrets
# ---------------------------------------------------------------------------
load_dotenv()
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
OPENAI_PROJECT_ID  = os.getenv("OPENAI_PROJECT_ID")  # proj_… (sk-proj- 用) 個人キーなら不要
GUILD_ID_RAW       = os.getenv("GUILD_ID")

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError(".env に DISCORD_TOKEN と OPENAI_API_KEY を設定してください")

PRIMARY_MODEL  = "gpt-4o-mini"
FALLBACK_MODEL = "gpt-3.5-turbo"

# ---------------------------------------------------------------------------
# 2.  OpenAI SDK 0.x / 1.x 互換ラッパ
# ---------------------------------------------------------------------------
try:
    import openai  # v1.x でも import 可能
    from openai import OpenAI  # v1.x のみ存在

    _client = OpenAI(api_key=OPENAI_API_KEY, project=OPENAI_PROJECT_ID)
    OpenAIError = openai.OpenAIError

    async def chat_complete(model: str, sys_msg: str, user_msg: str, max_tok: int) -> str:
        resp = _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tok,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()

    print("[OpenAI SDK] v1.x detected")
except (ImportError, AttributeError):
    import openai  # type: ignore
    openai.api_key = OPENAI_API_KEY
    if OPENAI_PROJECT_ID:
        openai.organization = OPENAI_PROJECT_ID  # v0.x では org/ proj 指定にこれを利用

    OpenAIError = openai.error.OpenAIError  # type: ignore

    async def chat_complete(model: str, sys_msg: str, user_msg: str, max_tok: int) -> str:
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: openai.ChatCompletion.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=max_tok,
                temperature=0.7,
            ),
        )
        return resp["choices"][0]["message"]["content"].strip()

    print("[OpenAI SDK] v0.x detected")

# ---------------------------------------------------------------------------
# 3.  helper — decide limits
# ---------------------------------------------------------------------------

def limits_for(text: str) -> Tuple[int, int]:
    return (1000, 700) if "レイシオ" in text else (200, 200)

# ---------------------------------------------------------------------------
# 4.  Discord bot scaffolding
# ---------------------------------------------------------------------------
class XhiqiBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID_RAW:
            guild = discord.Object(id=int(GUILD_ID_RAW))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print("Slash コマンドをギルドへ同期しました")
        else:
            await self.tree.sync()
            print("Slash コマンドを全体へ同期しました (最大 1h)")

bot = XhiqiBot()

# ---------------------------------------------------------------------------
# 5.  /talk command
# ---------------------------------------------------------------------------
@bot.tree.command(name="talk", description="xhiqi とお話しする")
@app_commands.describe(message="質問や話しかけたい内容")
async def talk(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)

    char_limit, max_tok = limits_for(message)
    sys_prompt = (
        "あなたの名前はしき（xhiqi）。穏やかで丁寧に、"
        f"{char_limit} 文字以内で日本語で答えてください。"
    )

    try:
        reply = await chat_complete(PRIMARY_MODEL, sys_prompt, message, max_tok)
    except OpenAIError as primary_err:
        print("Primary model error:", primary_err)
        try:
            reply = await chat_complete(FALLBACK_MODEL, sys_prompt, message, max_tok)
        except OpenAIError as fallback_err:
            print("Fallback model error:", fallback_err)
            await interaction.followup.send("OpenAI API エラーで返答できませんでした…", ephemeral=True)
            return

    reply = textwrap.shorten(reply, width=char_limit, placeholder="…")
    await interaction.followup.send(reply)

# ---------------------------------------------------------------------------
# 6.  slash-level error handler
# ---------------------------------------------------------------------------
@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print("Discord command error:", repr(error))
    try:
        await interaction.followup.send("コマンド実行時にエラーが発生しました…", ephemeral=True)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 7.  run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("XhiqiBot starting …")
    bot.run(DISCORD_TOKEN)
