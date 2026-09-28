# -*- coding: utf-8 -*-
"""
เครื่องมือทดสอบสมอง Jarvis (Groq) v3 — ไล่ลองทุกโมเดลจนเจอตัวที่ใช้ได้จริง
รัน: python test_groq.py
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

print("=" * 42)
print("  ทดสอบสมอง Jarvis (Groq API) v3")
print("=" * 42)

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
    print('วิธีแก้: echo "GROQ_API_KEY=gsk_xxx" >> .env')
    raise SystemExit(1)

print("✅ พบ key ที่มาจาก: " + key_from)
print()

from groq import Groq

client = Groq(api_key=key)

BAD = ("whisper", "tts", "guard", "embed", "playai")
PREFERRED = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

print("🔍 ดึงรายชื่อโมเดลจาก Groq...")
try:
    ids = [m.id for m in client.models.list()]
except Exception as e:
    print("   ❌ ดึงรายชื่อไม่สำเร็จ: " + str(e)[:300])
    raise SystemExit(1)

good = [i for i in ids if not any(k in i.lower() for k in BAD)]
ordered = ([p for p in PREFERRED if p in good]
           + [i for i in good if i not in PREFERRED])
print("   มีทั้งหมด " + str(len(ids)) + " โมเดล (ใช้ทดสอบได้ " + str(len(good)) + "):")
print("   " + ", ".join(good[:12]))
print()
print("🧪 ไล่ทดลองยิงจริงทีละตัว (ตัวไหนตอบได้ = ชนะ)...")

winner = None
for cand in ordered[:8]:
    try:
        r = client.chat.completions.create(
            model=cand,
            messages=[{"role": "user", "content": "พูดว่า ทดสอบสำเร็จ"}],
            max_tokens=30,
        )
        out = (r.choices[0].message.content or "(ว่าง)").strip()[:60]
        print("   ✅ " + cand + " → ตอบว่า: " + out)
        winner = cand
        break
    except Exception as e:
        s = str(e)
        low = s.lower()
        if "model_not_found" in low or "does not exist" in low or "access" in low:
            print("   ✗ " + cand + " → ถูกปลด/ไม่มีสิทธิ์ (ข้าม)")
        elif "429" in s or "rate limit" in low:
            print("   ⚠️ " + cand + " → มีสิทธิ์แต่ช่วงนี้โควตาเต็ม (ลองตัวอื่น)")
        else:
            print("   ✗ " + cand + " → " + s[:80])

print()
if winner:
    print("🎉 โมเดลที่ใช้ได้จริงคือ: " + winner)
    print("   ไปอัปเดต discord_bot.py ตามคำสั่งที่ผมให้ แล้ว Jarvis จะตอบได้เลยครับ")
else:
    print("❌ ไม่มีโมเดลไหนตอบเลย — ปัญหาอยู่ที่ key/สิทธิ์บัญชี")
    print("   1) เข้า console.groq.com → API Keys → สร้าง key ใหม่")
    print('   2) รัน: echo "GROQ_API_KEY=gsk_ตัวใหม่" >> .env')
    print("   3) รัน python test_groq.py ใหม่")
