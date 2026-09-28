# -*- coding: utf-8 -*-
"""
เครื่องมือทดสอบสมองของ Jarvis (Groq) — เลือกโมเดลอัตโนมัติ
รัน: python test_groq.py
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

print("=" * 40)
print("  ทดสอบสมอง Jarvis (Groq API)")
print("=" * 40)

# หา key: ลอง .env ก่อน แล้วค่อยลอง config.py
key = os.getenv("GROQ_API_KEY")
key_from = ".env"
if not key:
    try:
        import config
        for attr in ("GROQ_API_KEY", "GROQ_KEY", "GROQ_API", "groq_api_key"):
            v = getattr(config, attr, None)
            if v:
                key = v
                key_from = "config.py (" + attr + ")"
                break
    except Exception:
        pass

if not key:
    print("❌ ไม่พบ GROQ_API_KEY ทั้งใน .env และ config.py")
    print()
    print("วิธีแก้: เอา key ฟรีที่ https://console.groq.com")
    print("แล้วรันคำสั่งนี้ (แทน gsk_xxx ด้วย key ของคุณ):")
    print('   echo "GROQ_API_KEY=gsk_xxx" >> .env')
    raise SystemExit(1)

print("✅ พบ key ที่มาจาก: " + key_from)
print("   (เริ่มด้วย " + key[:6] + "... ยาว " + str(len(key)) + " ตัวอักษร)")
print()

from groq import Groq

client = Groq(api_key=key)

# ---- เลือกโมเดลที่ยังมีชีวิต ----
PREFERRED = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
BAD = ("whisper", "tts", "guard", "embed", "playai")

model = os.getenv("GROQ_MODEL")
if not model:
    print("🔍 กำลังถาม Groq ว่าตอนนี้มีโมเดลอะไรให้ใช้บ้าง...")
    try:
        ids = [m.id for m in client.models.list()]
        good = [i for i in ids if not any(k in i.lower() for k in BAD)]
        print("   โมเดลที่ใช้ได้ (" + str(len(good)) + " ตัว): " + ", ".join(good[:8]))
        for p in PREFERRED:
            if p in good:
                model = p
                break
        if not model and good:
            model = good[0]
    except Exception as e:
        print("   ⚠️ เช็ครายชื่อไม่สำเร็จ: " + str(e)[:200])
        model = PREFERRED[0]
if not model:
    model = PREFERRED[0]

print("🧠 ใช้โมเดล: " + model)
print()

try:
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "พูดว่า ทดสอบสำเร็จ"}],
    )
    print("🤖 AI ตอบว่า:", (r.choices[0].message.content or "").strip())
    print()
    print("🎉 สมองใช้ได้ปกติ! กลับไปทักบอทใน Discord ได้เลยครับ")
except Exception as e:
    print("❌ เรียก Groq ไม่สำเร็จ — สาเหตุ:")
    print()
    print("   " + str(e)[:600])
    print()
    print("วิธีแก้ตามอาการ:")
    print("   401/Invalid API Key → key ไม่ถูก เอาใหม่ที่ console.groq.com")
    print("   429/Rate limit      → รอ 1 นาทีแล้วรันใหม่")
    print("   404/model           → ช็อตจอส่งผม ผมจะแก้ชื่อโมเดลให้")
    print("   Connection error    → เน็ตมีปัญหา สลับ WiFi/เน็ตมือถือ")
