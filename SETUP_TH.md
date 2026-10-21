# ติดตั้ง AI Agent บนมือถือ Android (ฉบับภาษาไทย)

คู่มือนี้พาไปทีละขั้น ตั้งแต่ศูนย์จนได้เอเจนต์ที่ **ดูจอและกดจอแทนคุณได้** ทั้งหมดทำบนมือถือเครื่องเดียว ไม่ต้องใช้คอม

> ⏱ ใช้เวลาประมาณ 30–45 นาที
> 💰 ค่าใช้จ่าย: ฟรี (ใช้ Gemini free tier)
> ⚠️ อ่านข้อ 12 ก่อนตัดสินใจใช้กับบัญชีเงินจริง

---

## 1. สิ่งที่ต้องมี

| สิ่งที่ต้องมี | หมายเหตุ |
|---|---|
| มือถือ Android 7 ขึ้นไป | Android 11+ ดีที่สุด (ต่อ ADB ไร้สายได้ในเครื่อง) |
| Termux | ติดตั้งจาก **F-Droid** เท่านั้น |
| Google account | สำหรับขอ API key ฟรี |
| เน็ต | ใช้ตอนเรียก AI |

---

## 2. ติดตั้ง Termux (จาก F-Droid เท่านั้น)

**อย่าติดตั้งจาก Play Store** — เวอร์ชันนั้นเลิกอัปเดตแล้ว และติดตั้ง `android-tools` ไม่ได้

1. เปิดเบราว์เซอร์ ไปที่ https://f-droid.org/packages/com.termux/
2. ดาวน์โหลด APK แล้วติดตั้ง (อนุญาต "ติดตั้งจากแหล่งที่ไม่รู้จัก" ถ้าระบบถาม)
3. เปิด Termux แล้วรัน:

```bash
pkg update -y && pkg upgrade -y
pkg install python android-tools git nano -y
```

ตรวจว่าได้จริง:

```bash
python --version     # ควรได้ 3.11 ขึ้นไป
adb version          # ควรได้ Android Debug Bridge version ...
```

---

## 3. เปิด Developer options บนมือถือ

1. ไปที่ **Settings → About phone**
2. แตะ **Build number** 7 ครั้ง จนขึ้น "You are now a developer"
3. กลับไป **Settings → System → Developer options**
4. เปิด **Wireless debugging** (Android 11 ขึ้นไป)

> มือถือ Android 10 ลงมา: ต้องเปิด **USB debugging** แล้วต่อสายกับคอมก่อน (ข้ามไปอ่านส่วน "ถ้าเครื่องเก่ากว่า Android 11" ท้ายคู่มือ)

---

## 4. เชื่อม Termux เข้ากับมือถือ (ADB ไร้สาย)

หน้านี้คือจุดที่คนพลาดมากที่สุด เพราะมี **ตัวเลข 2 ชุดที่หน้าตาคล้ายกัน**

| ตัวเลข | หน้าตา | ใช้ทำอะไร |
|---|---|---|
| **IP:พอร์ต (ในกล่องขาว)** | เช่น `192.168.1.156:32887` | ตัวกลางของ `adb pair` |
| **รหัสจับคู่** | 6 หลัก เช่น `105022` | ตัวสุดท้ายของ `adb pair` |

> 📌 **ห้ามใช้ `127.0.0.1` ถ้าหน้าจอแสดง IP จริง** (เช่น OPPO / Xiaomi / Samsung บางรุ่น
> จะขึ้น `192.168.x.x` ในกล่องคู่) ให้ใช้ IP ที่เห็นบนจอตรง ๆ

> ⚠️ **รหัส pair ไม่ใช่เลขเดียวกับพอร์ต** — ถ้าใส่พอร์ตซ้ำลงไปจะขึ้น
> `error: protocol fault (couldn't read status message)`

### ทำไมต้องใช้ split screen

หน้าต่าง "Pair device with pairing code" **จะปิดทันทีที่คุณสลับแอป** ถ้าเปิด Termux เต็มจอ
รหัสจะหายก่อนได้ใช้ ให้แบ่งจอ:

1. เปิด **Settings → System → Developer options → Wireless debugging**
2. แตะ **Pair device with pairing code** (หน้าต่างจะเด้งขึ้นมา)
3. กดปุ่ม **Recent apps** → กดค้างที่การ์ดของ **Termux** → เลือก **Split screen**
4. ตอนนี้ครึ่งบนเป็นหน้าต่าง pair ครึ่งล่างเป็น Termux — เห็นทั้งคู่พร้อมกัน

### เชื่อมต่อ (วิธีที่แนะนำ — ทำรวดเดียว)

```bash
bash setup-adb.sh
```

สคริปต์จะถามตัวเลข **ครั้งเดียว** แล้วทำ pair + หาพอร์ต connect + connect ให้ทันที
เพราะพอร์ต connect เปลี่ยนทุกครั้งที่เปิด-ปิด Wireless debugging การอ่านจอ 2 ครั้งห่างกันเป็นนาที
จึงมักทำให้พอร์ตเก่าไปแล้ว

หรือทำมือก็ได้:

```bash
adb pair 192.168.1.156:32887 105022
```

ถ้าสำเร็จจะขึ้น `Successfully paired to 192.168.1.156:32887`

จากนั้นกลับไปหน้า **Wireless debugging** ดูบรรทัด **IP address & Port**
(เช่น `192.168.1.156:37223` — พอร์ตนี้ **คนละตัว** กับตอน pair) แล้วรัน:

```bash
adb connect 192.168.1.156:37223     # ใช้ค่าที่เห็นบนจอ
adb devices
```

ต้องเห็นแบบนี้:

```
List of devices attached
192.168.1.156:37223	device
```

### ถ้าต่อไม่ติด — รันตัววินิจฉัยก่อน

```bash
bash fix-adb.sh
```

สคริปต์นี้ตอบได้ว่า "ติดตรงไหน" ไม่ใช่แค่ "ไม่ติด":

| สิ่งที่ตรวจ | ถ้าผิดจะบอกว่า |
|---|---|
| IP (ผ่าน termux-api / UDP socket) | หา IP ไม่ได้ → Wi-Fi ไม่ได้ต่อ |
| พอร์ตจาก mDNS | ไม่มีพอร์ต → Wireless debugging ปิด |
| TCP probe ทีละพอร์ต | พอร์ตตาย → ประกาศค้าง ต้องปิด-เปิดใหม่ |
| `adb connect` + `adb devices` | `unauthorized` → ต้องกด Allow |
| คีย์ pair | พอร์ตเปิดแต่ต่อไม่ได้ → pair ไม่จริง ต้อง pair ใหม่ |

> 📌 บน Android 15 คำสั่ง `settings get ...` ถูกบล็อก
> (`Failed transaction (2147483646)`) และ Termux อาจไม่มี `ip`/`ifconfig`
> สคริปต์นี้จึงอ่าน IP จาก `termux-wifi-connectioninfo` และ UDP socket แทน

### ถ้าต่อไม่ติด — ใช้ตัวช่วยอัตโนมัติ

```bash
bash connect.sh
```

ลำดับที่สคริปต์ลองให้:

1. ปิด-เปิด adb server
2. ค้นหาผ่าน mDNS — **สองทาง**: `adb mdns services` และ `find_port.py` (ถาม mDNS เองด้วย Python)
3. อ่านพอร์ตที่ listen อยู่จาก `/proc/net/tcp`
4. สแกนพอร์ต 30000–65535 (~1–3 นาที)
5. ถาม IP:พอร์ตจากคุณเป็นทางสุดท้าย

> ⚠️ adb ใน Termux บางเวอร์ชัน (เช่น 37.0.0p1-2) **ไม่รองรับ mDNS** จะขึ้น
> `adb: mdns is not supported by this version of adb.`
> แต่ Android ยังประกาศบริการ `_adb-tls-connect._tcp` อยู่ → `find_port.py`
> จะถามเองด้วย UDP multicast แล้วได้พอร์ตมาใน ~5 วินาที

**หาเฉพาะพอร์ต (ไม่เชื่อมต่อ):**

```bash
python find_port.py                 # พิมพ์ 192.168.1.156:37223
python find_port.py --connect       # หาแล้วสั่ง adb connect ให้เลย
```

> 💡 **สาเหตุที่พบบ่อยสุด:** พอร์ตเชื่อมต่อเปลี่ยนทุกครั้งที่เปิด-ปิด Wireless debugging
> รหัส pair ที่เคยใช้ได้จึงไม่เกี่ยวกับพอร์ตที่ต้อง connect

### ถ้ายังไม่สำเร็จ

| อาการ | วิธีแก้ |
|---|---|
| `protocol fault (couldn't read status message)` | ใส่พอร์ตซ้ำในช่องรหัส → รหัสต้องเป็น **6 หลัก** |
| `Failed: Wrong password` | รหัสเก่า/หน้าต่างปิดแล้ว → เปิด pair ใหม่ เอารหัสใหม่ |
| `unable to connect` ทุกครั้ง | ใช้ `127.0.0.1` แต่เครื่องต้องการ IP จริง | ใช้ IP จากในกล่องขาว |
| `failed to connect` | ใช้พอร์ต pair แทนพอร์ต connect → ดูบรรทัดใหม่ในหน้า Wireless debugging |
| ขึ้น `offline` | `adb kill-server && adb connect <IP>:<พอร์ต>` |
| หน้าต่าง pair ปิดเอง | ใช้ split screen (ด้านบน) |
| `protocol fault ... : Success` | **pair สำเร็จแล้ว** (บั๊กการพิมพ์ของ adb) → รัน `bash connect.sh` ต่อ |
| `failed to connect` หลัง pair สำเร็จ | พอร์ตเก่า → ดู 'IP address & Port' ใหม่ หรือรัน `bash connect.sh` |

> 💡 พอร์ตทั้งสองตัวเปลี่ยนทุกครั้งที่รีบูตหรือเปิด-ปิด Wireless debugging
> ถ้าเจอ "ไม่พบอุปกรณ์" ให้กลับมาทำข้อ 4 ใหม่ (ใช้ไม่ถึง 1 นาที)

> 💡 ในตัวติดตั้ง `install.sh` มีให้ลองได้ 3 ครั้ง และไม่ต้องตอบคำถาม interactive
> — มันส่งรหัสให้ adb ตรง ๆ

## 4.5 ถ้าใช้ Tailscale (แนะนำถ้ามี)

Tailscale ทำให้มือถือมี IP คงที่ (ช่วง `100.64.0.0/10`) ที่ไม่เปลี่ยนแม้สลับ Wi-Fi/4G
และบางเครื่องที่บล็อก loopback จะต่อ ADB ผ่าน Tailscale ได้

1. เปิดแอป Tailscale บนมือถือ → เชื่อมต่อ
2. ดู IP ในแอป (เช่น `100.94.117.13`)
3. รันสคริปต์ได้เลย — มันจะตรวจเจอ Tailscale เองและลองก่อน IP อื่น

```bash
bash go.sh
```

หรือระบุเอง:

```bash
bash go.sh --host=100.94.117.13
# หรือ
ADB_HOST=100.94.117.13 bash go.sh
```

สคริปต์จะลองทุก IP ที่มี (Tailscale → Wi-Fi → loopback) ทั้งตอน pair และตอน connect
จึงไม่ต้องเดาว่า IP ตัวไหนจะใช้ได้

> 💡 `python find_port.py --hosts` ดูรายการ IP ทั้งหมดที่ตรวจพบ

---

## 5. ให้พิมพ์ภาษาไทยได้ (ADBKeyboard)

`adb` พิมพ์ภาษาไทยตรง ๆ ไม่ได้ ต้องใช้คีย์บอร์ดพิเศษ

1. ดาวน์โหลด APK จาก https://github.com/senzhk/ADBKeyBoard/releases
   (ไฟล์ `ADBKeyboard.apk`)
2. ติดตั้งให้เสร็จ
3. เปิดใช้ผ่าน Termux:

```bash
adb shell ime enable com.android.adbkeyboard/.AdbIME
adb shell ime set com.android.adbkeyboard/.AdbIME
```

4. ตรวจว่าตั้งเป็นคีย์บอร์ดปัจจุบัน:

```bash
adb shell settings get secure default_input_method
# ต้องได้ com.android.adbkeyboard/.AdbIME
```

> ⚠️ ตอนใช้ ADBKeyboard คีย์บอร์ดปกติจะหายไปชั่วคราว ต้องพิมพ์ผ่านเอเจนต์เท่านั้น
> เมื่อเลิกใช้ กลับไปใช้คีย์บอร์ดปกติได้ที่ **Settings → System → Languages & input → On-screen keyboard**
> ระหว่างใช้งานจริง ให้ตั้ง ADBKeyboard เป็นค่าเริ่มต้นไว้เลย เอเจนต์จะพิมพ์ไทยได้ทุกครั้ง

---

## 6. ขอ API key ฟรี (Gemini)

1. เปิด https://aistudio.google.com/apikey แล้วล็อกอินด้วย Google
2. กด **Create API key** → คัดลอกคีย์ (ขึ้นต้นด้วย `AIza...`)
3. อย่าส่งคีย์นี้ให้ใคร และอย่าใส่ใน Git

---

## 7. เอาโค้ดลงเครื่อง

```bash
cd ~
git clone https://github.com/kaoltx-beep/ai-assistant-status.git
cd ai-assistant-status
cp .env.example .env
chmod 600 .env
nano .env
```

แก้ 2 บรรทัดนี้:

```env
AGENT_PROVIDER=gemini
GEMINI_API_KEY=AIza...ใส่คีย์ของคุณตรงนี้
```

บันทึกแล้วออก (ใน nano: `Ctrl+O` → Enter → `Ctrl+X`)

---

## 8. ตรวจความพร้อม

```bash
python -m android_agent --check
```

ควรเห็นแบบนี้:

```
=== ตรวจความพร้อม ===
  ✓ อุปกรณ์ 192.168.1.156:37223 [device]
  ✓ API key: gemini (39 ตัวอักษร)
  ℹ โมเดล: gemini-2.5-flash
  ℹ ระดับยืนยัน: risky
  ℹ Telegram: ไม่ได้ตั้งค่า → จะถามยืนยันใน terminal แทน
=== พร้อมใช้งาน ✅ ===
```

ถ้ามี ✗ ให้แก้ตามข้อ 12

---

## 9. ลองงานแรก

```bash
python -m android_agent "เปิด Settings แล้วบอกว่า Android version อะไร"
```

สิ่งที่ควรเกิดขึ้น:

1. เอเจนต์ถ่ายภาพหน้าจอ
2. วางแผน 2–4 ขั้นตอน
3. แตะ/เลื่อนจอเองทีละก้าว
4. จบแล้วสรุปผลให้ฟัง

ดูภาพหน้าจอที่เอเจนต์เห็นได้ด้วย:

```bash
python -m android_agent --screenshot
```

---

## 10. ตัวอย่างคำสั่งที่ใช้ได้จริง

```bash
# ดูข้อมูลเครื่อง
python -m android_agent "เปิด Settings ดูว่าใช้พื้นที่เก็บข้อมูลไปเท่าไหร่"

# สื่อสาร
python -m android_agent "เปิด LINE อ่านข้อความล่าสุดจากกลุ่มครอบครัว แล้วบอกว่ามีอะไรบ้าง"

# ความบันเทิง
python -m android_agent "เปิด YouTube ค้นหา lo-fi music แล้วเล่นคลิปแรก"

# งานประจำวัน
python -m android_agent "เปิดปฏิทิน สร้างนัดพรุ่งนี้ 10 โมง ชื่อ ประชุมทีม"

# หลายขั้น (แบ่งรันทีละท่อนจะสำเร็จมากกว่า)
python -m android_agent "เปิด Shopee ค้นหาหมวกกันแดด"
python -m android_agent "กรองราคาต่ำสุด แล้วเปิดรายการแรก"
```

ตัวเลือกที่มีประโยชน์:

```bash
--steps 40        # งานยาว ๆ ใช้ก้าวเยอะขึ้น (ค่าเริ่มต้น 25)
--confirm all     # ถามก่อนทุกก้าว (ใช้ตอนลองครั้งแรก)
--confirm none    # ไม่ถามเลย (ระวัง!)
--quiet           # พิมพ์น้อยลง
--json            # ผลลัพธ์เป็น JSON (เอาไปต่อกับสคริปต์อื่น)
--dry-run         # ดูแผนกับความคิดแรก แล้วหยุด ยังไม่กดจริง
```

> 💡 `--dry-run` คือคำสั่งที่ควรใช้ก่อนเสมอ เมื่อลองงานใหม่ที่ยังไม่แน่ใจ

---

## 11. ให้เอเจนต์ขออนุญาตผ่าน Telegram (แนะนำ)

ถ้าไม่ตั้ง Telegram เอเจนต์จะถามในหน้าจอ Termux ซึ่งคุณต้องกลับมาเปิดดูตลอด ถ้าตั้ง Telegram แล้ว **คำขออนุมัติจะเด้งเข้ามือถือ** กด yes/no ได้จากที่ไหนก็ได้

1. เปิด Telegram คุยกับ **@BotFather** → `/newbot` → ตั้งชื่อ → ได้ token มา
2. ส่งข้อความอะไรก็ได้หาบอทที่เพิ่งสร้าง
3. เอา token ไปเปิดดู chat id:

```bash
curl -s "https://api.telegram.org/bot<ใส่_TOKEN>/getUpdates" | head -40
```

หา `"chat":{"id":123456789` — ตัวเลขนั้นคือ chat id

4. เติมใน `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

5. ทดสอบ:

```bash
python -m android_agent "ลบข้อมูลทั้งหมดในเครื่อง" --dry-run
```

จะเห็นข้อความเตือน + คำขออนุมัติเด้งเข้า Telegram (ยังไม่ลบจริงเพราะ `--dry-run`)

---

## 12. ความปลอดภัย — อ่านก่อนใช้กับของจริง

เอเจนต์นี้ **กดจอแทนคุณได้จริง** รวมถึงปุ่มที่กดแล้วเสียเงิน ดังนั้นค่าเริ่มต้นคือ `--confirm risky`:

| เอเจนต์จะถามก่อนเสมอ เมื่อเจอ | ตัวอย่าง |
|---|---|
| คำเกี่ยวกับการเงิน | ชำระเงิน, โอนเงิน, สั่งซื้อ, checkout, pay now |
| คำเกี่ยวกับการลบ | ลบข้อมูล, ลบบัญชี, delete, unsubscribe |
| เปิดแอปการเงิน | ชื่อ package มี bank / wallet / pay |

**สิ่งที่ยังกันไม่ได้** (ต้องระวังเอง):

- ปุ่มที่ไม่มีข้อความ (ไอคอนล้วน) — เอเจนต์เดาจากภาพ อาจกดพลาดได้
- แอปธนาคารที่บล็อกการถ่ายภาพหน้าจอ → เอเจนต์จะมองไม่เห็น (ดีในแง่ความปลอดภัย)
- OTP / 2FA — **อย่าให้เอเจนต์ทำแทน** และอย่าให้ใครขอรหัส
- การอนุมัติอัตโนมัติ (`--yes`) — ใช้เฉพาะเครื่องทดสอบ

**หลักปฏิบัติ**

```bash
chmod 600 .env        # ไฟล์คีย์อ่านได้แค่คุณ
```

- อย่า commit `.env` (มี `.gitignore` กันไว้แล้ว)
- อย่าแชร์ API key ในแชท/ภาพหน้าจอ
- เริ่มจากงานอ่านอย่างเดียวก่อน (เปิดแอป, ดูข้อมูล) ค่อยขยับไปงานที่แก้ข้อมูล
- ถ้าไม่แน่ใจ → `--dry-run`

---

## 13. แก้ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `ไม่พบคำสั่ง adb` | ยังไม่ลง android-tools | `pkg install android-tools -y` |
| `ไม่พบมือถือที่เชื่อมต่อ` | หลุดหลังรีบูต/พักเครื่อง | ทำข้อ 4 ใหม่ (`adb pair` + `adb connect`) |
| `device offline` | adb server ค้าง | `adb kill-server && adb connect <IP>:<พอร์ต>` |
| ภาพหน้าจอดำ | แอปบล็อก screencap (ธนาคาร/DRM) | ใช้กับแอปนั้นไม่ได้ เปลี่ยนแอป |
| พิมพ์ไทยไม่ได้ | ยังไม่ตั้ง ADBKeyboard | ข้อ 5 |
| `API ตอบ 429` | ชนโควตาฟรี | รอ 1 นาที หรือเปลี่ยนไปใช้ Groq (`AGENT_PROVIDER=groq`) |
| `โมเดลตอบไม่เป็น JSON` | โมเดลเล็กเกินไป | เปลี่ยน `AGENT_MODEL` เป็นรุ่นใหญ่ขึ้น |
| กดผิดปุ่มบ่อย | หน้าจอมีแต่ไอคอน ไม่มีข้อความ | เพิ่ม `--steps`, ลอง `--dry-run` ดูว่ามันเห็นอะไร |
| ค้างนานมาก | เน็ตช้า/ภาพใหญ่ | ใส่ `AGENT_IMAGE_WIDTH=720` ใน `.env` |
| แบตหมดเร็ว/หลุดบ่อย | ระบบฆ่า Termux | ตั้ง Termux เป็น "ไม่จำกัดแบตเตอรี่" ใน Settings |

---

## 14. ข้อจำกัดที่ควรรู้

- **แอปธนาคาร/แอปที่บล็อกภาพหน้าจอ** — เอเจนต์มองไม่เห็นจอ จึงทำอะไรไม่ได้
- **แอปที่มีแต่ไอคอนไม่มีข้อความ** (Flutter/React Native บางตัว) — ต้องใช้การเดาจากภาพ ความแม่นยำลดลง
- **แคปชา/ยืนยันตัวตน** — อย่าพึ่งเอเจนต์
- **ภาษาไทย** — ต้องมี ADBKeyboard (ข้อ 5)
- **โควตาฟรี** — Gemini free tier จำกัดจำนวนคำขอต่อนาที/วัน งานยาว ๆ อาจต้องรอ
- **ไม่ควรใช้กับแอปการเงินแบบไม่ดู** — แม้มีระบบถามยืนยัน แต่ปุ่มที่ไม่มีข้อความอาจหลุดได้

---

## 15. ถ้าเครื่องเก่ากว่า Android 11

ต้องต่อผ่านคอม:

```bash
# บนคอม (มี adb ติดตั้งแล้ว)
adb devices                 # เห็นเครื่องแล้ว
adb tcpip 5555              # เปลี่ยนเป็นโหมดไร้สาย
adb shell ip route          # ดู IP มือถือ
adb connect <IP>:5555
```

จากนั้นเอา IP:5555 ไปใส่ใน Termux (`adb connect <IP>:5555`) — มือถือกับคอมต้องอยู่ Wi-Fi เดียวกัน

---

## ภาคผนวก — โครงสร้างโค้ด

```
android_agent/
├── adb.py        # คุยกับมือถือ (ถ่ายจอ, แตะ, พิมพ์, อ่าน UI tree)
├── agent.py      # ลูปหลัก: ดูจอ → คิด → ลงมือ → ตรวจ
├── cli.py        # คำสั่ง python -m android_agent
├── config.py     # อ่านค่า .env / ผู้ให้บริการ AI
├── imaging.py    # ย่อภาพหน้าจอ (ถ้ามี pillow)
├── llm.py        # เรียก API แบบ OpenAI-compatible
├── notify.py     # Telegram + หน้าจอ terminal
└── safety.py     # ตัวตรวจความเสี่ยง + การขออนุญาต
tests/            # เทสต์ 39 ตัว รันด้วย python -m unittest discover -s tests -t .
```
