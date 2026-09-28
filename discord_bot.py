# -*- coding: utf-8 -*-
"""
Jarvis Discord Bot — ให้ AI (Groq) ของคุณตอบคุยผ่าน Discord
=============================================================
วิธีใช้ (สั้น ๆ):
  1) pip install -U discord.py groq python-dotenv
  2) เอาไฟล์นี้วางในโฟลเดอร์เดียวกับ My_bot_kao (จะดึง GROQ_API_KEY จาก config.py ให้อัตโนมัติ)
     หรือจะตั้งค่าใน .env เองก็ได้:
        DISCORD_BOT_TOKEN=token จาก Discord Developer Portal
        GROQ_API_KEY=gsk_...
  3) python discord_bot.py
  4) ไปพิมพ์ @Jarvis สวัสดี ใน Discord ได้เลย!

อ่านวิธีตั้งค่าละเอียดแบบกดทีละขั้น ในไฟล์ SETUP_DISCORD.md
"""

import asyncio
import logging
import os
from collections import deque

# ------------------
# โหลดค่า config (.env ก่อน แล้ว fallback ไป config.py ของ My_bot_kao ถ้ามี)
# ------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(name, fallback=None):
    """ดึงค่าจาก environment ก่อน ถ้าไม่มีค่อยลอง import config.py"""
    v = os.getenv(name)
    if v:
        return v
    try:
        import config  # ไฟล์ config.py ของ My_bot_kao (ถ้าวางไว้โฟลเดอร์เดียวกัน)
        return getattr(config, name, fallback)
    except Exception:
        return fallback


DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN")
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "llama-3.1-8b-instant")
MAX_TURNS = 5  # จำคอยสนทนาย้อนหลัง 5 รอบต่อแชนเนล

if not DISCORD_BOT_TOKEN or "here" in str(DISCORD_BOT_TOKEN) or "ใส่" in str(DISCORD_BOT_TOKEN):
    raise SystemExit(
        "❌ ยังไม่ได้ตั้งค่า DISCORD_BOT_TOKEN\n"
        "   วิธีทำ: สร้างบอทที่ https://discord.com/developers/applications\n"
        "   แล้วใส่ token ในไฟล์ .env  →  ดูขั้นตอนเต็มใน SETUP_DISCORD.md"
    )
if not GROQ_API_KEY or "here" in str(GROQ_API_KEY) or "ใส่" in str(GROQ_API_KEY):
    raise SystemExit(
        "❌ ยังไม่ได้ตั้งค่า GROQ_API_KEY\n"
        "   เอา key ฟรีได้ที่ https://console.groq.com  →  ดูใน SETUP_DISCORD.md"
    )

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jarvis-discord")

import discord
from discord import app_commands
from groq import Groq

groq_client = Groq(api_key=GROQ_API_KEY)

# ------------------
# ความจำรายแชนเนล: channel_id -> deque ของ {"role","content"}
# ------------------
memories = {}


def ask_jarvis_sync(user_text, history):
    """ยิงคำถามไป Groq  (เรียกแบบ sync แล้วเอาไปรันใน thread แยก)"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + [
        {"role": "user", "content": user_text}
    ]
    res = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.7,
    )
    return (res.choices[0].message.content or "").strip()


SYSTEM_PROMPT = """คุณคือ Jarvis AI ผู้ช่วยส่วนตัว ทำงานผ่าน Discord

กฎ:
- ตอบเป็นภาษาไทยที่เป็นธรรมชาติ เป็นกันเอง และอธิบายเข้าใจง่าย
- สุภาพและจริงใจ
- ลงท้ายด้วย "ครับ" ทุกประโยค
- ห้ามใช้คำว่า "ค่ะ" หรือ "คะ" เด็ดขาด
- ตอบสั้น กระชับ เหมาะกับการแชท"""


async def ask_jarvis(user_text, channel_id):
    """คุยกับ AI พร้อมจำบริบทรายแชนเนล"""
    history = memories.setdefault(channel_id, deque(maxlen=MAX_TURNS * 2))
    try:
        reply = await asyncio.to_thread(ask_jarvis_sync, user_text, history)
    except Exception as e:
        log.error("Groq Error: %s", e)
        return "ขออภัยครับ ระบบ AI ขัดข้องครับ"

    # 🔥 ล้างคำหลุดเหมือนระบบเดิม 100%
    reply = reply.replace("ค่ะ", "ครับ").replace("คะ", "ครับ") or "รับทราบครับ"

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    return reply


async def reply_long(channel, text):
    """ส่งข้อความยาวได้หลายข้อความ (Discord จำกัด 2000 ตัวอักษร)"""
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900])


# ------------------
# บอท
# ------------------
intents = discord.Intents.default()
intents.message_content = True  # ⚠️ ต้องเปิดใน Developer Portal ด้วย (ดู SETUP_DISCORD.md ขั้นที่ 3)

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@tree.command(name="ask", description="ถาม Jarvis AI")
async def slash_ask(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    reply = await ask_jarvis(message, interaction.channel_id)
    await interaction.followup.send(reply[:1900])


@bot.event
async def on_ready():
    try:
        await tree.sync()
        log.info("Slash commands synced")
    except Exception as e:
        log.error("Sync slash commands failed: %s", e)
    log.info("✅ Jarvis Discord bot online แล้ว! (%s)", bot.user)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    mentioned = bot.user in (message.mentions or [])

    if not (is_dm or mentioned):
        return  # ไม่ตอบข้อความทั่วไปในแชนเนล กันสแปม

    # ตัด @mention ออกจากข้อความ
    text = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    if not text:
        text = "สวัสดี"

    async with message.channel.typing():
        reply = await ask_jarvis(text, message.channel.id)
    await reply_long(message.channel, reply)


@bot.event
async def on_error(event_method, *args, **kwargs):
    log.error("Discord event error ใน %s", event_method, exc_info=True)


if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        raise SystemExit(
            "❌ Discord บอกว่ายังไม่ได้เปิด Message Content Intent\n"
            "   แก้ที่ https://discord.com/developers/applications → เลือกแอป → Bot\n"
            "   → เปิด 'MESSAGE CONTENT INTENT' แล้วกด Save  (ดู SETUP_DISCORD.md ขั้นที่ 3)"
        )
    except discord.errors.LoginFailure:
        raise SystemExit("❌ Token ไม่ถูกต้อง — เอา token ใหม่จาก Developer Portal → Bot → Reset Token")
