# 🤖 Jarvis AI Assistant

ผู้ช่วย AI ส่วนตัวภาษาไทย ทำงานบน **Termux (Android)** พูดคุย + ลงมือทำ + ตอบด้วยเสียงผู้หญิง

> 📦 โค้ดฉบับสมบูรณ์อยู่ใน PR #1 → `discord_bot.py` (Discord) และ `run.py` (Telegram)

---

## 🧩 สถาปัตยกรรม

```
        ผู้ใช้
       /      \
  Discord     Telegram
  discord_bot.py   run.py
       \      /
    🧠 สมอง: Groq AI (เลือกโมเดลอัตโนมัติ)
    🦾 มือ: device_actions + plugins + termux-api
    🔊 เสียง: Edge TTS อัจฉรา (ไทย) → gTTS → termux-tts-speak
    ⏰ แจ้งเตือน: เฝ้า reminder.db ทุก 20 วินาที
```

## 💬 Discord Bot (`discord_bot.py`)

| กลุ่ม | ความสามารถ |
|---|---|
| 🧠 สมอง | คุยได้ทุกเรื่อง จำบริบท 5 รอบ ภาษาไทยจบ "ครับ" |
| 🦾 มือ | 🔋 แบต • 📺 YouTube (MacroDroid) • ⏰ เตือน • 📋 งาน • 💰 รายจ่าย • 📰 ข่าว • 🌤️ อากาศ • 💱 อัตราแลกเปลี่ยน • 🎲 สุ่ม • 🔦 ไฟฉาย • 📸 ถ่ายรูปส่งแชต • 📍 GPS |
| 🎙️ เสียง | พูดออกลำโพง + ส่ง voice note ในแชต (`เปิดเสียง`/`ปิดเสียง`) |
| ⏰ เตือนเอง | ถึงเวลา = ทักหาเอง + พูดเรียก |

**จุดเด่นสำคัญ: Auto-pick model** — โมเดล Groq ถูกปลดบ่อย (`llama-3.1-8b-instant` ฯลฯ) บอทจะดึงรายชื่อ + ไล่ทดลองยิงจริงแล้วจำตัวที่ใช้ได้ ไม่ต้องแก้โค้ดอีกเมื่อ Groq เปลี่ยนรายชื่อ

คู่มือตั้งค่าทีละขั้น (สร้างแอป Discord / เชิญบอท / รันบน Termux) → [`SETUP_DISCORD.md`](SETUP_DISCORD.md)

## 💬 Telegram Bot (`run.py`)

โครงสร้างเดิมของโปรเจกต์ (worker queue / PLUGIN_MAP / memory_manager / tts / FastAPI `/pulse`) อัปเกรดสมองเป็น auto-model เหมือน Discord — แก้ปัญหา "ระบบ AI ขัดข้อง" ที่เกิดจากโมเดลถูกปลด

## 🔧 เครื่องมือช่วย

- `test_groq.py` — วินิจฉัย key + ไล่ทดสอบโมเดลว่าตัวไหนยังใช้ได้จริง
- `n8n-jarvis-discord.json` — workflow n8n สำหรับ Discord Interactions (ทางเลือกไม่ใช้ Python)

## 🚀 รัน

```bash
cd ~/My_bot_kao
python discord_bot.py   # บอท Discord
python run.py           # บอท Telegram (รันพร้อมกันได้ใน session แยก)
```

---

## ⚠️ บันทึกภาษาไทยกับ substring (เผื่อคนต่อยอด)

- "เปิดเสียง" มี "ปิดเสียง" ซ่อนอยู่ (เ + ปิดเสียง)
- "เปิดไฟฉาย" มี "ปิดไฟฉาย" ซ่อนอยู่
- → ทุกจุดที่เช็คคำสั่งเปิด/ปิด **ต้องเช็ค "เปิด" ก่อน "ปิด"** เสมอ

🤖 สร้างและดูแลโดย Arena Agent • 2026-09-28
