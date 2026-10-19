#!/usr/bin/env bash
# repair-pair.sh — ล้างคีย์ adb เก่า แล้ว pair ใหม่แบบสะอาด
#
# ใช้เมื่อ: พอร์ตเปิดอยู่ แต่ adb connect ไม่ผ่าน (คีย์ pair ไม่ตรงกัน)
# ซึ่งเกิดจาก adb ขึ้น "protocol fault (couldn't read status message)"
# แล้วไม่ได้ลงทะเบียนคีย์ให้จริง
#
# วิธีใช้:  bash repair-pair.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
q()    { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
ANDROID_DIR="${ANDROID_SDK_HOME:-$HOME/.android}"
[ -d "$ANDROID_DIR" ] || ANDROID_DIR="$HOME/.android"

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb"; exit 1; }

detect_ip() {
  local out=""
  if command -v termux-wifi-connectioninfo >/dev/null 2>&1; then
    out=$(termux-wifi-connectioninfo 2>/dev/null | python -c '
import sys, json
try:
    print(json.load(sys.stdin).get("ip", "") or "")
except Exception:
    print("")
' 2>/dev/null)
    case "$out" in ""|0.0.0.0|127.0.0.1|169.254.*) out="" ;; esac
  fi
  if [ -z "$out" ]; then
    out=$(python -c '
import socket
for probe in ("1.1.1.1", "8.8.8.8"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1); s.connect((probe, 53))
        ip = s.getsockname()[0]; s.close()
        if ip and not ip.startswith(("127.", "169.254.")):
            print(ip); break
    except OSError:
        continue
' 2>/dev/null)
  fi
  [ -n "$out" ] && { printf '%s' "$out"; return 0; }
  return 1
}

online() {
  adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device([[:space:]]|$)'
}

# ---------------------------------------------------------------------------
say "0) เตรียมความพร้อมบนมือถือ"
cat <<EOF
  ทำ 3 ข้อนี้ก่อน (สำคัญมากสำหรับ OPPO/ColorOS):

  1. Settings → Developer options → เปิด ${BOLD}'Disable permission monitoring'${OFF}
     (ภาษาไทย: ${BOLD}'ปิดการตรวจสอบสิทธิ์'${OFF}) — ถ้ามีข้อนี้
     ColorOS จะเพิกถอนสิทธิ์ ADB เองถ้าไม่ปิด

  2. Settings → Developer options → เปิด ${BOLD}'USB debugging'${OFF} ด้วย
     (ไม่ใช่แค่ Wireless debugging)

  3. ตั้งจอไม่ให้ดับ: Settings → Display → Screen timeout → 10 นาที

EOF
printf "  ทำครบทั้ง 3 ข้อแล้วกด Enter: "
read -r _ || true

# ---------------------------------------------------------------------------
say "1) ล้างคีย์ adb เก่า"
adb kill-server >/dev/null 2>&1 || true
if [ -f "${ANDROID_DIR}/adbkey" ]; then
  BACKUP="${ANDROID_DIR}/adbkey.bak.$(date +%s)"
  mv "${ANDROID_DIR}/adbkey" "$BACKUP" 2>/dev/null && ok "เก็บ adbkey เก่าไว้ที่ $(basename "$BACKUP")"
  mv "${ANDROID_DIR}/adbkey.pub" "${BACKUP}.pub" 2>/dev/null || true
else
  q "ไม่มี adbkey เดิม"
fi

adb start-server >/dev/null 2>&1 || true
if [ -f "${ANDROID_DIR}/adbkey" ]; then
  ok "สร้างคีย์ใหม่แล้ว"
else
  warn "ยังไม่มีคีย์ใหม่ (จะสร้างตอน pair)"
fi
q "ADB_VENDOR_KEYS จะไม่ถูกใช้ — ใช้คีย์ใหม่ล้วน"

# ---------------------------------------------------------------------------
IP="${1:-}"
[ -z "$IP" ] && IP=$(detect_ip || true)

say "2) หาพอร์ต pair และรับรหัส"
q "เปิด Settings → Developer options → Wireless debugging → 'จับคู่กับอุปกรณ์ด้วยรหัส'"
q "ปล่อยกล่องนั้นค้างไว้ (ใช้ split screen) — สคริปต์จะหาพอร์ตให้เอง"

PAIR_TARGET=""
if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  printf "  กำลังหาพอร์ต pair ผ่าน mDNS ... "
  PAIR_LINE=$(timeout 25 python "${SCRIPT_DIR}/find_port.py" --pair 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' | head -1 || true)
  if [ -n "$PAIR_LINE" ]; then
    printf "${GREEN}เจอ${OFF}\n"
    ok "พอร์ต pair: ${BOLD}${PAIR_LINE}${OFF}  (ไม่ต้องพิมพ์เอง)"
    PAIR_TARGET="$PAIR_LINE"
    IP="${PAIR_LINE%%:*}"
  else
    printf "${YELLOW}ไม่เจอ${OFF}\n"
  fi
fi

if [ -z "$PAIR_TARGET" ]; then
  warn "mDNS ไม่ประกาศพอร์ต pair — ต้องพิมพ์เอง"
  q "ในกล่องขาว มี 2 บรรทัด:"
  q "   'รหัสการจับคู่ Wi-Fi'   → 6 หลัก  (เช่น 105022)"
  q "   'ที่อยู่ IP และพอร์ต'    → เช่น 192.168.1.156:32887"
  q "ช่องต่อไปนี้ต้องการ ${BOLD}ที่อยู่ IP และพอร์ต${OFF} ไม่ใช่รหัส"
  printf "  IP:พอร์ต ในกล่องขาว: "
  read -r PAIR_IN || true
  [ -z "$PAIR_IN" ] && { bad "ไม่ได้กรอก"; exit 1; }
  case "$PAIR_IN" in
    *:*) : ;;
    *) PAIR_IN="${IP}:${PAIR_IN}" ;;
  esac
  PAIR_TARGET="$PAIR_IN"
fi

# --- ตรวจพอร์ต ---
PAIR_PORT="${PAIR_TARGET##*:}"
case "$PAIR_PORT" in
  ""|*[!0-9]*)
    bad "พอร์ต '${PAIR_PORT}' ไม่ใช่ตัวเลข"
    q "ดูบรรทัด 'ที่อยู่ IP และพอร์ต' ในกล่องขาวอีกครั้ง"
    exit 1 ;;
esac
if [ "$PAIR_PORT" -gt 65535 ] || [ "$PAIR_PORT" -lt 1 ]; then
  bad "พอร์ต ${PAIR_PORT} ไม่ถูกต้อง (ต้อง 1-65535)"
  q "คุณอาจกรอกรหัส 6 หลักลงในช่องพอร์ต"
  q "พอร์ตคือเลข ${BOLD}5 หลัก${OFF} บรรทัด 'ที่อยู่ IP และพอร์ต' (เช่น 32887)"
  q "รหัสคือเลข ${BOLD}6 หลัก${OFF} บรรทัด 'รหัสการจับคู่ Wi-Fi' (เช่น 105022)"
  exit 1
fi
[ -z "$IP" ] && IP="${PAIR_TARGET%%:*}"

printf "  รหัส 6 หลัก (บรรทัด 'รหัสการจับคู่ Wi-Fi'): "
read -r PAIR_CODE || true
case "$PAIR_CODE" in
  ""|*[!0-9]*) bad "รหัสต้องเป็นตัวเลขล้วน"; exit 1 ;;
esac
if [ "${#PAIR_CODE}" -ne 6 ]; then
  bad "รหัสต้อง 6 หลัก (ที่กรอกมา ${#PAIR_CODE} หลัก)"
  q "ถ้าคุณกรอกพอร์ตมา แปลว่าสลับช่อง — รหัสอยู่ในบรรทัด 'รหัสการจับคู่ Wi-Fi'"
  exit 1
fi
if [ "$PAIR_CODE" = "$PAIR_PORT" ]; then
  bad "รหัสกับพอร์ตเป็นเลขเดียวกัน — น่าจะสลับช่อง"
  exit 1
fi

say "3) Pair"
printf "  adb pair %s %s\n" "$PAIR_TARGET" "$PAIR_CODE"
PAIR_OUT=$(timeout 40 adb pair "$PAIR_TARGET" "$PAIR_CODE" 2>&1 || true)
printf '%s\n' "$PAIR_OUT" | sed 's/^/    /'

PAIRED=0
case "$PAIR_OUT" in
  *Successfully\ paired*) PAIRED=1 ;;
  *protocol\ fault*Success*) PAIRED=1; warn "adb รายงาน protocol fault แต่ลงท้าย Success — จะตรวจจากผลจริง" ;;
  *"Wrong password"*) bad "รหัสผิดหรือหมดอายุ — เปิดกล่องใหม่ เอารหัสใหม่" ;;
esac

# ---------------------------------------------------------------------------
say "4) หาพอร์ต connect แล้วเชื่อมต่อ"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

PORTS=""
if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  PORTS=$(timeout 25 python "${SCRIPT_DIR}/find_port.py" 2>/dev/null \
    | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' | sort -n -u || true)
fi

if [ -z "$PORTS" ]; then
  warn "mDNS ไม่เจอ — อ่านจากหน้า Wireless debugging เอง"
  printf "  พอร์ต connect (บรรทัด 'ที่อยู่ IP และพอร์ต'): "
  read -r PORT_IN || true
  PORTS="$PORT_IN"
fi
[ -z "$PORTS" ] && { bad "ไม่ได้พอร์ต"; exit 1; }
q "พอร์ตที่จะลอง: $(printf '%s' "$PORTS" | tr '\n' ' ')"

CONNECTED=0
for p in $PORTS; do
  for host in "$IP" 127.0.0.1; do
    printf "  %-26s " "${host}:${p}"
    OUT=$(timeout 20 adb connect "${host}:${p}" 2>&1 || true)
    printf "${DIM}%s${OFF}\n" "$OUT"
    if online; then CONNECTED=1; break 2; fi
    sleep 1
  done
done

say "ผลลัพธ์"
adb devices -l 2>/dev/null | sed 's/^/    /'

if [ "$CONNECTED" = 1 ]; then
  ok "เชื่อมต่อสำเร็จ"
  printf "\n  ขั้นต่อไป:\n"
  printf "    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

# ---------------------------------------------------------------------------
DELAYED=0
for p in $PORTS; do
  printf "  ลองซ้ำอีกรอบใน 3 วินาที: %s\n" "$p"
  sleep 3
  timeout 20 adb connect "${IP}:${p}" >/dev/null 2>&1 || true
  timeout 20 adb connect "127.0.0.1:${p}" >/dev/null 2>&1 || true
  if online; then DELAYED=1; break; fi
done

if [ "$DELAYED" = 1 ]; then
  ok "เชื่อมต่อสำเร็จ (รอบที่สอง)"
  adb devices -l 2>/dev/null | sed 's/^/    /'
  exit 0
fi

say "ยังไม่สำเร็จ — ตรวจ 3 อย่างนี้"
cat <<EOF

  1. ${BOLD}ดูบนมือถือ: 'อุปกรณ์ที่จับคู่ไว้' (Paired devices)${OFF}
     Settings → Developer options → Wireless debugging → เลื่อนลงล่างสุด
     • ถ้ามีรายการอยู่ → pair สำเร็จ ปัญหาอยู่ที่ตัว connect
     • ถ้าไม่มี → pair ไม่สำเร็จจริง ให้ทำข้อ 2

  2. ${BOLD}เพิกถอนการจับคู่ทั้งหมด แล้ว pair ใหม่${OFF}
     กด 'ยกเลิกการจับคู่' ทุกรายการในหน้า Paired devices
     แล้วรันสคริปต์นี้อีกครั้ง

  3. ${BOLD}ตรวจว่ากล่อง Allow เด้งขึ้นไหม${OFF}
     ตอน connect ให้มองหน้าจอมือถือ — ถ้ามีกล่อง
     'Allow USB debugging?' ให้กด ${BOLD}Allow${OFF} ทันที
     (บางเครื่องไม่เด้งถ้าเปิด 'Disable permission monitoring' ไม่ครบ)

  ถ้าทั้ง 3 ข้อผ่านแล้วยังไม่ติด: ปิด-เปิด Wireless debugging
  แล้วรัน ${BOLD}bash repair-pair.sh${OFF} อีกครั้ง

EOF
exit 1
