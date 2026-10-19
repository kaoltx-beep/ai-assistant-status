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
PAIR_PORT_ARG=""
IP=""
for arg in "$@"; do
  case "$arg" in
    --port=*) PAIR_PORT_ARG="${arg#*=}" ;;
    *[!0-9]*)
      # มีอะไรที่ไม่ใช่ตัวเลข (เช่น จุด) → เป็น IP
      [ -z "$IP" ] && IP="$arg" ;;
    *)
      # ตัวเลขล้วน → พอร์ต (ต้องไม่เกิน 65535)
      if [ "${#arg}" -le 5 ] && [ "$arg" -le 65535 ]; then
        PAIR_PORT_ARG="$arg"
      else
        bad "พอร์ต '$arg' ไม่ถูกต้อง (ต้อง 1-65535)"
        exit 1
      fi ;;
  esac
done
[ -z "$IP" ] && IP=$(detect_ip || true)

say "2) เตรียมกล่องจับคู่"
q "ทำตามนี้ก่อน (ช้าไม่ได้ เพราะรหัสมีอายุสั้น):"
q "  1. เปิด Settings → Developer options → Wireless debugging"
q "  2. แตะ ${BOLD}'จับคู่กับอุปกรณ์ด้วยรหัส'${OFF} — ปล่อยกล่องนั้นค้างไว้"
q "  3. กลับมาที่ Termux แล้วกด Enter"
q ""
q "สคริปต์จะสแกนหาพอร์ตก่อน (ไม่กี่วินาที) แล้วค่อยถามรหัส"
q "จากนั้น pair ทันที — รหัสจะไม่ทันหมดอายุ"

printf "\n  เปิดกล่องจับคู่เรียบร้อยแล้วกด Enter: "
read -r _ || true

# พอร์ต connect ที่รู้อยู่แล้ว — ตัดออกจากผลสแกน
KNOWN_CONNECT=""
if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  KNOWN_CONNECT=$(timeout 20 python "${SCRIPT_DIR}/find_port.py" 2>/dev/null \
    | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' ' || true)
fi

say "3) สแกนหาพอร์ต pair"
CANDS=""

if [ -n "${PAIR_PORT_ARG:-}" ]; then
  ok "ใช้พอร์ตที่ระบุ: ${BOLD}${PAIR_PORT_ARG}${OFF}"
  CANDS="$PAIR_PORT_ARG"
else
  # mDNS ก่อน (เร็วที่สุด) แล้วค่อยสแกน
  if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
    printf "  mDNS ... "
    LINE=$(timeout 20 python "${SCRIPT_DIR}/find_port.py" --pair 2>/dev/null \
      | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' | head -1 || true)
    if [ -n "$LINE" ]; then
      printf "${GREEN}เจอ %s${OFF}\n" "$LINE"
      CANDS="${LINE##*:}"
      [ -z "$IP" ] && IP="${LINE%%:*}"
    else
      printf "${YELLOW}ไม่เจอ${OFF}\n"
    fi
  fi

  if [ -z "$CANDS" ]; then
    printf "  สแกน TCP ... "
    SCAN_OUT=$(timeout 200 python "${SCRIPT_DIR}/find_port.py" --scan-pair \
      --ip "$IP" --port-start 30000 --port-end 49999 \
      --exclude "$KNOWN_CONNECT" 2>/dev/null || true)
    CANDS=$(printf '%s\n' "$SCAN_OUT" | grep -E '^[0-9]+\.' \
      | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' ')
    if [ -n "$CANDS" ]; then
      printf "${GREEN}เจอ %s${OFF}\n" "$(printf '%s' "$CANDS" | tr -s ' ')"
    else
      printf "${YELLOW}ไม่เจอ${OFF}\n"
    fi
  fi
fi

if [ -z "$CANDS" ]; then
  bad "ไม่พบพอร์ต pair"
  q "ตรวจว่า: กล่อง 'จับคู่กับอุปกรณ์ด้วยรหัส' ยังเปิดอยู่"
  q "ถ้ากล่องปิดไปแล้ว ให้เปิดใหม่แล้วรันสคริปต์นี้อีกครั้ง"
  exit 1
fi

printf "  รหัส 6 หลัก (บรรทัด 'รหัสการจับคู่ Wi-Fi'): "
read -r PAIR_CODE || true

case "$PAIR_CODE" in
  *:*) PAIR_CODE="${PAIR_CODE##*:}" ;;
esac
if [ -z "$PAIR_CODE" ]; then
  bad "ยังไม่ได้กรอกรหัส"
  q "รหัสอยู่ในบรรทัด 'รหัสการจับคู่ Wi-Fi' ในกล่องขาว (6 หลัก)"
  exit 1
fi
case "$PAIR_CODE" in
  *[!0-9]*) bad "รหัสต้องเป็นตัวเลขล้วน"; exit 1 ;;
esac
if [ "${#PAIR_CODE}" -ne 6 ]; then
  bad "รหัสต้อง 6 หลัก (ที่กรอกมา ${#PAIR_CODE} หลัก)"
  exit 1
fi

PAIRED=0
PAIR_PORT=""
for p in $CANDS; do
  printf "  adb pair %s:%s ... " "$IP" "$p"
  OUT=$(timeout 30 adb pair "${IP}:${p}" "$PAIR_CODE" 2>&1 || true)
  case "$OUT" in
    *Successfully\ paired*|*"protocol fault"*Success*)
      printf "${GREEN}✓${OFF}\n"; PAIRED=1; PAIR_PORT="$p"; break ;;
    *"Wrong password"*|*"Failed: Wrong"*)
      printf "${RED}รหัสผิด/หมดอายุ${OFF}\n"
      break ;;
    *)
      printf "${DIM}%s${OFF}\n" "$(printf '%s' "$OUT" | head -1)" ;;
  esac
done

if [ "$PAIRED" = 0 ]; then
  bad "pair ไม่สำเร็จ"
  q "สาเหตุที่พบบ่อย: รหัสหมดอายุ (อายุ ~2 นาที)"
  q "  → เปิดกล่องจับคู่ใหม่ เอารหัสใหม่ แล้วรันสคริปต์นี้อีกครั้ง"
  q "ถ้ารู้พอร์ตจากกล่องขาว ใช้: ${BOLD}bash repair-pair.sh --port=XXXXX${OFF}"
  exit 1
fi
ok "pair สำเร็จ"

say "4) หาพอร์ต connect แล้วเชื่อมต่อ"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

CONNECT_PORTS=""
if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  printf "  ลอง mDNS ... "
  MDNS_PORTS=$(timeout 25 python "${SCRIPT_DIR}/find_port.py" 2>/dev/null \
    | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' ' || true)
  if [ -n "$MDNS_PORTS" ]; then
    printf "${GREEN}เจอ %s${OFF}\n" "$(printf '%s' "$MDNS_PORTS" | tr -s ' ')"
    CONNECT_PORTS="$MDNS_PORTS"
  else
    printf "${YELLOW}ไม่เจอ${OFF}\n"
  fi

  if [ -z "$CONNECT_PORTS" ]; then
    warn "mDNS ไม่ประกาศพอร์ต connect — จะสแกนแทน"
    printf "  กำลังสแกน ... "
    SCAN_OUT=$(timeout 240 python "${SCRIPT_DIR}/find_port.py" --scan-pair \
      --ip "$IP" --exclude "${PAIR_PORT:-}" 2>/dev/null || true)
    CONNECT_PORTS=$(printf '%s\n' "$SCAN_OUT" | grep -E '^[0-9]+\.' \
      | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' ')
    if [ -n "$CONNECT_PORTS" ]; then
      printf "${GREEN}เจอ %s${OFF}\n" "$(printf '%s' "$CONNECT_PORTS" | tr -s ' ')"
    else
      printf "${YELLOW}ไม่เจอ${OFF}\n"
    fi
  fi
fi

# ตัดพอร์ต pair ออก (ต่อไม่ติดแน่นอน)
if [ -n "${PAIR_PORT:-}" ]; then
  CONNECT_PORTS=$(printf '%s\n' $CONNECT_PORTS | grep -vx "$PAIR_PORT" | tr '\n' ' ' || true)
fi

if [ -z "${CONNECT_PORTS:-}" ]; then
  warn "หาเองไม่เจอ — อ่านจากหน้า Wireless debugging"
  q "บรรทัด 'ที่อยู่ IP และพอร์ต' (เช่น ${IP}:41087)"
  printf "  พอร์ต connect: "
  read -r PORT_IN || true
  CONNECT_PORTS="$PORT_IN"
fi
[ -z "${CONNECT_PORTS:-}" ] && { bad "ไม่ได้พอร์ต connect"; exit 1; }
q "พอร์ตที่จะลอง: $(printf '%s' "$CONNECT_PORTS" | tr -s ' ')"

CONNECTED=0
HOSTS="$IP 127.0.0.1"
[ "$IP" = "127.0.0.1" ] && HOSTS="127.0.0.1"
for p in $CONNECT_PORTS; do
  for host in $HOSTS; do
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

DELAYED=0
for p in ${CONNECT_PORTS:-}; do
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
