# -*- coding: utf-8 -*-
"""
Jarvis AI — Telegram Bot (v2 สมองอัตโนมัติ)
=============================================
โครงสร้างเดิมทั้งหมด (worker queue, PLUGIN_MAP, memory, TTS, FastAPI /pulse)
เพียงแต่ซ่อม/อัปเกรด:
  ✅ ลบขยะข้อความที่ปนมาในไฟล์เดิม (terminal dump)
  ✅ เพิ่ม import time (เดิม /pulse จะ crash เพราะเรียก time.time() โดยไม่ import)
  ✅ สมองเลือกโมเดล Groq อัตโนมัติ (llama-3.1-8b-instant ถูกปลดแล้ว — สาเหตุที่บอทตอบ "ระบบขัดข้อง")
  ✅ แกะคำตอบ AI ได้ทุกรูปแบบ (JSON / fence / list-of-blocks / ข้อความดิบ)
  ✅ ล้างคำหลุด ("คำตอบ:" prefix, ค่ะ→ครับ)
รันเหมือนเดิม:  python run.py
"""
import json
import logging
import re
import threading
import time
from queue import Queue

import telebot
from groq import Groq

# ดึงค่าจากไฟล์เดิมในระบบของพี่ ปลอดภัยไม่พังชัวร์
import config
import device_actions
import plugin_loader

PLUGIN_MAP = {
    "CHECK_BATTERY": "battery",
    "OPEN_YOUTUBE": "youtube",
}
import memory_manager
import tts

from fastapi import FastAPI
import uvicorn

# ------------------
# STATUS
# ------------------
JARVIS_LIVE_STATUS = {
    "last_ai_latency_ms": 0,
    "intent_ok": True,
    "db_ok": True,
}

logging.basicConfig(level=logging.ERROR)

bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
client = Groq(api_key=config.GROQ_API_KEY)

task_queue = Queue()

ACTION_MAP = {
    "open_youtube": device_actions.open_youtube,
    "check_battery": device_actions.check_battery,
}

# ------------------
# 🧠 สมอง: เลือกโมเดล Groq อัตโนมัติ
# (ไล่ทดลองยิงจริงทีละตัว — กันโมเดลถูกปลดจนบอทตอบแต่ "ระบบขัดข้อง")
# ------------------
PREFERRED_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.3-70b-versatile"]
FALLBACK_MODELS = ["qwen/qwen3-32b", "compound-beta", "llama3-8b-8192",
                   "gemma2-9b-it", "mixtral-8x7b-32768"]
BAD_MODEL_KEYWORDS = ("whisper", "tts", "guard", "embed", "playai")

_current_model = None
_model_candidates = []


def _build_candidates():
    if getattr(config, "GROQ_MODEL", None):
        return [config.GROQ_MODEL]
    good = []
    try:
        from urllib.request import Request, urlopen
        req = Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + config.GROQ_API_KEY},
        )
        data = json.loads(urlopen(req, timeout=20).read().decode())
        ids = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        good = [i for i in ids if not any(k in i.lower() for k in BAD_MODEL_KEYWORDS)]
    except Exception as e:
        print("Model list error:", e)
    extra = [c for c in FALLBACK_MODELS if c not in good]
    return ([p for p in PREFERRED_MODELS if p in good]
            + [i for i in good if i not in PREFERRED_MODELS] + extra)


def get_model():
    global _current_model, _model_candidates
    if _current_model:
        return _current_model
    if not _model_candidates:
        _model_candidates = _build_candidates()
    for cand in _model_candidates[:14]:
        try:
            # ห้ามใส่ max_tokens ต่ำ — โมเดลแบบคิดก่อนตอบ (gpt-oss/qwen) จะ 400
            client.chat.completions.create(
                model=cand, messages=[{"role": "user", "content": "ping"}])
            _current_model = cand
            print("ใช้โมเดล Groq:", cand)
            return cand
        except Exception as e:
            s = str(e).lower()
            if "429" in s or "rate limit" in s:
                _current_model = cand
                print("ใช้โมเดล Groq:", cand, "(ช่วงนี้โควตาแน่นนิดหน่อย)")
                return cand
            dead = any(k in s for k in ("decommission", "model_not_found",
                                        "does not exist", "do not have access"))
            if dead:
                print("ข้ามโมเดล", cand, "(ถูกปลด/ไม่มีสิทธิ์)")
                continue
            _current_model = cand
            print("ใช้โมเดล Groq:", cand, "(หมายเหตุ:", str(e)[:70], ")")
            return cand
    raise RuntimeError("ไม่พบโมเดลที่ใช้ได้ — เช็ค key ที่ console.groq.com")


# ------------------
# fallback intent
# ------------------
def fallback_intent(text):
    text = text.lower()

    if "แบต" in text or "battery" in text:
        return "CHECK_BATTERY"

    if "youtube" in text or "ยูทูป" in text:
        return "OPEN_YOUTUBE"

    return None


# ------------------
# ล้างคำหลุด
# ------------------
def clean_reply(text):
    t = (text or "").strip()
    t = re.sub(r"^\s*(คำตอบ|คำตอบคือ|Response|Reply|Answer|Output)\s*[:：]\s*", "", t,
               flags=re.IGNORECASE)
    t = re.sub(r"^\s*(Jarvis|จาร์วิส)\s*[:：]\s*", "", t)
    return t.replace("ค่ะ", "ครับ").replace("คะ", "ครับ").replace("ครับ/ค่ะ", "ครับ")


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
    """ดึง {reply, action} แบบยืดหยุ่น — ไม่มี JSON ก็ใช้ข้อความดิบ"""
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
            return {"reply": raw[:1500], "action": None}
    reply = data.get("reply") or data.get("response") or data.get("message") or ""
    action = data.get("action") or data.get("intent") or None
    if isinstance(action, dict):
        action = action.get("name") or action.get("type") or None
    if isinstance(action, str):
        action = action.strip().upper() or None
    if not reply and raw_text:
        reply = str(raw_text).strip()
    return {"reply": (str(reply) or "รับทราบครับ").strip(), "action": action}


# ------------------
# AI (ใช้โครงสร้างแบบที่พี่ปรับปรุงมา นิ่งและฉลาดขึ้น)
# ------------------
def ask_jarvis(user_message, history_text=""):
    system_instruction = """คุณคือ Jarvis AI ผู้ช่วยส่วนตัว

กฎ:
- ตอบเป็นภาษาไทยที่เป็นธรรมชาติ เป็นกันเอง และอธิบายเข้าใจง่าย
- สุภาพและจริงใจ
- ลงท้ายด้วย "ครับ" ทุกประโยค
- ห้ามใช้คำว่า "ค่ะ" หรือ "คะ" เด็ดขาด
- ห้ามขึ้นต้นด้วย "คำตอบ:" หรือ "Response:"
- ตอบเฉพาะ JSON ตามรูปแบบที่กำหนดเท่านั้น"""

    prompt = f"""Context:
{history_text}

User:
{user_message}

ตอบกลับเป็น JSON รูปแบบนี้เท่านั้น:
{{
  "reply": "ข้อความตอบกลับ",
  "action": null
}}"""

    global _current_model, _model_candidates
    last_err = None
    use_json_mode = True
    for attempt in (1, 2, 3):
        try:
            kwargs = dict(model=get_model(), messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ], temperature=0.5)
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            res = client.chat.completions.create(**kwargs)
            content = res.choices[0].message.content
            result = coerce_result(parse_ai_json(content), content)
            if result is None:
                return {"reply": "รับทราบครับ", "action": None}
            return result
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if attempt == 1 and ("model_not_found" in msg or "does not exist" in msg):
                dead = _current_model
                _current_model = None
                _model_candidates = [c for c in _model_candidates if c != dead]
                print("โมเดล", dead, "ใช้ไม่ได้แล้ว — เลือกตัวใหม่")
                continue
            if use_json_mode and ("response_format" in msg or ("json" in msg and "400" in msg)):
                use_json_mode = False
                continue
            raise
    raise last_err or RuntimeError("AI error")


# ------------------
# worker (ล้างคำหลุดก่อนส่งออกทุกช่องทาง)
# ------------------
def worker():
    while True:
        task = task_queue.get()

        reply = ""

        try:
            chat_id = task["chat_id"]
            text = task["text"]
            history = task["history"]

            history_text = "\n".join([f"User:{u}\nJarvis:{b}" for u, b in history])

            result = ask_jarvis(text, history_text)

            action = result.get("action") or fallback_intent(text)
            reply = result.get("reply") or "รับทราบครับ"

            # 🔥 ระบบล้างคำหลุด: AI เผลอพูด "ค่ะ"/"คำตอบ:" โค้ดแก้ให้ทันที
            reply = clean_reply(reply)

            if action:
                try:
                    # รองรับทั้งชื่อ plugin ตรง ๆ และรูปแบบ CHECK_BATTERY/OPEN_YOUTUBE
                    plugin_name = PLUGIN_MAP.get(action, str(action).lower())
                    plugin = plugin_loader.get_plugin(plugin_name)

                    if plugin:
                        out = plugin.execute(text)
                        if out:
                            reply = clean_reply(str(out))

                except TypeError:
                    plugin_name = PLUGIN_MAP.get(action, str(action).lower())
                    plugin = plugin_loader.get_plugin(plugin_name)
                    if plugin:
                        reply = clean_reply(str(plugin.execute()))
                except Exception as e:
                    print("PLUGIN Error:", e)

            bot.send_message(chat_id, reply)

            # 🔊 TTS ลำโพงพูดได้คำที่ถูกต้อง (ไม่ให้ TTS ทำ worker ล้ม)
            try:
                tts.speak(reply)
            except Exception as e:
                print("TTS Error:", e)

            # 🧠 บันทึกความจำด้วยคำที่ผ่านการกรองแล้ว
            try:
                memory_manager.save_memory(text, reply)
            except Exception as e:
                print("Memory Error:", e)

        except Exception as e:
            print("Worker Error:", e)
            print("DEBUG reply =", reply)
            try:
                bot.send_message(task.get("chat_id"), "ขออภัยครับ ระบบ AI ขัดข้องครับ")
            except Exception:
                pass

        finally:
            task_queue.task_done()


# ------------------
# telegram
# ------------------
@bot.message_handler(func=lambda m: True)
def handle(m):
    if not m.text:
        return

    task_queue.put({
        "chat_id": m.chat.id,
        "text": m.text,
        "history": memory_manager.get_memory(5),
    })


# ------------------
# fastapi
# ------------------
app = FastAPI()


@app.get("/pulse")
def pulse():
    return {
        "status": "ok",
        "queue": task_queue.qsize(),
        "time": time.time(),
        "model": _current_model,
        "hands": sorted(PLUGIN_MAP.values()),
    }


# ------------------
# start
# ------------------
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    print("Jarvis started")

    uvicorn.run(app, host="127.0.0.1", port=8000)
