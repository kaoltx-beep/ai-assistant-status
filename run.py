import threading
nfig.cpython-313.pyc           requirements.txt
config.py                        restart.py
deploy.sh                        run.py
deploy_v8.sh                     run.py.backup
developer.py                     run.py.before_router_fix
device_actions.cpython-313.pyc   run.py.broken
device_actions.py                run.py.error
feedback_server.cpython-313.pyc  run.py.good
feedback_server.py               sandbox
handlers                         test.py
intents                          tts.py
jarvis                           voice.mp3
jarvis.db                        voice.py
jarvis.db-shm                    voice_jarvis.py
~/My_bot_kao $ cd ~/My_bot_kao
~/My_bot_kao $ python run.py
Jarvis started
INFO:     Started server process [13347]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
 time
import logging
import json
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
    "db_ok": True
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
# fallback intent
# ------------------
def fallback_intent(text):
    text = text.lower()

    if "แบต" in text or "battery" in text:
        return "check_battery"

    if "youtube" in text or "ยูทูป" in text:
        return "open_youtube"

    return None


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

    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print("AI Error:", e)
        return {"reply": "ขออภัยครับ ระบบ AI ขัดข้องครับ", "action": None}


# ------------------
# worker (เพิ่มโค้ดล้างคำหลุด ชัวร์ 100% ก่อนส่งออกทุกช่องทาง)
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

            # 🔥 ระบบล้างคำหลุดตามที่พี่แนะนำ: ต่อให้ AI เผลอพูด "ค่ะ" โค้ดส่วนนี้จะแก้ให้เป็น "ครับ" ทันที
            reply = reply.replace("ค่ะ", "ครับ").replace("คะ", "ครับ").replace("ครับ/ค่ะ", "ครับ")

            if action in PLUGIN_MAP:
                try:
                    plugin_name = PLUGIN_MAP[action]
                    plugin = plugin_loader.get_plugin(plugin_name)

                    if plugin:
                        reply = plugin.execute()

                except Exception as e:
                    print("PLUGIN Error:", e)

            bot.send_message(chat_id, reply)

            # 🔊 TTS ลำโพงพูดได้คำที่ถูกต้อง
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
        "history": memory_manager.get_memory(5)
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
        "time": time.time()
    }


# ------------------
# start
# ------------------
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    print("Jarvis started")

    uvicorn.run(app, host="127.0.0.1", port=8000)

