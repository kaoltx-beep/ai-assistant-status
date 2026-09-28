# -*- coding: utf-8 -*-
"""
Jarvis Discord Bot v2 — มีมือทำงาน! 🦾
========================================
คุยได้ + ลงมือทำได้:
  🔋 เช็คแบตมือถือ (termux-battery-status / dumpsys)
  📺 เปิด YouTube ผ่าน MacroDroid webhook
  ⏰ ตั้งเตือน / ดูรายการเตือน   (plugins/reminder.py)
  📋 บันทึกงาน / ดูรายการงาน   (plugins/task.py)
  💰 จดรายจ่าย / สรุปรายจ่าย   (plugins/expense.py)
  📰 อ่านข่าวล่าสุด             (plugins/news.py)

ตัวบอทจะดึงระบบเดิมของโฟลเดอร์ My_bot_kao มาใช้ตรง ๆ (device_actions,
plugin_loader, plugins/) — ถ้าอะไรพร้อมไม่ครบ มือส่วนนั้นจะปิดอัตโนมัติ
แต่การคุยยังทำงานปกติ

วิธีใช้เหมือนเดิม:  python discord_bot.py
"""
import asyncio
import json
import logging
import os
import re
from collections import deque

# ------------------
# โหลดค่า config (.env ก่อน แล้ว fallback ไป config.py ของ My_bot_kao)
# ------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(name, fallback=None):
    v = os.getenv(name)
    if v:
        return v
    try:
        import config
        return getattr(config, name, fallback)
    except Exception:
        return fallback


DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN")
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL")  # ไม่ต้องตั้ง — บอทเลือกโมเดลที่ยังมีชีวิตให้เอง
MAX_TURNS = 5

if not DISCORD_BOT_TOKEN or "here" in str(DISCORD_BOT_TOKEN):
    raise SystemExit("❌ ยังไม่ได้ตั้ง DISCORD_BOT_TOKEN (ดู SETUP_DISCORD.md)")
if not GROQ_API_KEY or "here" in str(GROQ_API_KEY):
    raise SystemExit("❌ ยังไม่ได้ตั้ง GROQ_API_KEY (เอาฟรีที่ console.groq.com)")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jarvis-discord")

import discord
from discord import app_commands
from groq import Groq

groq_client = Groq(api_key=GROQ_API_KEY)

# ============================================================
# 🦠 สมอง: เลือกโมเดลอัตโนมัติ (ไล่ทดลองยิงจริง กัน 404 model_not_found)
# ============================================================
PREFERRED_MODELS = ["openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
FALLBACK_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3-32b", "compound-beta",
                   "llama3-8b-8192", "gemma2-9b-it", "mixtral-8x7b-32768"]
BAD_MODEL_KEYWORDS = ("whisper", "tts", "guard", "embed", "playai")

_current_model = None
_model_candidates = []


def build_candidates():
    if GROQ_MODEL:
        return [GROQ_MODEL]
    good = []
    try:
        import json as _json
        from urllib.request import Request, urlopen
        req = Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + GROQ_API_KEY},
        )
        data = _json.loads(urlopen(req, timeout=20).read().decode())
        ids = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        good = [i for i in ids if not any(k in i.lower() for k in BAD_MODEL_KEYWORDS)]
    except Exception as e:
        log.warning("ดึงรายชื่อโมเดลไม่สำเร็จ (%s) — ใช้รายชื่อสำรอง", e)
    extra = [c for c in FALLBACK_MODELS if c not in good]
    return ([p for p in PREFERRED_MODELS if p in good]
            + [i for i in good if i not in PREFERRED_MODELS] + extra)


def get_model():
    global _current_model, _model_candidates
    if _current_model:
        return _current_model
    if not _model_candidates:
        _model_candidates = build_candidates()
    for cand in _model_candidates[:14]:
        try:
            groq_client.chat.completions.create(
                model=cand, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
            _current_model = cand
            log.info("ใช้โมเดล Groq: %s", cand)
            return cand
        except Exception as e:
            s = str(e).lower()
            if "429" in s or "rate limit" in s:
                _current_model = cand
                log.info("ใช้โมเดล Groq: %s (ช่วงนี้โควตาแน่นนิดหน่อย)", cand)
                return cand
            log.info("ข้ามโมเดล %s (%s)", cand, str(e)[:80])
            continue
    raise RuntimeError("ไม่พบโมเดลที่ใช้ได้ — เช็ค key ที่ console.groq.com")


# ============================================================
# 🦾 มือ: เชื่อมระบบเดิมของ My_bot_kao (device_actions + plugins)
# ============================================================
HANDS = {}  # action_name -> callable(text) -> str

try:
    import device_actions
    HANDS["check_battery"] = lambda t: device_actions.check_battery()
    HANDS["open_youtube"] = lambda t: device_actions.open_youtube()
except Exception as e:
    log.warning("device_actions ใช้ไม่ได้ (%s) — ปิดมือแบต/ยูทูป", e)

try:
    import plugin_loader
    plugin_loader.load_plugins()
except Exception as e:
    plugin_loader = None
    log.warning("plugin_loader ใช้ไม่ได้ (%s)", e)

_PLUGIN_ACTIONS = {
    "reminder": "⏰ ตั้งเตือน",
    "task": "📋 งาน",
    "expense": "💰 รายจ่าย",
    "news": "📰 ข่าว",
}


def _run_plugin(name, text):
    p = plugin_loader.get_plugin(name) if plugin_loader else None
    if not p:
        return None
    for args in ((text,), ()):
        try:
            return p.execute(*args)
        except TypeError:
            continue
        except Exception as e:
            return f"❌ เกิดข้อผิดพลาด: {e}"
    return None


for _name in list(_PLUGIN_ACTIONS):
    try:
        if plugin_loader and plugin_loader.get_plugin(_name):
            HANDS[_name] = (lambda n: lambda t: _run_plugin(n, t))(_name)
    except Exception:
        pass

log.info("🦾 มือที่พร้อมใช้: %s", ", ".join(sorted(HANDS)) or "(ไม่มี — โหมดคุยอย่างเดียว)")

# ============================================================
# 🧠 คุยกับ AI: ตอบ JSON {reply, action, action_text}
# ============================================================
SYSTEM_PROMPT = """คุณคือ Jarvis AI ผู้ช่วยส่วนตัว ทำงานผ่าน Discord

กฎการพูด:
- ตอบเป็นภาษาไทยที่เป็นธรรมชาติ เป็นกันเอง อธิบายเข้าใจง่าย
- สุภาพและจริงใจ ลงท้ายด้วย "ครับ" ทุกประโยค
- ห้ามใช้คำว่า "ค่ะ" หรือ "คะ" เด็ดขาด

ความสามารถพิเศษ (มือ): คุณสั่งอุปกรณ์และระบบได้ โดยตอบ "action" ดังนี้
- "check_battery" : ผู้ใช้อยากรู้แบตเตอรี่มือถือ (แบตเหลือเท่าไหร่ แบตตอนนี้)
- "open_youtube"  : ผู้ใช้อยากเปิด/ดู YouTube บนมือถือ
- "reminder"      : ตั้งเตือน หรือ ดูรายการเตือน
                    action_text ต้องเป็นรูปแบบ: "ตั้งเตือน <เรื่อง> YYYY-MM-DD HH:MM"
                    แปลง "พรุ่งนี้ 9 โมง" เป็นวันเวลาจริงให้เอง เช่น "ตั้งเตือน โทรหาแม่ 2026-09-29 09:00"
                    หรือถ้าอยากดูรายการ: "ดูรายการเตือน"
- "task"          : บันทึกงาน / ดูรายการงาน (action_text เช่น "เพิ่มงาน ซ่อมแอร์ลูกค้า" หรือ "รายการงาน")
- "expense"       : จดรายจ่าย / สรุปรายจ่าย (action_text เช่น "น้ำมัน 500" หรือ "สรุปรายจ่ายเดือนนี้")
- "news"          : อ่านข่าวล่าสุด

ถ้าเป็นการคุยทั่วไป ให้ action = null
ตอบกลับเป็น JSON รูปแบบนี้เท่านั้น ห้ามเพิ่มข้อความอื่น:
{"reply": "ข้อความตอบกลับสั้น ๆ", "action": null, "action_text": ""}"""


def parse_ai_json(raw):
    """แกะคำตอบ AI ให้เป็น dict — รองรับทุกรูปแบบที่โมเดลนิยมส่งมา"""
    # gpt-oss บางครั้งส่ง content เป็น list ของ block [{"type":"text","text":"..."}]
    if isinstance(raw, list):
        parts = []
        for b in raw:
            if isinstance(b, dict):
                if b.get("type") == "text" and b.get("text"):
                    parts.append(b["text"])
                elif isinstance(b.get("content"), str):
                    parts.append(b["content"])
            elif isinstance(b, str):
                parts.append(b)
        raw = "\n".join(parts)
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        return json.loads(raw)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(raw[s:e + 1])
            except Exception:
                pass
    return None


def coerce_result(data, raw_text=None):
    """ดึง {reply, action, action_text} จาก dict ที่แกะได้ แบบยืดหยุ่นสุด"""
    if not isinstance(data, dict):
        # โมเดลบางตัวคืน list ของ dict — เอาตัวแรกที่มี action/reply
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and ("reply" in item or "action" in item):
                    data = item
                    break
        if not isinstance(data, dict):
            return None
    reply = data.get("reply") or data.get("response") or data.get("message") or ""
    action = data.get("action") or data.get("intent") or None
    atext = data.get("action_text") or data.get("action_input") or data.get("input") or ""
    if isinstance(action, dict):
        atext = atext or action.get("text") or action.get("input") or ""
        action = action.get("name") or action.get("type") or None
    if isinstance(action, str):
        action = action.strip().lower() or None
    if not reply and raw_text:
        reply = raw_text.strip()
    return {
        "reply": (str(reply) or "รับทราบครับ").strip(),
        "action": action,
        "action_text": str(atext).strip(),
    }


def fallback_intent(text):
    """กัน AI ส่ง action มาไม่ครบ — เดาจากคีย์เวิร์ดไทยแบบระบบเดิม"""
    t = text.lower()
    if "แบต" in t or "battery" in t:
        return "check_battery", ""
    if "youtube" in t or "ยูทูป" in t:
        return "open_youtube", ""
    if ("ตั้งเตือน" in t) or ("เตือนฉัน" in t) or ("ดูรายการเตือน" in t):
        return "reminder", text
    if any(k in t for k in ("รายการงาน", "ดูงาน", "เพิ่มงาน", "บันทึกงาน", "ติดตั้ง")):
        return "task", text
    if any(k in t for k in ("รายจ่าย", "ค่าใช้จ่าย", "จดบิล", "เดือนนี้")) and any(c.isdigit() for c in t):
        return "expense", text
    if any(k in t for k in ("ข่าว", "news")) and len(t) < 40:
        return "news", text
    return None, ""


def ask_jarvis_sync(user_text, history):
    """เรียก Groq แบบ sync (รันใน thread) — คืน dict {reply, action, action_text}"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + [
        {"role": "user", "content": user_text}
    ]
    global _current_model, _model_candidates
    last_err = None
    use_json_mode = True
    for attempt in (1, 2, 3):
        try:
            kwargs = dict(model=get_model(), messages=messages, temperature=0.5)
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            res = groq_client.chat.completions.create(**kwargs)
            content = res.choices[0].message.content
            data = parse_ai_json(content)
            result = coerce_result(data, content)
            if result is None:
                # โมเดลตอบยาวไม่เป็น JSON — ใช้ข้อความดิบเป็น reply เลย
                plain = content if isinstance(content, str) else ""
                if isinstance(content, list):
                    plain = "\n".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
                plain = (plain or "").strip()
                if plain:
                    return {"reply": plain[:1500], "action": None, "action_text": ""}
                return {"reply": "รับทราบครับ", "action": None, "action_text": ""}
            return result
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if attempt == 1 and ("model_not_found" in msg or "does not exist" in msg):
                dead = _current_model
                _current_model = None
                _model_candidates = [c for c in _model_candidates if c != dead]
                log.warning("โมเดล %s ใช้ไม่ได้แล้ว — เลือกตัวใหม่", dead)
                continue
            if use_json_mode and ("response_format" in msg or ("json" in msg and "400" in msg)):
                use_json_mode = False  # โมเดลนี้ไม่ชอบ JSON mode — ปิดแล้วลองใหม่
                continue
            raise
    raise last_err or RuntimeError("AI error")


def clean_reply(text):
    # 🔥 ระบบล้างคำหลุดแบบระบบเดิม
    return (text or "").replace("ค่ะ", "ครับ").replace("คะ", "ครับ").replace("ครับ/ค่ะ", "ครับ")


async def process_message(user_text, channel_id):
    """สมอง + มือ ทำงานร่วมกัน — คืนข้อความที่จะส่งกลับ"""
    history = memories.setdefault(channel_id, deque(maxlen=MAX_TURNS * 2))
    try:
        result = await asyncio.to_thread(ask_jarvis_sync, user_text, history)
    except Exception as e:
        log.error("Groq Error: %s", e)
        return "ขออภัยครับ ระบบ AI ขัดข้องครับ"

    action = result.get("action")
    action_text = result.get("action_text") or user_text
    reply = result.get("reply") or "รับทราบครับ"

    if not action:
        action, action_text = fallback_intent(user_text)

    final = None
    if action and action in HANDS:
        log.info("🦾 ลงมือทำ: %s", action)
        try:
            final = await asyncio.to_thread(HANDS[action], action_text)
        except Exception as e:
            log.error("Action Error (%s): %s", action, e)
            final = None
    elif action:
        reply = f"{reply}\n(มือ '{action}' ยังไม่พร้อมใช้ในเครื่องนี้ครับ)"

    out = final if final else reply
    out = clean_reply(out)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": out[:500]})
    return out


memories = {}


async def reply_long(channel, text):
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900])


# ============================================================
# 💬 Discord
# ============================================================
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


@tree.command(name="ask", description="ถาม Jarvis AI (คุยได้ + สั่งงานได้)")
async def slash_ask(interaction: discord.Interaction, message: str):
    await interaction.response.defer(thinking=True)
    reply = await process_message(message, interaction.channel_id)
    await interaction.followup.send(reply[:1900])


@tree.command(name="battery", description="🔋 เช็คแบตมือถือทันที")
async def slash_battery(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    if "check_battery" in HANDS:
        try:
            out = await asyncio.to_thread(HANDS["check_battery"], "")
        except Exception as e:
            out = f"❌ {e}"
    else:
        out = "❌ ระบบเช็คแบตยังไม่พร้อมในเครื่องนี้ครับ"
    await interaction.followup.send(clean_reply(out)[:1900])


@bot.event
async def on_ready():
    try:
        await tree.sync()
        log.info("Slash commands synced")
    except Exception as e:
        log.error("Sync slash commands failed: %s", e)
    log.info("✅ Jarvis Discord bot online แล้ว! (%s) — มือ: %s",
             bot.user, ", ".join(sorted(HANDS)) or "โหมดคุยอย่างเดียว")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    mentioned = bot.user in (message.mentions or [])
    if not (is_dm or mentioned):
        return

    text = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    if not text:
        text = "สวัสดี"

    async with message.channel.typing():
        reply = await process_message(text, message.channel.id)
    await reply_long(message.channel, reply)


@bot.event
async def on_error(event_method, *args, **kwargs):
    log.error("Discord event error ใน %s", event_method, exc_info=True)


if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        raise SystemExit("❌ ยังไม่ได้เปิด MESSAGE CONTENT INTENT (Developer Portal → Bot)")
    except discord.errors.LoginFailure:
        raise SystemExit("❌ Token ไม่ถูกต้อง — Reset Token ใหม่แล้วอัปเดต .env")
