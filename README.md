# ai-assistant-status

ผู้ช่วย AI สองตัวใน repo เดียว

| ส่วน | ทำอะไร |
|---|---|
| `android_agent/` | **AI agent ควบคุมมือถือ Android** — ดูจอผ่าน ADB, ตัดสินใจด้วย vision model, กดจอแทนคุณ |
| `run.py` | บอท Jarvis ตัวเดิม (Telegram + Groq) ที่มีอยู่ก่อนแล้ว |

---

## เริ่มใช้ Android agent

อ่านคู่มือทีละขั้น (ภาษาไทย): **[SETUP_TH.md](SETUP_TH.md)**

สรุปสั้น ๆ:

```bash
# บนมือถือ ผ่าน Termux
pkg install python android-tools git -y
git clone https://github.com/kaoltx-beep/ai-assistant-status.git
cd ai-assistant-status
cp .env.example .env && chmod 600 .env
nano .env                     # ใส่ GEMINI_API_KEY

adb pair 127.0.0.1:PORT       # ครั้งแรกเท่านั้น
adb connect 127.0.0.1:PORT

bash connect.sh              # ต่อ ADB อัตโนมัติ (หา IP:พอร์ตใหม่เอง)
python -m android_agent --check
python -m android_agent "เปิด Settings ดูเลข Android version"
```

### จุดเด่น

- **ไม่ต้องใช้คอม** — รันใน Termux บนเครื่อง Android ได้เลย
- **ไม่ต้องติดตั้งแพ็กเกจ Python** — ใช้ stdlib ล้วน (`urllib`, `subprocess`)
- **มีระบบขออนุญาต** — หยุดถามก่อนจ่ายเงิน/ลบข้อมูล/ส่งข้อความ (`--confirm risky` เป็นค่าเริ่มต้น)
- **รองรับภาษาไทย** — ผ่าน ADBKeyboard IME
- **ตัวกันวนซ้ำ** — กดจุดเดิมซ้ำเกิน 3 ครั้งจะหยุดเอง ไม่เปลืองโควตา
- **ล็อกการรัน** — กันสองงานแย่งจอกัน (`~/.android_agent/agent.lock`)

### คำสั่งที่มีให้

```bash
python -m android_agent "..."              # รันงาน
python -m android_agent --check            # ตรวจความพร้อม
python -m android_agent --screenshot       # ถ่ายภาพหน้าจอ
python -m android_agent "..." --dry-run    # ดูแผนก่อน ยังไม่กดจริง
python -m android_agent "..." --confirm all # ถามก่อนทุกก้าว
python -m android_agent "..." --json       # ผลลัพธ์เป็น JSON
```

### เทสต์

```bash
python -m unittest discover -s tests -t .
```

### โครงสร้าง

```
android_agent/
├── adb.py      # ADB: ถ่ายจอ, แตะ, พิมพ์, อ่าน accessibility tree
├── agent.py    # ลูป observe → think → act, guard, loop breaker
├── cli.py      # argparse + health check + สรุปผล
├── config.py   # โหลด .env, ผู้ให้บริการ (gemini/groq/openrouter)
├── imaging.py  # ย่อภาพหน้าจอถ้ามี Pillow
├── llm.py      # ไคลเอนต์ OpenAI-compatible ด้วย urllib
├── notify.py   # Telegram (ข้อความ/รูป/อนุมัติ) + terminal
└── safety.py   # ตรวจคำเสี่ยง + ตัดสินใจว่าจะถามไหม
```

---

## ความปลอดภัย

- ไฟล์ `.env` ถูก ignore ไว้แล้ว — **อย่า commit คีย์**
- ใช้ `--dry-run` กับงานใหม่เสมอ
- อ่านหัวข้อ "ความปลอดภัย" ใน [SETUP_TH.md](SETUP_TH.md) ก่อนใช้กับแอปการเงิน
