#!/usr/bin/env bash
# pair-now.sh — จับคู่ ADB แบบ "อ่านพอร์ตจากหน้าจอ" ไม่สแกน ไม่เดา
#
# ทำไมไม่สแกน: การสแกนช่วง 30000-50000 จะเจอพอร์ตของแอปอื่น ๆ ด้วย
#   adb connect ไปที่พอร์ตพวกนั้น -> adb สร้าง transport ที่ค้าง offline ตลอด
#   พอร์ตที่ถูกต้องมีตัวเดียว คือที่มือถือแสดงไว้ให้เห็นบนจอ

set -u

BOLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'
GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}%s${OFF}\n" "$*"; }
q()    { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"

# ---------- IP ที่ใช้ได้ทั้งหมดของเครื่องนี้ ----------
hosts() {
  local list=""
  if [ -f "$SCRIPT_DIR/find_port.py" ]; then
    list=$(timeout 15 python "$SCRIPT_DIR/find_port.py" --hosts 2>/dev/null \
      | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)
  fi
  if [ -z "$list" ]; then
    local lan
    lan=$(termux-wifi-connectioninfo 2>/dev/null | python -c '
import sys, json
try: print(json.load(sys.stdin).get("ip","") or "")
except Exception: print("")
' 2>/dev/null)
    list=$(printf '%s\n127.0.0.1' "${lan:-}")
  fi
  # loopback ก่อนเสมอ: adb บนเครื่องเดียวกันคุยผ่าน 127.0.0.1 ได้ตรงที่สุด
  { printf '127.0.0.1\n'; printf '%s\n' $list; } | awk '!seen[$0]++'
}

# ---------- อ่านค่าที่ผู้ใช้พิมพ์: รับได้ทั้ง "port" และ "ip:port" ----------
read_port() {  # $1 = prompt  (prompt goes to stderr: stdout is captured)
  local raw=""
  printf "  %s" "$1" >&2
  read -r raw || true
  raw=$(printf '%s' "$raw" | tr -d ' \t\r')
  printf '%s' "${raw##*:}"
}

valid_port() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }

online() { adb devices 2>/dev/null | tr -d '\r' | awk '$2=="device"' | grep -q .; }

# ---------- 1. pair ----------
say "ขั้นที่ 1 — จับคู่"
cat <<'EOF'

  บนมือถือ:
    Settings → System → Developer options → Wireless debugging
    → แตะ 'จับคู่กับอุปกรณ์ด้วยรหัส'

  ในกล่องนั้นจะเห็น 2 อย่าง:
      IP address & port   192.168.1.156:41234     ← เอา 41234
      Wi-Fi pairing code  123456                  ← เอา 6 หลัก

EOF

PAIR_PORT=$(read_port "พอร์ตในกล่องจับคู่ (5 หลัก): ")
if ! valid_port "$PAIR_PORT"; then bad "พอร์ตไม่ถูกต้อง"; exit 1; fi

CODE=$(read_port "รหัส 6 หลัก: ")
if [ "${#CODE}" -ne 6 ]; then bad "รหัสต้อง 6 หลัก (ได้ ${#CODE})"; exit 1; fi

PAIRED=0
for h in $(hosts); do
  printf "  adb pair %s:%s ... " "$h" "$PAIR_PORT"
  OUT=$(timeout 30 adb pair "${h}:${PAIR_PORT}" "$CODE" 2>&1 || true)
  case "$OUT" in
    *Successfully\ paired*) printf "${GREEN}✓${OFF}\n"; PAIRED=1; break ;;
    *"Wrong password"*|*"Failed: Wrong"*) printf "${RED}รหัสผิด/หมดอายุ${OFF}\n"; break ;;
    *) printf "${DIM}%s${OFF}\n" "$(printf '%s' "$OUT" | head -1)" ;;
  esac
done

if [ "$PAIRED" != 1 ]; then
  bad "จับคู่ไม่สำเร็จ"
  q "สาเหตุที่พบบ่อย: กล่องจับคู่ถูกปิดไปแล้ว / รหัสหมดอายุ (รหัสอยู่ได้ ~2 นาที)"
  q "ลองใหม่: กด 'จับคู่กับอุปกรณ์ด้วยรหัส' อีกครั้ง แล้วรันสคริปต์นี้ใหม่"
  exit 1
fi
ok "pair สำเร็จ"

# ---------- 2. connect ----------
say "ขั้นที่ 2 — เชื่อมต่อ"
cat <<'EOF'

  ตอนนี้ทำบนมือถือ:
    1. ปิดกล่องจับคู่ (แตะยกเลิก / กดปุ่มย้อนกลับ)
    2. กลับมาที่หน้า Wireless debugging
    3. อ่านบรรทัด 'IP address & Port' ใต้ชื่ออุปกรณ์

  ⚠️ พอร์ตนี้ไม่เหมือนพอร์ต pair — เลขจะเปลี่ยนใหม่

EOF

CONN_PORT=$(read_port "พอร์ตในหน้า Wireless debugging: ")
if ! valid_port "$CONN_PORT"; then bad "พอร์ตไม่ถูกต้อง"; exit 1; fi

CONNECTED=0
for h in $(hosts); do
  printf "  adb connect %s:%s ... " "$h" "$CONN_PORT"
  OUT=$(timeout 20 adb connect "${h}:${CONN_PORT}" 2>&1 || true)
  printf "${DIM}%s${OFF}\n" "$OUT"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if online; then CONNECTED=1; break 2; fi
    sleep 1
  done
  adb disconnect "${h}:${CONN_PORT}" >/dev/null 2>&1 || true
done

say "ผลลัพธ์"
adb devices 2>/dev/null | tr -d '\r' | sed 's/^/    /'

if [ "$CONNECTED" = 1 ]; then
  if timeout 15 adb shell echo ok 2>/dev/null | grep -q ok; then
    ok "เชื่อมต่อสำเร็จ"
    printf "\n  เริ่มใช้งาน:\n    ${BOLD}python -m android_agent --check${OFF}\n"
    printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n\n"
    exit 0
  fi
  bad "ต่อได้แต่สั่งงานไม่ได้"
  exit 1
fi

# เก็บกวาด transport ที่ค้าง offline ไม่ให้ไปกวนครั้งต่อไป
adb devices 2>/dev/null | tr -d '\r' | awk '$2=="offline" {print $1}' \
  | while read -r dead; do adb disconnect "$dead" >/dev/null 2>&1 || true; done

bad "เชื่อมต่อไม่สำเร็จ"
q "ถ้าขึ้น offline: ตรวจว่าอ่านพอร์ตจากหน้า Wireless debugging (ไม่ใช่ในกล่องจับคู่)"
q "ถ้าต่อไม่ติดเลย: ปิด/เปิด Wireless debugging ใหม่ แล้วอ่านพอร์ตใหม่"
exit 1
