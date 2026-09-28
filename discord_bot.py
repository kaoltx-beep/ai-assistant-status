# -*- coding: utf-8 -*-
"""
Jarvis Discord Bot v4 — สมอง 🧠 + มือ 🦾 + เสียงผู้หญิงน่าฟัง 🎙️
=================================================================
ความสามารถ:
  💬 คุยได้ทุกเรื่อง (Groq AI + จำบริบท 5 รอบ)
  🔊 ตอบด้วย "เสียงผู้หญิง" (Google Thai Voice) — พูดออกลำโพง
      + ส่งไฟล์เสียงมีปุ่ม play ใน Discord เหมือน voice note
  🔋 เช็คแบตมือถือ    📺 เปิด YouTube (MacroDroid)
  ⏰ ตั้งเตือน + แจ้งเตือนเองเมื่อถึงเวลา (มีเสียงเรียกด้วย)
  📋 งาน / งานติดตั้ง   💰 รายจ่าย   📰 ข่าว
  🌤️ อากาศวันนี้        💱 อัตราแลกเปลี่ยน   🎲 ทอยเต๋า/สุ่มเลข

ติดตั้งครั้งแรก:  pip install -U discord.py groq python-dotenv gTTS requests
รัน:              python discord_bot.py
"""
import asyncio
import glob
import json
import logging
import os
import random
import re
import sqlite3
import subprocess
import time
from collections import deque
from datetime import datetime

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
# 🧠 สมอง: เลือกโมเดลอัตโนมัติ (ไล่ทดลองยิงจริง กัน 404 model_not_found)
# ============================================================
PREFERRED_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]
FALLBACK_MODELS = ["qwen/qwen3-32b", "compound-beta", "llama3-8b-8192",
                   "gemma2-9b-it", "mixtral-8x7b-32768"]
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
    # ลองโมเดลที่ยืนยันสดว่ามีชีวิตก่อนเสมอ (แม้ดึงลิสต์จาก API ไม่สำเร็จ)
    # จากนั้นค่อยตามด้วยรายชื่อจาก API และลิสต์สำรอง
    return (PREFERRED_MODELS
            + [i for i in good if i not in PREFERRED_MODELS]
            + [c for c in FALLBACK_MODELS if c not in PREFERRED_MODELS])


def get_model():
    global _current_model, _model_candidates
    if _current_model:
        return _current_model
    if not _model_candidates:
        _model_candidates = build_candidates()
    for cand in _model_candidates[:14]:
        try:
            # โปรบแบบไม่จำกัด token — โมเดลแบบคิดก่อนตอบ (gpt-oss/qwen) จะ 400 ถ้าใส่ max_tokens น้อย
            groq_client.chat.completions.create(
                model=cand, messages=[{"role": "user", "content": "ping"}])
            _current_model = cand
            log.info("ใช้โมเดล Groq: %s", cand)
            return cand
        except Exception as e:
            s = str(e).lower()
            if "429" in s or "rate limit" in s:
                _current_model = cand
                log.info("ใช้โมเดล Groq: %s (ช่วงนี้โควตาแน่นนิดหน่อย)", cand)
                return cand
            dead = any(k in s for k in ("decommission", "model_not_found",
                                        "does not exist", "do not have access"))
            if dead:
                log.info("ข้ามโมเดล %s (ถูกปลด/ไม่มีสิทธิ์)", cand)
                continue
            # error อื่น (เช่นพารามิเตอร์ไม่ตรง) = โมเดลยังมีชีวิต ให้ลองใช้จริง
            _current_model = cand
            log.info("ใช้โมเดล Groq: %s (หมายเหตุ: %s)", cand, str(e)[:70])
            return cand
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


for _name in ("reminder", "expense", "news"):  # ไม่โหลด "task" (ระบบงานของทาง) — ตามคำขอเจ้าของบอท
    try:
        if plugin_loader and plugin_loader.get_plugin(_name):
            HANDS[_name] = (lambda n: lambda t: _run_plugin(n, t))(_name)
    except Exception:
        pass


# ============================================================
# 🌤️ มือใหม่: อากาศ / อัตราแลกเปลี่ยน / สุ่ม (ใช้ได้ทันที ไม่ต้องตั้งค่า)
# ============================================================
def hand_weather(text=""):
    import requests
    t = text or ""
    city_map = {"กรุงเทพ": "Bangkok", "กรุงเทพฯ": "Bangkok", "bangkok": "Bangkok",
                "เชียงใหม่": "Chiang%20Mai", "เชียงราย": "Chiang%20Rai",
                "ภูเก็ต": "Phuket", "ขอนแก่น": "Khon%20Kaen",
                "หาดใหญ่": "Hat%20Yai", "พัทยา": "Pattaya", "อุดร": "Udon%20Thani"}
    city = "Bangkok"
    for th, en in city_map.items():
        if th in t.lower():
            city = en
            break
    r = requests.get(f"https://wttr.in/{city}?format=j1", timeout=15)
    cur = r.json()["current_condition"][0]
    desc = cur["weatherDesc"][0]["value"]
    return (f"🌤️ อากาศ{('ที่ ' + city.replace('%20', ' ')) if city != 'Bangkok' else 'กรุงเทพ'}ตอนนี้\n"
            f"🌡️ {cur['temp_C']}°C (รู้สึกจริง {cur['FeelsLikeC']}°C)\n"
            f"💧 ความชื้น {cur['humidity']}% • {desc} ครับ")


def hand_rates(text=""):
    import requests
    t = (text or "").lower()
    r = requests.get("https://open.er-api.com/v6/latest/THB", timeout=15)
    rates = r.json().get("rates", {})
    names = [("ดอลลาร์สหรัฐ", "USD"), ("ยูโร", "EUR"), ("เยนญี่ปุ่น", "JPY"),
             ("หยวนจีน", "CNY"), ("ปอนด์อังกฤษ", "GBP")]
    alias = {"ดอลลาร์": "USD", "ดอลล่า": "USD", "usd": "USD", "ยูโร": "EUR", "eur": "EUR",
             "เยน": "JPY", "jpy": "JPY", "หยวน": "CNY", "cny": "CNY", "ปอนด์": "GBP", "gbp": "GBP"}
    lines = ["💱 อัตราแลกเปลี่ยนวันนี้ครับ"]
    for th, code in names:
        if rates.get(code):
            lines.append(f"• 1 {code} ({th}) ≈ {1.0 / rates[code]:,.2f} บาท")
    m = re.search(r"([\d,\.]+)\s*([a-zก-๙]+)", t)
    if m:
        amt_raw, word = m.group(1), m.group(2)
        code = alias.get(word)
        if code and rates.get(code) and re.search(r"\d", amt_raw):
            amt = float(amt_raw.replace(",", ""))
            lines.append(f"➡️ {amt:,.2f} {code} ≈ {amt / rates[code]:,.2f} บาทครับ")
    return "\n".join(lines)


def hand_random(text=""):
    t = (text or "").lower()
    if "เหรียญ" in t or "หัวก้อย" in t:
        return "🪙 ออก '" + random.choice(["หัว", "ก้อย"]) + "' ครับ"
    m = re.search(r"(\d+)\s*(?:ถึง|-|to)\s*(\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return f"🎲 สุ่มได้เลข {random.randint(a, b)} ครับ (จาก {a}-{b})"
    if "เต๋า" in t or "ทอย" in t:
        m2 = re.search(r"(\d+)\s*(?:ดอก|ลูก|ครั้ง)", t)
        n = min(int(m2.group(1)), 6) if m2 else 1
        rolls = [random.randint(1, 6) for _ in range(max(n, 1))]
        return f"🎲 ทอยได้ {sum(rolls)} แต้มครับ ({' + '.join(map(str, rolls))})"
    return f"🎲 สุ่มได้เลข {random.randint(1, 100)} ครับ"


def hand_torch(text=""):
    t = (text or "").lower()
    # "เปิดไฟฉาย" มี "ปิดไฟฉาย" ซ่อนอยู่ (เ-ปิดไฟฉาย) — ถ้ามี "เปิด" ถือว่าเปิดเสมอ
    state = "off" if ("เปิด" not in t and "ปิด" in t) else "on"
    try:
        subprocess.run(["termux-torch", state], capture_output=True, timeout=15)
        return "🔦 เปิดไฟฉายแล้วครับ" if state == "on" else "🌑 ปิดไฟฉายแล้วครับ"
    except FileNotFoundError:
        return "❌ ต้องติดตั้งแอป Termux:API + รัน pkg install termux-api ก่อนนะครับ"
    except Exception as e:
        return f"❌ ควบคุมไฟฉายไม่สำเร็จ: {e}"


def hand_camera(text=""):
    t = (text or "").lower()
    cam = "1" if any(k in t for k in ("หน้า", "เซลฟี่", "เซลฟี", "selfie", "front")) else "0"
    os.makedirs(_OUTDIR, exist_ok=True)
    path = os.path.join(_OUTDIR, f"photo_{int(time.time())}.jpg")
    try:
        subprocess.run(["termux-camera-photo", "-c", cam, path],
                       capture_output=True, timeout=25)
        if os.path.exists(path) and os.path.getsize(path) > 2000:
            label = "กล้องหน้า" if cam == "1" else "กล้องหลัง"
            return (f"📸 ถ่ายด้วย{label}ให้แล้วครับ", path)
        return "❌ ถ่ายไม่สำเร็จ (เช็คสิทธิ์กล้องของ Termux ในตั้งค่ามือถือด้วยครับ)"
    except FileNotFoundError:
        return "❌ ต้องติดตั้งแอป Termux:API + รัน pkg install termux-api ก่อนนะครับ"
    except Exception as e:
        return f"❌ ถ่ายรูปไม่สำเร็จ: {e}"


def hand_location(text=""):
    try:
        r = subprocess.run(["termux-location", "-p", "network"],
                           capture_output=True, timeout=40)
        data = json.loads(r.stdout.decode())
        lat, lon = data["latitude"], data["longitude"]
        return (f"📍 ตำแหน่งตอนนี้ครับ\n"
                f"ละติจูด {lat:.5f} / ลองจิจูด {lon:.5f}\n"
                f"🗺️ แผนที่: https://maps.google.com/?q={lat:.5f},{lon:.5f}")
    except FileNotFoundError:
        return "❌ ต้องติดตั้งแอป Termux:API + รัน pkg install termux-api ก่อนนะครับ"
    except Exception as e:
        return f"❌ หาตำแหน่งไม่สำเร็จ: {e} (เปิด GPS/อนุญาตตำแหน่งให้ Termux ด้วยครับ)"


HANDS["torch"] = hand_torch
HANDS["camera"] = hand_camera
HANDS["location"] = hand_location

HANDS["weather"] = hand_weather
HANDS["rates"] = hand_rates
HANDS["random"] = hand_random

log.info("🦾 มือที่พร้อมใช้: %s", ", ".join(sorted(HANDS)) or "(โหมดคุยอย่างเดียว)")


# ============================================================
# 🧹 ล้างคำหลุด
# ============================================================
def clean_reply(text):
    t = (text or "").strip()
    t = re.sub(r"^\s*(คำตอบ|คำตอบคือ|Response|Reply|Answer|Output)\s*[:：]\s*", "", t,
               flags=re.IGNORECASE)
    t = re.sub(r"^\s*(Jarvis|จาร์วิส)\s*[:：]\s*", "", t)
    return t.replace("ค่ะ", "ครับ").replace("คะ", "ครับ").replace("ครับ/ค่ะ", "ครับ")


# ============================================================
# 🎙️ เสียงผู้หญิง (Google Thai Voice ผ่าน gTTS) — พูด + ทำ voice note
# ============================================================
VOICE_ENABLED = {}  # channel_id -> bool (ค่าเริ่มต้น: เปิด)
LAST_HAND = {}  # channel_id -> มือล่าสุดที่เพิ่งทำ (ให้คำสั่งสั้นอย่าง "ปิด" รู้บริบท)


def _looks_like_job_dump(text):
    """ตรวจว่าเป็นก้อนข้อความงานจากระบบทางหรือไม่ — ใช้แค่แนะนำ ไม่จับเป็นงาน"""
    t = text or ""
    if len(t) < 60:
        return False
    hits = 0
    if re.search(r"\d{15,}", t):
        hits += 1
    if any(k in t for k in ("HSI/", "FIBERTV", "ระยะสายเริ่มต้น", "ระยะสายสิ้นสุด",
                            "ชื่อ-นามสกุล", "Order Detail")):
        hits += 1
    if t.count("*") >= 3 or re.search(r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:", t):
        hits += 1
    return hits >= 2


def _bare_torch_state(text):
    """คืน 'on'/'off' ถ้าผู้ใช้พิมพ์คำสั้น ๆ ล้วน เช่น 'ปิด' 'เปิด' (จะใช้กับอุปกรณ์ล่าสุด) ไม่งั้น None"""
    bare = (text or "").strip().lower()
    if bare in ("ปิด", "ปิดดิ", "ปิดซะ", "ดับ", "off", "ปิดไฟ"):
        return "off"
    if bare in ("เปิด", "เปิดดิ", "on", "เปิดไฟ"):
        return "on"
    return None
_OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_output")
_edge_missing = False
_gtts_missing = False


def voice_note_file(text):
    """สร้างไฟล์ mp3 — ลำดับ: 1) edge-tts เสียงผู้หญิงไทย Achara (Neural ธรรมชาติมาก)
    2) gTTS เสียง Google 3) None (= speak_sync จะ fallback ไป termux-tts-speak)"""
    global _edge_missing, _gtts_missing
    if not text:
        return None
    spoken = clean_reply(text)[:600]
    try:
        os.makedirs(_OUTDIR, exist_ok=True)
        now = time.time()
        for f in glob.glob(os.path.join(_OUTDIR, "voice_*.mp3")):
            try:
                if now - os.path.getmtime(f) > 1800:
                    os.remove(f)
            except Exception:
                pass
        path = os.path.join(_OUTDIR, f"voice_{int(now * 10)}.mp3")
    except Exception as e:
        log.warning("output dir error: %s", e)
        return None

    # 1) Edge TTS — เสียงผู้หญิงไทย "Achara" ธรรมชาติที่สุด
    if not _edge_missing:
        for attempt in (1, 2):  # เน็ตมือถือสะดุดบ่อย — ลอง 2 ครั้งก่อนสลับ
            try:
                subprocess.run(
                    ["edge-tts", "--voice", "th-TH-AcharaNeural", "--text", spoken,
                     "--write-media", path],
                    capture_output=True, timeout=45)
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    return path
                log.warning("edge-tts ไฟล์ไม่สมบูรณ์ (ครั้งที่ %d/2)", attempt)
            except FileNotFoundError:
                _edge_missing = True
                log.warning("ยังไม่มี edge-tts — ติดตั้ง: pip install edge-tts (เสียงจะเพราะขึ้นมาก)")
                break
            except Exception as e:
                log.warning("edge-tts error: %s (ครั้งที่ %d/2)", e, attempt)
            if attempt == 1:
                time.sleep(2)

    # 2) gTTS — เสียง Google
    if not _gtts_missing:
        try:
            from gtts import gTTS
            gTTS(text=spoken, lang="th").save(path)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return path
        except ImportError:
            _gtts_missing = True
            log.warning("ยังไม่ได้ติดตั้ง gTTS — รัน: pip install gTTS")
        except Exception as e:
            log.warning("gTTS Error: %s", e)
    return None


def speak_sync(text):
    """พูดออกลำโพง (termux-media-player) + คืน path ไฟล์เสียงไว้แนบใน Discord"""
    spoken = clean_reply(text)[:600]
    path = voice_note_file(spoken)
    if path:
        try:
            subprocess.run(["termux-media-player", "stop"], capture_output=True, timeout=10)
        except Exception:
            pass
        try:
            subprocess.Popen(["termux-media-player", "play", path])
            return path
        except FileNotFoundError:
            log.warning("termux-media-player ไม่พบ — ต้องติดตั้งแอป Termux:API ด้วย")
        except Exception as e:
            log.warning("play error: %s", e)
    # fallback: เสียงระบบเดิม
    try:
        subprocess.Popen(["termux-tts-speak", spoken[:280]])
    except Exception:
        pass
    return None


async def speak_and_note(text, channel_id, channel=None):
    """เล่นเสียงออกลำโพง + ส่งไฟล์เสียงเป็น voice note ในแชนเนล"""
    if not VOICE_ENABLED.get(channel_id, True):
        return
    try:
        path = await asyncio.to_thread(speak_sync, text)
        if path and channel:
            await channel.send(file=discord.File(path))
    except Exception as e:
        log.warning("speak_and_note: %s", e)


# ============================================================
# 🧠 คุยกับ AI: ตอบ JSON {reply, action, action_text}
# ============================================================
SYSTEM_PROMPT = """คุณคือ Jarvis AI ผู้ช่วยส่วนตัว ทำงานผ่าน Discord (เสียงผู้หญิงใจดี)

กฎการพูด:
- ตอบเป็นภาษาไทยที่เป็นธรรมชาติ เป็นกันเอง อธิบายเข้าใจง่าย
- สุภาพและจริงใจ ลงท้ายด้วย "ครับ" ทุกประโยค
- ห้ามใช้คำว่า "ค่ะ" หรือ "คะ" เด็ดขาด
- ห้ามขึ้นต้นด้วยคำว่า "คำตอบ:" หรือ "Response:" เด็ดขาด

มือที่คุณสั่งได้ (ตอบ field "action"):
- "check_battery" : ถามแบตมือถือ (แบตเหลือเท่าไหร่)
- "open_youtube"  : อยากเปิด/ดู YouTube บนมือถือ
- "reminder"      : ตั้งเตือน/ดูเตือน — action_text รูปแบบ "ตั้งเตือน <เรื่อง> YYYY-MM-DD HH:MM" (แปลง พรุ่งนี้/เช้า/บ่าย เป็นวันเวลาจริงให้เอง) หรือ "ดูรายการเตือน"
- "expense"       : รายจ่าย — action_text "<รายการ> <จำนวนเงิน>" หรือ "สรุปรายจ่ายเดือนนี้"
- "news"          : ขออ่านข่าว
- "weather"       : ถามอากาศ/ฝน/ร้อนไหม — action_text ใส่ชื่อเมืองถ้ามี
- "rates"         : ถามอัตราแลกเปลี่ยน/เงินต่างประเทศเท่าไหร่บาท
- "random"        : ทอยเต๋า/สุ่มเลข/เหี่ยวหัวก้อย — action_text เช่น "ทอยเต๋า 2 ดอก" หรือ "สุ่มเลข 1 ถึง 100"
- "torch"         : เปิด/ปิดไฟฉาย — action_text "on" หรือ "off"
- "camera"        : ถ่ายรูปจากมือถือส่งเข้าแชต — action_text "back" (หลัง) หรือ "front" (หน้า)
- "location"      : ถามว่าฉันอยู่ที่ไหน/ตำแหน่งปัจจุบัน/พิกัด

เมื่อมี action ให้ reply สั้น ๆ ว่ากำลังทำให้ (เช่น "กำลังเช็คให้ครับ")
ถ้าเป็นแค่การคุย ให้ action = null แล้วตอบใน reply ได้เต็มที่
ตอบกลับเป็น JSON รูปแบบนี้เท่านั้น ห้ามเพิ่มข้อความอื่น:
{"reply": "...", "action": null, "action_text": ""}"""


def parse_ai_json(raw):
    """แกะคำตอบ AI — รองรับ list-of-blocks ของ gpt-oss ด้วย"""
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
    """ดึง {reply, action, action_text} แบบยืดหยุ่น — ไม่มี JSON ก็ใช้ข้อความดิบ"""
    if not isinstance(data, dict):
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and ("reply" in item or "action" in item):
                    data = item
                    break
        if not isinstance(data, dict):
            raw = raw_text if isinstance(raw_text, str) else ""
            if isinstance(raw_text, list):
                raw = "\n".join(
                    b.get("text", "") for b in raw_text
                    if isinstance(b, dict) and b.get("type") == "text")
            raw = (raw or "").strip()
            if not raw:
                return None
            return {"reply": raw[:1500], "action": None, "action_text": ""}
    reply = data.get("reply") or data.get("response") or data.get("message") or ""
    action = data.get("action") or data.get("intent") or None
    atext = data.get("action_text") or data.get("action_input") or data.get("input") or ""
    if isinstance(action, dict):
        atext = atext or action.get("text") or action.get("input") or ""
        action = action.get("name") or action.get("type") or None
    if isinstance(action, str):
        action = action.strip().lower() or None
    if not reply and raw_text:
        reply = str(raw_text).strip()
    return {"reply": (str(reply) or "รับทราบครับ").strip(),
            "action": action, "action_text": str(atext).strip()}


def fallback_intent(text):
    """กัน AI ส่ง action มาไม่ครบ — เดาจากคีย์เวิร์ดไทยแบบระบบเดิม"""
    t = text.lower()
    if "แบต" in t or "battery" in t:
        return "check_battery", ""
    if "youtube" in t or "ยูทูป" in t:
        return "open_youtube", ""
    if ("ตั้งเตือน" in t) or ("เตือนฉัน" in t) or ("ดูรายการเตือน" in t) or ("รายการเตือน" in t):
        return "reminder", text
    if any(k in t for k in ("รายจ่าย", "ค่าใช้จ่าย", "จดบิล")) or ("เดือนนี้" in t and any(c.isdigit() for c in t)):
        return "expense", text
    if any(k in t for k in ("ข่าว", "news")) and len(t) < 40:
        return "news", text
    if any(k in t for k in ("อากาศ", "ฝนตก", "ร้อนไหม", "weather", "หนาวไหม")):
        return "weather", text
    if any(k in t for k in ("แลกเปลี่ยน", "อัตราแลก", "ดอลลาร์", "ดอลล่า", "เยน", "ยูโร", "หยวน")) \
            or ("usd" in t and ("เท่าไหร่" in t or "บาท" in t)):
        return "rates", text
    if any(k in t for k in ("ทอยเต๋า", "ทอย", "สุ่มเลข", "หัวก้อย", "เหี่ยวเหรียญ", "เหรียญ")) and len(t) < 60:
        return "random", text
    if "ไฟฉาย" in t or "ไฟแฟลช" in t or "torch" in t:
        # "เปิดไฟฉาย" มีทั้ง "เปิด" และ "ปิดไฟฉาย" ซ่อนอยู่ — ถ้ามี "เปิด" ให้ถือว่าเปิดเสมอ
        state = "off" if ("เปิด" not in t and "ปิด" in t) else "on"
        return "torch", state
    if any(k in t for k in ("ถ่ายรูป", "ถ่ายภาพ", "เซลฟี่", "เซลฟี", "selfie")):
        return "camera", ("front" if any(k in t for k in ("หน้า", "เซลฟี่", "เซลฟี", "selfie")) else "back")
    if any(k in t for k in ("อยู่ที่ไหน", "ตำแหน่ง", "พิกัด", "จีพีเอส", "gps")) and len(t) < 60:
        return "location", ""
    return None, ""


def ask_jarvis_sync(user_text, history):
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
            result = coerce_result(parse_ai_json(content), content)
            if result is None:
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
                use_json_mode = False
                continue
            raise
    raise last_err or RuntimeError("AI error")


memories = {}


async def process_message(user_text, channel_id, images=None):
    """สมอง + มือ ทำงานร่วมกัน — คืน (ข้อความ, ควรพูดไหม)"""
    # คำสั่งเสียงด่วน (เช็ค "เปิดเสียง" ก่อน "ปิดเสียง" เพราะ "เปิดเสียง" มี "ปิดเสียง" ซ่อนอยู่!)
    t = user_text.strip().lower()
    if "เปิดเสียง" in t or "เปิดเสียงหน่อย" in t or "เปิด เสียง" in t:
        VOICE_ENABLED[channel_id] = True
        return "🔊 เปิดเสียงแล้วครับ ผมจะพูดตามทุกคำตอบให้ฟังเองครับ", True, None
    if "ปิดเสียง" in t or "หุบเสียง" in t or "เงียบๆ" in t or "เงียบ ๆ" in t:
        VOICE_ENABLED[channel_id] = False
        return "🔇 ปิดเสียงแล้วครับ ต่อจากนี้ตอบเป็นข้อความเฉย ๆ ครับ", False, None

    # 👀 มีรูปแนบ → อ่านรูป (พิมพ์คำถามมาด้วย = ถามเรื่องรูป ไม่งั้นถอดข้อความ)
    if images:
        q = user_text if len((user_text or "").strip()) > 2 else None
        outs, errs = [], []
        for img_b, ct in images[:2]:
            try:
                t = await asyncio.to_thread(ocr_image, img_b, ct, q)
            except Exception as e:
                log.error("vision error: %s", e)
                errs.append(str(e)[:110])
                t = None
            if t:
                outs.append(t.strip())
        if outs:
            body = "\n".join(outs).replace("```", "``")[:1600]
            tip = ""
            if not q and _looks_like_job_dump(body):
                tip = ("\n\n💡 นี่ดูเป็นใบงานของทาง — กดคัดลอกข้อความในกล่องด้านบน "
                       "แล้วไปพิมพ์ /job → ปุ่ม 📥 วางข้อความงาน วางลงไปได้เลยครับ")
            return ("📷 อ่านรูปแล้วครับ:\n```text\n" + body + "\n```" + tip,
                    False, None)
        reason = errs[0] if errs else "ไม่ทราบสาเหตุ"
        return ("ขออภัยครับ อ่านรูปไม่สำเร็จ\nเหตุผล: " + reason +
                "\n(ลองส่งรูปใหม่ได้เลยครับ หรือก๊อปข้อความในใบงานมาวางใน /job ก็ได้ครับ)",
                True, None)

    # คำสั่งสั้น "ปิด"/"เปิด" — ถ้าเพิ่งเล่นไฟฉาย ให้หมายถึงไฟฉาย (ไม่ต้องรบกวนสมอง)
    bare_state = _bare_torch_state(user_text)
    if bare_state and LAST_HAND.get(channel_id) == "torch" and "torch" in HANDS:
        log.info("🦾 ลงมือทำ: torch (คำสั่งสั้น -> %s)", bare_state)
        res = await asyncio.to_thread(
            HANDS["torch"], "ปิดไฟฉาย" if bare_state == "off" else "เปิดไฟฉาย")
        return res, True, None

    # ก้อนข้อความงานวางในแชต → ไม่จับเป็นงาน (ตามเจ้าของสั่ง) แต่แนะนำปุ่มที่ถูก
    if _looks_like_job_dump(user_text):
        return ("📄 นี่ดูเป็นข้อความงานจากระบบทางนะครับ — ผมจะไม่จับใส่ระบบงานเองแน่นอนครับ\n"
                "ถ้าอยากเปิดเป็นงาน: พิมพ์ **/job** แล้วกดปุ่ม **📥 วางข้อความงาน** "
                "แล้ววางก้อนนี้ลงไป ผมจะแยกชื่อ/ที่อยู่/เบอร์/ระยะสายให้ครบครับ", False, None)

    history = memories.setdefault(channel_id, deque(maxlen=MAX_TURNS * 2))
    try:
        result = await asyncio.to_thread(ask_jarvis_sync, user_text, history)
    except Exception as e:
        log.error("Groq Error: %s", e)
        return "ขออภัยครับ ระบบ AI ขัดข้องครับ", True, None

    action = result.get("action")
    action_text = result.get("action_text") or user_text
    reply = result.get("reply") or "รับทราบครับ"

    if action == "task":  # ระบบงานของทางถูกถอดออก — ให้ตอบเป็นการคุยแทน
        action = None
    if not action:
        action, action_text = fallback_intent(user_text)

    final = None
    attach = None
    if action and action in HANDS:
        log.info("🦾 ลงมือทำ: %s", action)
        LAST_HAND[channel_id] = action  # จำไว้ให้คำสั่งสั้น "ปิด"/"เปิด" รอบหน้า
        # ไฟฉาย: ใช้คำของผู้ใช้จริงตัดสิน เปิด/ปิด (กัน AI ส่ง on/off มาผิด)
        hand_input = action_text
        if action == "torch" and any(k in user_text for k in ("เปิด", "ปิด", "ดับ")):
            hand_input = user_text + " " + (action_text or "")
        try:
            res_hand = await asyncio.to_thread(HANDS[action], hand_input)
            if isinstance(res_hand, tuple):      # (ข้อความ, ไฟล์แนบ) เช่น รูปถ่าย
                final, attach = res_hand
            else:
                final = res_hand
        except Exception as e:
            log.error("Action Error (%s): %s", action, e)
            final = None
    elif action:
        reply = f"{reply}\n(มือ '{action}' ยังไม่พร้อมใช้ในเครื่องนี้ครับ)"

    out = clean_reply(final if final else reply)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": out[:500]})
    return out, True, attach


async def reply_long(channel, text):
    for i in range(0, len(text), 1900):
        await channel.send(text[i:i + 1900])


# ============================================================
# ⏰ แจ้งเตือนเองเมื่อถึงเวลา (อ่าน reminder.db ทุก 20 วินาที)
# ============================================================
_last_channel_id = None


def due_reminders():
    items = []
    try:
        conn = sqlite3.connect("reminder.db")
        c = conn.cursor()
        c.execute("SELECT id, text, remind_time FROM reminders WHERE status='waiting'")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for rid, text, rtime in c.fetchall():
            if str(rtime)[:16] <= now:
                c.execute("UPDATE reminders SET status='done' WHERE id=?", (rid,))
                items.append(f"⏰ ถึงเวลาแล้วครับ: {text}")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("reminder check: %s", e)
    return items


async def reminder_loop():
    await bot.wait_until_ready()
    log.info("⏰ เฝ้าระวังการแจ้งเตือนเปิดแล้ว (ทุก 20 วินาที)")
    while True:
        try:
            items = await asyncio.to_thread(due_reminders)
            for msg in items:
                ch = bot.get_channel(_last_channel_id) if _last_channel_id else None
                if ch is None:
                    for g in bot.guilds:
                        for tc in g.text_channels:
                            if tc.permissions_for(g.me).send_messages:
                                ch = tc
                                break
                        if ch:
                            break
                if ch:
                    await ch.send(msg)
                    await speak_and_note(msg, ch.id, ch)
        except Exception as e:
            log.warning("reminder loop: %s", e)
        await asyncio.sleep(20)


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
    reply, _, attach = await process_message(message, interaction.channel_id)
    path = None
    if VOICE_ENABLED.get(interaction.channel_id, True):
        path = await asyncio.to_thread(speak_sync, reply)
    files = [discord.File(p) for p in (path, attach) if p][:2]
    if files:
        await interaction.followup.send(reply[:1900], files=files)
    else:
        await interaction.followup.send(reply[:1900])


@tree.command(name="voice", description="🔊 เปิด/ปิดเสียงพูดของ Jarvis")
@app_commands.choices(mode=[
    app_commands.Choice(name="เปิดเสียง (พูดตามทุกคำตอบ)", value="on"),
    app_commands.Choice(name="ปิดเสียง (ตอบเป็นข้อความเฉย ๆ)", value="off"),
])
async def slash_voice(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    on = (mode.value == "on")
    VOICE_ENABLED[interaction.channel_id] = on
    if on:
        asyncio.create_task(speak_and_note("เปิดเสียงแล้วครับ", interaction.channel_id))
    await interaction.response.send_message(
        "🔊 เปิดเสียงแล้วครับ ผมจะพูดตามทุกคำตอบให้ฟังเองครับ" if on
        else "🔇 ปิดเสียงแล้วครับ ต่อจากนี้ตอบเป็นข้อความเฉย ๆ ครับ")


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
    out = clean_reply(out)
    asyncio.create_task(speak_and_note(out, interaction.channel_id))
    await interaction.followup.send(out[:1900])


@tree.command(name="weather", description="🌤️ อากาศวันนี้ (ระบุเมืองได้)")
async def slash_weather(interaction: discord.Interaction, เมือง: str = "กรุงเทพ"):
    await interaction.response.defer(thinking=True)
    try:
        out = await asyncio.to_thread(hand_weather, เมือง)
    except Exception as e:
        out = f"❌ ดึงอากาศไม่สำเร็จ: {e}"
    out = clean_reply(out)
    asyncio.create_task(speak_and_note(out, interaction.channel_id))
    await interaction.followup.send(out[:1900])


# ============================================================
# 👀 ตา: อ่านรูปที่แนบมา (Groq vision — llama-4 scout/maverick)
# ============================================================
import base64 as _base64

VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]
_vision_model = None
_TINY_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _vision_candidates():
    """รายชื่อโมเดลภาพ: ตัวที่รู้จัก + ไล่จากรายชื่อจริงของ Groq (กันโมเดลถูกปลด)"""
    cands = list(VISION_MODELS)
    try:
        from urllib.request import Request, urlopen
        req = Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + GROQ_API_KEY})
        data = json.loads(urlopen(req, timeout=20).read().decode())
        for m in data.get("data", []):
            mid = (m.get("id") or "") if isinstance(m, dict) else ""
            if not mid or mid in cands:
                continue
            if any(k in mid.lower() for k in ("llama-4", "vision", "scout",
                                              "maverick", "vl", "ocr")):
                cands.append(mid)
    except Exception as e:
        log.warning("ดึงรายชื่อโมเดลภาพไม่สำเร็จ (%s) — ใช้รายชื่อที่รู้จัก", e)
    return cands


_vision_last_error = None


def find_vision_model():
    """หาโมเดลอ่านภาพที่ยังมีชีวิต — โปรบด้วยรูปจิ๋ว (ตอบได้ = อ่านรูปได้จริง)"""
    global _vision_model, _vision_last_error
    if _vision_model:
        return _vision_model
    _vision_last_error = None
    for cand in _vision_candidates():
        try:
            groq_client.chat.completions.create(
                model=cand,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "รูปนี้เห็นอะไร ตอบสั้นที่สุด"},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/png;base64," + _TINY_PNG}},
                ]}])
            _vision_model = cand
            log.info("ใช้ตา (vision): %s", cand)
            return cand
        except Exception as e:
            s = str(e).lower()
            if any(k in s for k in ("decommission", "model_not_found",
                                    "does not exist", "do not have access")):
                log.info("ข้ามโมเดลภาพ %s (ถูกปลด/ไม่มีสิทธิ์)", cand)
                continue
            _vision_last_error = str(e)[:120]
            _vision_model = cand
            log.info("ใช้ตา (vision): %s (หมายเหตุ: %s)", cand, str(e)[:70])
            return cand
    log.warning("ไม่มีโมเดลอ่านรูปที่ใช้ได้เลย — Groq อาจปลดหมดแล้ว: %s",
                _vision_last_error)
    return None


def _reply_text(resp):
    """แกะข้อความจากคำตอบโมเดล — รองรับ content เป็น list-of-blocks ด้วย"""
    try:
        raw = resp.choices[0].message.content
    except Exception:
        return ""
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
    return clean_reply(str(raw or "")).strip()


def ocr_image(img_bytes, content_type="image/jpeg", question=None):
    """อ่านรูปด้วยโมเดล vision — ไม่ถามอะไร = ถอดข้อความทั้งหมดในรูป"""
    model = find_vision_model()
    if not model:
        raise RuntimeError(
            "ไม่มีโมเดลอ่านรูปที่ใช้ได้ใน key นี้ (ถูกปลด/ไม่มีสิทธิ์ทั้งหมด)")
    if not question:
        question = ("ถอดข้อความทั้งหมดในรูปนี้เป็นข้อความธรรมดา "
                    "รักษาโครงสร้างบรรทัดและป้ายกำกับเดิมทุกบรรทัด "
                    "อย่าเพิ่มคำอธิบายหรือสรุปของคุณเอง "
                    "ถ้ารูปไม่มีข้อความเป็นหลัก ให้อธิบายรูปสั้น ๆ เป็นภาษาไทย")
    b64 = _base64.b64encode(img_bytes).decode()
    for attempt in (1, 2):
        try:
            resp = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {
                        "url": "data:" + content_type + ";base64," + b64}},
                ]}],
                temperature=0.1, max_tokens=2048)
            return _reply_text(resp) or None
        except Exception as e:
            s = str(e).lower()
            if ("429" in s or "rate limit" in s) and attempt == 1:
                time.sleep(3)
                continue
            raise


# ============================================================
# 🧰 ระบบงานแบบปุ่ม — เข้าด้วย /job เท่านั้น (แยกจากแชต 100%)
#    เก็บใน jobs.db ข้างสคริปต์ (ห้ามลบไฟล์นี้!)
# ============================================================
import json as _json
import sqlite3 as _sqlite3
from datetime import datetime as _dt

JOBS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")


def _jobs_conn():
    conn = _sqlite3.connect(JOBS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer TEXT DEFAULT '', jtype TEXT DEFAULT '',
        address TEXT DEFAULT '', phone TEXT DEFAULT '', circuit TEXT DEFAULT '',
        start_len REAL, end_len REAL, total_len REAL,
        status TEXT DEFAULT 'open',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        closed_at TEXT,
        extra TEXT DEFAULT '{}')""")
    return conn


def _now_local():
    return _dt.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_job_text(text):
    """แยกข้อความงานจากระบบทาง — ก๊อปมาวางทั้งก้อนได้เลย (รองรับทั้งไลน์และหน้า Order Detail)"""
    data = {"customer": "", "jtype": "", "address": "", "phone": "", "circuit": "",
            "start_len": None, "end_len": None, "total_len": None, "extra": {}}
    ex = data["extra"]

    # 1) หัวแบบ "1. ชื่อ (09:00 - 12:00) — ประเภทงาน"
    m = re.search(r"^\s*\d+\.\s*(.+?)(?:\s*\(([^)]*)\))?\s*[—–-]+\s*(.+)$",
                  text, re.M)
    if m:
        data["customer"] = m.group(1).strip()
        if m.group(2):
            ex["เวลา"] = m.group(2).strip()
        data["jtype"] = m.group(3).strip()

    # 2) ฟิลด์แบบ "* คีย์: ค่า"
    keymap = {"ที่อยู่": "address", "เบอร์โทร": "phone", "circuit": "circuit",
              "ระยะสายเริ่มต้น": "start_len", "ระยะสายสิ้นสุด": "end_len",
              "ระยะสายรวมทั้งหมด": "total_len"}
    for km in re.finditer(r"^[ \t]*\*[ \t]*([^:\n]+?)[ \t]*:[ \t]*(.*)$", text, re.M):
        k = km.group(1).strip()
        v = km.group(2).strip()
        tgt = keymap.get(k.lower())
        if tgt and tgt.endswith("_len"):
            num = _to_num(v)
            if num is not None:
                data[tgt] = num
        elif tgt:
            data[tgt] = v or data[tgt]
        elif v:
            ex[k] = v

    # 3) ป้ายกำกับบรรทัดเดี่ยวแล้วค่าอยู่บรรทัดถัดไป (สไตล์ Order Detail)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    label_map = {"ชื่อ-นามสกุล": "customer", "ชื่อนามสกุล": "customer",
                 "ชื่อลูกค้า": "customer", "ชื่อ": "customer",
                 "ที่อยู่": "address", "ที่อยู่จัดส่ง": "address",
                 "เบอร์โทร": "phone", "เบอร์โทรศัพท์": "phone", "phone": "phone"}
    for i, l in enumerate(lines):
        lab = l.replace(" ", "").lower()
        f = None
        for lk, fv in label_map.items():
            if lab == lk.replace(" ", "").lower():
                f = fv
                break
        if f and i + 1 < len(lines) and not data[f]:
            data[f] = lines[i + 1][:300]

    # 4) วันเวลานัดหมาย เช่น "29/09/2026 09:00-12:00"
    if not ex.get("เวลา"):
        m2 = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2})", text)
        if m2:
            ex["วันเวลา"] = m2.group(1) + " " + m2.group(2)

    # 5) เบอร์โทร 0XXXXXXXXX
    if not data["phone"]:
        mp = re.search(r"\b(0\d{8,9})\b", text)
        if mp:
            data["phone"] = mp.group(1)

    # 6) ประเภทงานแบบ Order Detail เช่น HSI/Change Address To, FTTH, FIBERTV
    if not data["jtype"]:
        mj = re.search(r"(HSI/[^,\n]*|FTTH[^\n,]{0,60}|FIBERTV[^\n,]{0,60}|Change Address[^\n,]{0,60}|New Connection[^\n,]{0,60}|Repair[^\n,]{0,60}|ย้ายออนไลน์[^,\n]{0,60}|ติดตั้งใหม่[^,\n]{0,60})", text)
        if mj:
            data["jtype"] = mj.group(1).strip()[:80]

    # 7) ความเร็วเน็ต เช่น 300Mbps
    ms = re.search(r"\b(\d{2,4})\s*[- ]?\s*Mbps\b", text, re.I)
    if ms:
        ex["ความเร็ว"] = ms.group(1) + "Mbps"

    # 8) พิกัดคู่ละติจูด/ลองจิจูด (ไทย: lat ~5-21, lon ~96-106)
    mc = [x for x in re.findall(r"\b(\d{1,3}\.\d{4,})\b", text)
          if 5.0 <= float(x) <= 21.0 or 96.0 <= float(x) <= 106.0]
    if len(mc) >= 2:
        ex["พิกัด"] = mc[0] + "," + mc[1]

    # 9) เลขที่ใบงาน (ตัวเลขยาว 15+ หลัก) และ LOI/LOID
    mo = re.search(r"\b(\d{15,})\b", text)
    if mo:
        ex["เลขที่ใบงาน"] = mo.group(1)
    ml = re.search(r"\bLOI[D]?\b\D{0,8}(\d{6,})", text)
    if ml:
        ex["LOID"] = ml.group(1)

    # 10) ชื่อสำรอง: บรรทัดสั้น ๆ ที่เป็นภาษาไทย ไม่มีโครงสร้างอื่นปน
    if not data["customer"]:
        for l in lines:
            if (len(l) <= 60 and re.search(r"[ก-๙]", l) and ":" not in l
                    and "," not in l and "/" not in l and not re.search(r"\d{5,}", l)):
                data["customer"] = re.sub(r"^\d+\.\s*", "", l)[:80]
                break
        if not data["customer"]:
            first = lines[0] if lines else ""
            data["customer"] = re.sub(r"^\d+\.\s*", "", first)[:80]
    return data


_JOB_COLS = ("id,customer,jtype,address,phone,circuit,start_len,end_len,"
             "total_len,status,created_at,closed_at,extra")


def _job_row(r):
    d = dict(zip(_JOB_COLS.split(","), r))
    try:
        d["extra"] = _json.loads(d.get("extra") or "{}")
    except Exception:
        d["extra"] = {}
    return d


def _jobs_add(d):
    conn = _jobs_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO jobs(customer,jtype,address,phone,circuit,"
                "start_len,end_len,total_len,extra) VALUES(?,?,?,?,?,?,?,?,?)",
                (d.get("customer", ""), d.get("jtype", ""), d.get("address", ""),
                 d.get("phone", ""), d.get("circuit", ""), d.get("start_len"),
                 d.get("end_len"), d.get("total_len"),
                 _json.dumps(d.get("extra", {}), ensure_ascii=False)))
    conn.commit()
    jid = cur.lastrowid
    conn.close()
    return jid


def _jobs_get(jid):
    cur = _jobs_conn().execute(
        f"SELECT {_JOB_COLS} FROM jobs WHERE id=?", (jid,))
    r = cur.fetchone()
    cur.close()
    return _job_row(r) if r else None


def _jobs_open(limit=25):
    cur = _jobs_conn().execute(
        f"SELECT {_JOB_COLS} FROM jobs WHERE status='open' ORDER BY id DESC LIMIT ?",
        (limit,))
    rows = [_job_row(r) for r in cur.fetchall()]
    cur.close()
    return rows


def _jobs_update(jid, **f):
    if not f:
        return
    cols = ",".join(f"{k}=?" for k in f)
    conn = _jobs_conn()
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*f.values(), jid))
    conn.commit()
    conn.close()


def _jobs_delete(jid):
    conn = _jobs_conn()
    conn.execute("DELETE FROM jobs WHERE id=?", (jid,))
    conn.commit()
    conn.close()


def _jobs_today():
    cur = _jobs_conn().execute(
        "SELECT COUNT(*), COALESCE(SUM(total_len),0) FROM jobs "
        "WHERE status='closed' AND date(closed_at)=date('now','localtime')")
    n, meters = cur.fetchone()
    cur.close()
    return n or 0, meters or 0


_EXTRA_ORDER = ["เวลา", "วันเวลา", "LOID", "Port L2", "L", "กล่องเราเตอร์", "Mesh",
                "True ID", "กล้อง", "ใช้สายเดิมสายใหม่", "การเก็บเงิน", "เลขดั้ม",
                "ความเร็ว", "พิกัด", "เลขที่ใบงาน"]


def _fmt_len(v):
    return "-" if v is None else f"{v:g}"


def _job_card(j):
    icon = "🔓" if j["status"] == "open" else "✅"
    lines = [f"{icon} #{j['id']} • {(j['customer'] or '(ไม่มีชื่อ)').replace(chr(10), ' ')}"]
    if j["jtype"]:
        lines.append(f"งาน: {j['jtype']}")
    if j["address"]:
        lines.append(f"ที่อยู่: {j['address']}".replace(chr(10), " / "))
    if j["circuit"]:
        lines.append(f"Circuit: {j['circuit']}")
    if j["phone"]:
        lines.append(f"โทร: {j['phone']}")
    lines.append(f"ระยะสาย: เริ่ม {_fmt_len(j['start_len'])} • "
                 f"สิ้นสุด {_fmt_len(j['end_len'])} • รวม {_fmt_len(j['total_len'])}")
    ex = j.get("extra") or {}
    for k in _EXTRA_ORDER:
        if ex.get(k):
            lines.append(f"{k}: {ex[k]}")
    for k, v in ex.items():
        if k not in _EXTRA_ORDER and v:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


class JobAddModal(discord.ui.Modal, title="🧰 เปิดงานใหม่"):
    customer = discord.ui.TextInput(label="ชื่อลูกค้า", placeholder="เช่น คุณสมชาย ใจดี",
                                    max_length=80)
    jtype = discord.ui.TextInput(label="ประเภทงาน",
                                 placeholder="เช่น FIBERTV, HSI/New Connection",
                                 required=False, max_length=80)
    address = discord.ui.TextInput(label="ที่อยู่", style=discord.TextStyle.paragraph,
                                   required=False, max_length=300)
    phone = discord.ui.TextInput(label="เบอร์โทร", required=False, max_length=30)
    circuit = discord.ui.TextInput(label="Circuit", required=False, max_length=80)

    async def on_submit(self, interaction: discord.Interaction):
        jid = _jobs_add({"customer": str(self.customer.value).strip(),
                         "jtype": str(self.jtype.value).strip(),
                         "address": str(self.address.value).strip(),
                         "phone": str(self.phone.value).strip(),
                         "circuit": str(self.circuit.value).strip()})
        await interaction.response.send_message(
            f"🧰 เปิดงาน #{jid} แล้วครับ\n```{_job_card(_jobs_get(jid))}```",
            ephemeral=True)


class JobPasteModal(discord.ui.Modal, title="📥 วางข้อความงาน (ก๊อปมาทั้งก้อน)"):
    blob = discord.ui.TextInput(label="ข้อความงาน", style=discord.TextStyle.paragraph,
                                placeholder="ก๊อปข้อความ/Order Detail จากระบบทางมาวางทั้งก้อนได้เลยครับ",
                                max_length=4000)

    async def on_submit(self, interaction: discord.Interaction):
        d = _parse_job_text(str(self.blob.value))
        jid = _jobs_add(d)
        await interaction.response.send_message(
            f"📥 เปิดงาน #{jid} จากข้อความที่วางแล้วครับ\n```{_job_card(_jobs_get(jid))}```",
            ephemeral=True)


class JobLenModal(discord.ui.Modal, title="📏 อัปเดตระยะสาย"):
    start_f = discord.ui.TextInput(label="ระยะสายเริ่มต้น", placeholder="เช่น 1002",
                                   max_length=15)
    end_f = discord.ui.TextInput(label="ระยะสายสิ้นสุด (ยังไม่มีปล่อยว่าง)",
                                 required=False, max_length=15)

    def __init__(self, jid):
        super().__init__()
        self.jid = jid
        j = _jobs_get(jid) or {}
        if j.get("start_len") is not None:
            self.start_f.default = f"{j['start_len']:g}"
        if j.get("end_len") is not None:
            self.end_f.default = f"{j['end_len']:g}"

    async def on_submit(self, interaction: discord.Interaction):
        s, e = _to_num(self.start_f.value), _to_num(self.end_f.value)
        tot = round(e - s, 1) if (s is not None and e is not None) else None
        _jobs_update(self.jid, start_len=s, end_len=e, total_len=tot)
        await interaction.response.send_message(
            f"📏 บันทึกระยะสายงาน #{self.jid} แล้วครับ\n```{_job_card(_jobs_get(self.jid))}```",
            ephemeral=True)


class _ConfirmDelete(discord.ui.View):
    def __init__(self, jid):
        super().__init__(timeout=60)
        self.jid = jid

    @discord.ui.button(label="ยืนยันลบ", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        _jobs_delete(self.jid)
        await interaction.response.edit_message(
            content=f"🗑️ ลบงาน #{self.jid} แล้วครับ", view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="ยกเลิกการลบแล้วครับ", view=None)


class _JobSelect(discord.ui.Select):
    def __init__(self, mode):
        self.mode = mode
        jobs = _jobs_open()
        ph = {"len": "เลือกงานที่จะบันทึกระยะสาย",
              "close": "เลือกงานที่จะปิด",
              "delete": "เลือกงานที่จะลบ"}[mode]
        opts = [discord.SelectOption(label=f"#{j['id']} {(j['customer'] or '')[:60]}",
                                     value=str(j["id"])) for j in jobs[:25]]
        super().__init__(placeholder=ph, options=opts)

    async def callback(self, interaction: discord.Interaction):
        jid = int(self.values[0])
        if self.mode == "len":
            await interaction.response.send_modal(JobLenModal(jid))
        elif self.mode == "close":
            _jobs_update(jid, status="closed", closed_at=_now_local())
            j = _jobs_get(jid)
            n, meters = _jobs_today()
            sumline = f"\nวันนี้ปิดแล้ว {n} งาน" + (f" • สายรวม {meters:g} ม." if meters else "")
            await interaction.response.edit_message(
                content=f"✅ ปิดงาน #{jid} เรียบร้อย\n```{_job_card(j)}```{sumline}",
                view=None)
        else:
            await interaction.response.edit_message(
                content=f"จะลบงาน #{jid} — กดปุ่มยืนยันลบเพื่อลบเลยครับ",
                view=_ConfirmDelete(jid))


class _JobPickView(discord.ui.View):
    def __init__(self, mode):
        super().__init__(timeout=180)
        self.add_item(_JobSelect(mode))


class JobPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="เปิดงานใหม่", emoji="➕",
                       style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JobAddModal())

    @discord.ui.button(label="วางข้อความงาน", emoji="📥",
                       style=discord.ButtonStyle.primary, row=0)
    async def paste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JobPasteModal())

    @discord.ui.button(label="ระยะสาย", emoji="📏",
                       style=discord.ButtonStyle.secondary, row=0)
    async def lens(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _jobs_open():
            await interaction.response.send_message(
                "ยังไม่มีงานเปิดอยู่ครับ — เริ่มด้วย ➕ เปิดงานใหม่ หรือ 📥 วางข้อความงาน",
                ephemeral=True)
            return
        await interaction.response.send_message(view=_JobPickView("len"), ephemeral=True)

    @discord.ui.button(label="ปิดงาน", emoji="✅",
                       style=discord.ButtonStyle.secondary, row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _jobs_open():
            await interaction.response.send_message(
                "ยังไม่มีงานเปิดอยู่ครับ", ephemeral=True)
            return
        await interaction.response.send_message(view=_JobPickView("close"), ephemeral=True)

    @discord.ui.button(label="ลบงาน", emoji="🗑️",
                       style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _jobs_open():
            await interaction.response.send_message(
                "ยังไม่มีงานเปิดอยู่ครับ", ephemeral=True)
            return
        await interaction.response.send_message(view=_JobPickView("delete"), ephemeral=True)

    @discord.ui.button(label="ดูงานทั้งหมด", emoji="📋",
                       style=discord.ButtonStyle.secondary, row=1)
    async def viewall(self, interaction: discord.Interaction, button: discord.ui.Button):
        jobs = _jobs_open()
        if not jobs:
            await interaction.response.send_message(
                "📋 ยังไม่มีงานเปิดอยู่ครับ", ephemeral=True)
            return
        body = "\n\n".join(_job_card(j) for j in jobs)
        await interaction.response.send_message(
            f"📋 **งานที่กำลังทำ ({len(jobs)})**\n```\n{body[:1800]}\n```",
            ephemeral=True)


@tree.command(name="job", description="🧰 ระบบงานแบบปุ่ม (แยกจากแชต)")
async def slash_job(interaction: discord.Interaction):
    jobs = _jobs_open()
    n_done, meters = _jobs_today()
    desc = f"🔓 กำลังทำ {len(jobs)} งาน • ✅ วันนี้ปิดแล้ว {n_done} งาน"
    if meters:
        desc += f" • สายรวม {meters:g} ม."
    desc += "\n\nกดปุ่มด้านล่างจัดการได้เลยครับ"
    await interaction.response.send_message(f"🧰 **ระบบงาน** — {desc}",
                                            view=JobPanel(), ephemeral=True)


@tree.command(name="help", description="📖 ดูความสามารถทั้งหมดของ Jarvis")
async def slash_help(interaction: discord.Interaction):
    hands = "\n".join(f"• `{k}`" for k in sorted(HANDS)) or "(โหมดคุยอย่างเดียว)"
    await interaction.response.send_message(
        "📖 **ความสามารถของ Jarvis**\n\n"
        "💬 **คุยได้ทุกเรื่อง** — แตะ @Jarvis หรือทัก DM หรือใช้ /ask\n\n"
        f"**🦾 มือที่พร้อมใช้ตอนนี้ ({len(HANDS)}):**\n{hands}\n\n"
        "**ตัวอย่างคำสั่ง:**\n"
        "• แบตเหลือเท่าไหร่ / เปิด YouTube\n"
        "• ตั้งเตือนโทรหาแม่พรุ่งนี้ 9 โมง / รายการเตือน\n"
        "• จดรายจ่าย น้ำมัน 500 / สรุปรายจ่ายเดือนนี้\n"
        "• อากาศเชียงใหม่ / ดอลลาร์วันนี้เท่าไหร่ / ทอยเต๋า 2 ดอก\n"
        "• เปิดไฟฉาย / ปิดไฟฉาย / ถ่ายรูปเซลฟี่ / ฉันอยู่ที่ไหน\n"
        "• เปิดเสียง / ปิดเสียง (พูด + ส่ง voice note)\n"
        "• ระบบงาน: พิมพ์ /job แล้วกดปุ่ม (แยกจากแชต 100%)\n"
        "• ส่งรูปมาให้ Jarvis อ่านได้ (ถอดข้อความในรูป / ถามเรื่องในรูป)\n\n"
        "คำสั่งลัด: /ask /battery /weather /voice /torch /photo /job /help",
        ephemeral=True)


@tree.command(name="torch", description="🔦 เปิด/ปิดไฟฉายมือถือ")
@app_commands.choices(mode=[
    app_commands.Choice(name="เปิดไฟฉาย", value="on"),
    app_commands.Choice(name="ปิดไฟฉาย", value="off"),
])
async def slash_torch(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    await interaction.response.defer(thinking=True)
    try:
        out = await asyncio.to_thread(HANDS["torch"], mode.value)
    except Exception as e:
        out = f"❌ {e}"
    await interaction.followup.send(clean_reply(out)[:1900])


@tree.command(name="photo", description="📸 ถ่ายรูปจากมือถือส่งเข้าแชต")
@app_commands.choices(camera=[
    app_commands.Choice(name="กล้องหลัง", value="0"),
    app_commands.Choice(name="กล้องหน้า (เซลฟี่)", value="1"),
])
async def slash_photo(interaction: discord.Interaction, camera: app_commands.Choice[str] = None):
    await interaction.response.defer(thinking=True)
    try:
        out, attach = await asyncio.to_thread(HANDS["camera"], camera.value if camera else "0")
    except Exception as e:
        out, attach = f"❌ {e}", None
    out = clean_reply(out)
    if attach:
        await interaction.followup.send(out[:1900], file=discord.File(attach))
    else:
        await interaction.followup.send(out[:1900])


@bot.event
async def on_ready():
    global _last_channel_id
    try:
        await tree.sync()
        log.info("Slash commands synced")
    except Exception as e:
        log.error("Sync slash commands failed: %s", e)
    asyncio.create_task(reminder_loop())
    log.info("✅ Jarvis Discord bot online แล้ว! (%s) — มือ: %s",
             bot.user, ", ".join(sorted(HANDS)) or "โหมดคุยอย่างเดียว")


@bot.event
async def on_message(message: discord.Message):
    global _last_channel_id
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    mentioned = bot.user in (message.mentions or [])
    if not (is_dm or mentioned):
        return

    _last_channel_id = message.channel.id
    text = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

    # 👀 เก็บรูปที่แนบมาด้วย (สูงสุด 2 รูป)
    images = []
    for a in (message.attachments or [])[:2]:
        ct = a.content_type or ""
        if ct.startswith("image/"):
            try:
                images.append((await a.read(), ct))
            except Exception as e:
                log.warning("โหลดรูปแนบไม่ได้: %s", e)
    if not text and not images:
        text = "สวัสดี"

    async with message.channel.typing():
        reply, want_voice, attach = await process_message(
            text, message.channel.id, images or None)
    await reply_long(message.channel, reply)

    if attach:
        try:
            await message.channel.send(file=discord.File(attach))
        except Exception as e:
            log.warning("send attach: %s", e)

    if want_voice and VOICE_ENABLED.get(message.channel.id, True):
        await speak_and_note(reply, message.channel.id, message.channel)


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
