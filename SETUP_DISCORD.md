# 🤖 คู่มือทำให้ Jarvis ตอบคุยผ่าน Discord (สำหรับมือใหม่ กดตามทีละขั้น)

> ⏱️ ใช้เวลาประมาณ **5–10 นาที** • ฟรีทั้งหมด • ไม่ต้องมีบัตรเครดิต

ทำแบบ **ทางเลือก A (แนะนำ)** ก็ใช้ได้แล้ว ส่วนทางเลือก B (n8n) ไว้ทำทีหลังได้

---

# ✅ ทางเลือก A: Python Discord Bot (ง่ายสุด แนะนำ)

หลักการ: คุณสร้าง "บัญชีบอท Discord" ของตัวเอง → เอา token มาใส่ในโค้ด → รันเหมือนรัน `python run.py` เดิม บอทจะวางใจรอคำถามใน Discord แล้วให้ Groq (AI ตัวเดิมของ Jarvis) ตอบ

## ขั้นที่ 1 — สร้างแอป Discord ของคุณ (3 นาที)

1. เปิดเว็บ **https://discord.com/developers/applications** แล้วล็อกอิน
2. มุมขวาบนกด **"New Application"** → ตั้งชื่อว่า `Jarvis` → กด **Create**
3. ในเมนูซ้ายกด **"Bot"**
4. กด **"Reset Token"** → ยืนยัน → กด **Copy** token เก็บไว้
   > ⚠️ Token คือรหัสลับของบอท **ห้ามส่งให้ใคร ห้ามลง Git!** (ถ้าเผลอหลุด กด Reset ใหม่ได้)

## ขั้นที่ 2 — เปิดสิทธิ์ให้บอทอ่านข้อความ (สำคัญมาก พลาดกันบ่อยสุด!)

ยังอยู่หน้า **Bot** เดิม เลื่อนลงมาหาหัวข้อ **"Privileged Gateway Intents"** เปิดสวิตช์:

- ✅ **MESSAGE CONTENT INTENT**  ← บังคับต้องเปิด
- ✅ SERVER MEMBERS INTENT (แนะนำ)

แล้วกด **Save Changes**

## ขั้นที่ 3 — เชิญบอทเข้าเซิร์ฟเวอร์ของคุณ

1. เมนูซ้ายกด **"OAuth2"** → กด **"URL Generator"**
2. ติ๊กเลือก:
   - Scopes: ✅ `bot` และ ✅ `applications.commands`
   - Bot Permissions: ✅ Send Messages, ✅ Read Message History, ✅ View Channels
3. คัดลอกลิงก์ที่ขึ้นมาด้านล่าง (หน้าตาแบบนี้) เปิดในเบราว์เซอร์:

   ```
   https://discord.com/oauth2/authorize?client_id=XXXXXXXX&scope=bot+applications.commands&permissions=68608
   ```

4. เลือกเซิร์ฟเวอร์ของคุณ → **Authorize** → บอทจะโผล่ในรายชื่อสมาชิก (ยังออฟไลน์อยู่ ปกติ)

## ขั้นที่ 4 — ติดตั้งโค้ดที่เครื่องคุณ

เปิด terminal เครื่องคุณ (อันเดียวกับที่รัน Telegram bot) แล้วพิมพ์:

```bash
# 1) ดาวน์โหลดไฟล์ discord_bot.py จาก repo นี้ ไปวางในโฟลเดอร์ My_bot_kao
cd ~/My_bot_kao

# 2) ติดตั้ง library
pip install -U discord.py groq python-dotenv

# 3) สร้างไฟล์ .env (หรือเปิดแก้ไฟล์ .env เดิมถ้ามี) ใส่ 2 บรรทัดนี้
echo 'DISCORD_BOT_TOKEN=วาง_token_จากขั้นที่_1_ตรงนี้' >> .env
echo 'GROQ_API_KEY=ใส่_gsk_ของคุณ' >> .env

# 4) รัน!
python discord_bot.py
```

> 💡 ถ้าคุณเอาไฟล์ `discord_bot.py` ไปวางในโฟลเดอร์ `~/My_bot_kao` ที่มี `config.py` อยู่แล้ว
> ตัว GROQ_API_KEY จะถูกดึงจาก config.py ให้อัตโนมัติ — ใส่แค่ `DISCORD_BOT_TOKEN` ใน .env ก็พอ

## ขั้นที่ 5 — ทดสอบ!

ถ้า terminal ขึ้นว่า `✅ Jarvis Discord bot online แล้ว!` ให้ไปที่ Discord แล้วลอง:

| วิธีคุย | ตัวอย่าง |
|---|---|
| แตะ @บอทในแชนเนลไหนก็ได้ | `@Jarvis สวัสดี วันนี้อากาศเป็นไงบ้าง` |
| ทัก DM บอทตรง ๆ | `ช่วยอธิบาย quantum computing หน่อย` |
| คำสั่ง slash | พิมพ์ `/ask` แล้วตามด้วยคำถาม |

บอทจำบริบทได้ **5 รอบสนทนาล่าสุดต่อแชนเนล** และตอบภาษาไทยลงท้าย "ครับ" เหมือนต้นฉบับ 🎉

---

# 🔧 แก้ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `LoginFailure` / Token ไม่ถูก | เอา token ใหม่: Developer Portal → Bot → **Reset Token** → อัปเดต .env |
| `PrivilegedIntentsRequired` | ลืมเปิด **MESSAGE CONTENT INTENT** ในขั้นที่ 2 |
| บอทออนไลน์แต่ไม่ตอบทักในแชนเนล | ต้อง **แตะ @Jarvis นำหน้า** ทุกครั้ง (หรือทัก DM) — บอทไม่ตอบข้อความทั่วไป |
| `/ask` ไม่ขึ้น | รอ 1 นาที (sync ครั้งแรกช้า) หรือเช็คว่าตอนเชิญบอทติ๊ก `applications.commands` แล้ว |
| `Groq Error 429` | ใช้ฟรีเกินโควตาชั่วคราว — รอ 1 นาทีแล้วใช้ต่อได้ |
| `Groq Error 401` | GROQ_API_KEY ผิด — เอาใหม่ที่ https://console.groq.com |

---

# 🟦 ทางเลือก B: ผ่าน n8n บน Render (ทำได้ แต่ขั้นเยอะกว่า)

มีไฟล์ **`n8n-jarvis-discord.json`** เตรียมให้แล้ว — import แล้วเชื่อมต่อได้เลย ขั้นตอน:

1. เปิด n8n ของคุณ (ตัวบน Render จาก repo `n8n-msrhxu2y` / `n8n-msw17onr`)
   > ⚠️ Render แผนฟรีจะ **sleep** ถ้าไม่มีคนใช้ — บอทจะเงียบเมื่อ n8n หลับ (ตัว `chore/n8n-keep-alive` ที่คุณทำไว้ช่วยเรื่องนี้ได้)
2. หน้า Workflows → **Import from File** → เลือก `n8n-jarvis-discord.json`
3. เปิด node **"Groq AI"** → แก้ค่า `Authorization` เป็น `Bearer gsk_xxxของคุณ`
4. เปิด node **"Send to Discord"** → แก้ค่า `Authorization` เป็น `Bot TOKEN_DISCORDของคุณ`
5. กด **Activate** workflow แล้วคัดลอก **Production Webhook URL**
6. กลับไปที่ Discord Developer Portal → แอปของคุณ → **General Information** → หาช่อง **Interactions Endpoint URL** วาง URL จากข้อ 5 → Save
   > Discord จะทดสอบยิง PING มาทันที — workflow นี้ตอบ `type:1` ให้อัตโนมัติ ถ้า Save ผ่านคือพร้อมใช้
7. ทดสอบ: ใช้ slash command `/ask` ในเซิร์ฟเวอร์ (ต้องเชิญบอทด้วย scope `applications.commands` ตามทางเลือก A ขั้นที่ 3)

> 💡 ความต่าง: ทาง A บอทตอบได้ทั้ง @mention / DM / slash และไม่มีปัญหา sleep — เสถียรกว่าสำหรับใช้ส่วนตัว
> ทาง B เหมาะถ้าอยากต่อยอด automation ใน n8n ต่อ (เชื่อม Gmail, Sheets, ฯลฯ)

---

# 📁 ไฟล์ในชุดนี้

| ไฟล์ | คืออะไร |
|---|---|
| `discord_bot.py` | ตัวบอท Discord (ทางเลือก A) |
| `requirements-discord.txt` | library ที่ต้องติดตั้ง |
| `SETUP_DISCORD.md` | คู่มือที่คุณกำลังอ่านอยู่ |
| `n8n-jarvis-discord.json` | workflow n8n สำเร็จรูป (ทางเลือก B) |

สร้างโดย Arena Agent • โค้ดออกแบบให้เข้ากับระบบ Jarvis เดิมของคุณ (ระบบล้างคำหลุด "ค่ะ→ครับ", ระบบจำบริบท, โมเดล llama-3.1-8b-instant)
