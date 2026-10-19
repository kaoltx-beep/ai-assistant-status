#!/usr/bin/env bash
# setup-adb.sh — pair + connect ในครั้งเดียว
#
# ปัญหาที่สคริปต์นี้แก้:
#   • พอร์ต connect เปลี่ยนทุกครั้งที่เปิด/ปิด Wireless debugging
#   • หน้าต่าง pairing ปิดทันทีที่สลับแอป
#   • ต้องอ่านตัวเลขจากจอ 2 ครั้ง ห่างกันเป็นนาที → พอร์ตหมดอายุก่อน
#
# วิธีใช้:  bash setup-adb.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
line() { printf "  ${DIM}%s${OFF}\n" "────────────────────────────"; }

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — pkg install android-tools"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"

detect_ip() {
  local c=""
  c=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}')
  [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  c=$(ip -4 addr show 2>/dev/null | awk '/inet /{sub("/.*","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  c=$(ifconfig 2>/dev/null | awk '/inet /{sub("addr:","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}

expand() {  # expand "32887" -> "IP:32887"
  case "$1" in
    *:*) printf '%s' "$1" ;;
    *)   printf '%s:%s' "$2" "$1" ;;
  esac
}

devices_online() {
  adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$'
}

show_devices() {
  adb devices 2>/dev/null | tail -n +2 | sed 's/^/    /'
}

# mDNS discovery via our own resolver (adb's is unsupported in Termux)
discover_targets() {
  [ -f "${SCRIPT_DIR}/find_port.py" ] || return 1
  command -v python >/dev/null 2>&1 || return 1
  python "${SCRIPT_DIR}/find_port.py" 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || return 1
}

# Is anything actually listening on this port?
# "port ตาย" -> พอร์ตเก่า | "port เปิด" แต่ adb ต่อไม่ได้ -> ปัญหา pairing/TLS
tcp_open() {  # $1 = host, $2 = port
  if command -v timeout >/dev/null 2>&1; then
    timeout 2 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null && return 0
    return 1
  fi
  (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null && return 0
  return 1
}

probe_port() {  # $1 = port
  local h

  for h in "$IP" 127.0.0.1; do
    if tcp_open "$h" "$1"; then
      printf "  ${DIM}พอร์ต %s เปิดอยู่ที่ %s${OFF}\n" "$1" "$h"
      return 0
    fi
  done
  printf "  ${YELLOW}พอร์ต %s ไม่มีใครฟังอยู่ (เก่าไปแล้ว)${OFF}\n" "$1"
  return 1
}

try_connect_port() {  # $1 = port ; tries LAN then loopback
  local port="$1" host out found=0
  local hosts
  if [ "$IP" = "127.0.0.1" ]; then hosts="127.0.0.1"; else hosts="$IP 127.0.0.1"; fi

  for host in $hosts; do
    printf "  %-26s " "${host}:${port}"
    out=$(adb connect "${host}:${port}" 2>&1)
    case "$out" in
      *connected*|*"already connected"*)
        if devices_online; then printf "${GREEN}✓${OFF}\n"; found=1; break
        else printf "${YELLOW}ต่อได้แต่ยังไม่ online${OFF}\n"; fi ;;
      *) printf "${DIM}%s${OFF}\n" "$out" ;;
    esac
  done
  return $((1 - found))
}

# ---------------------------------------------------------------------------
IP="${1:-}"

say "เตรียมการ"
line
printf "  ต้องเห็นหน้าจอมือถือพร้อมกัน 2 อย่าง — ใช้ ${BOLD}split screen${OFF}:\n"
printf "    1) หน้า ${BOLD}Wireless debugging${OFF} (มี 'IP address & Port')\n"
printf "    2) หน้า ${BOLD}Pair device with pairing code${OFF} (มีรหัส 6 หลัก)\n"
printf "    วิธีแยกจอ: กดปุ่ม Recent → กดค้างที่การ์ด Termux → Split screen\n"
line
printf "\n  เปิด ${BOLD}Wireless debugging${OFF} → เปิดสวิตช์ → แตะ ${BOLD}'จับคู่กับอุปกรณ์'${OFF}\n"
printf "  แล้วกรอกตัวเลขจาก ${BOLD}กล่องขาว${OFF} ที่เด้งขึ้นมา:\n\n"

printf "  IP:พอร์ต ในกล่องขาว (เช่น 192.168.1.156:32887): "
read -r PAIR_IN || true

# The IP in the pairing box is authoritative — no guessing needed.
case "$PAIR_IN" in
  *:*) IP="${PAIR_IN%%:*}" ;;
esac

if [ -z "$IP" ]; then
  IP=$(detect_ip || true)
  if [ -n "$IP" ]; then
    printf "  ${DIM}ตรวจพบ IP ของเครื่อง: %s${OFF}\n" "$IP"
    printf "  ใช้ IP นี้ไหม? [Y/n]: "
    read -r CONFIRM_IP || true
    case "${CONFIRM_IP:-Y}" in
      n|N)
        printf "  ใส่ IP ของมือถือ: "
        read -r IP || true ;;
    esac
  fi
fi

if [ -z "$IP" ]; then
  bad "ไม่รู้ IP — ดูบรรทัด 'IP address & Port' ในหน้า Wireless debugging"
  exit 1
fi

# Guard against cellular / link-local addresses, which cannot be used.
case "$IP" in
  169.254.*|127.*)
    bad "IP ${IP} ใช้ไม่ได้ (ไม่ใช่ IP ของ Wi-Fi)"
    printf "  เปิด Wi-Fi ก่อน แล้วดู 'IP address & Port' ในหน้า Wireless debugging\n"
    exit 1 ;;
esac
ok "IP: ${BOLD}${IP}${OFF}"

printf "  รหัส 6 หลัก: "
read -r PAIR_CODE || true

if [ -z "$PAIR_IN" ] || [ -z "$PAIR_CODE" ]; then
  bad "ต้องกรอกทั้ง IP:พอร์ต และรหัส"
  exit 1
fi

case "$PAIR_CODE" in
  *[!0-9]*) bad "รหัสต้องเป็นตัวเลขล้วน"; exit 1 ;;
esac
if [ "${#PAIR_CODE}" -ne 6 ]; then
  warn "รหัสที่กรอกมี ${#PAIR_CODE} หลัก (ปกติ 6 หลัก) — ตรวจอีกรอบ"
  printf "  ยืนยันใช้รหัสนี้? [y/N]: "
  read -r CONFIRM_CODE || true
  case "$CONFIRM_CODE" in
    y|Y) : ;;
    *) exit 1 ;;
  esac
fi

PAIR_TARGET=$(expand "$PAIR_IN" "$IP")

say "1) Pair"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true
printf "  adb pair %s %s\n" "$PAIR_TARGET" "$PAIR_CODE"
PAIR_OUT=$(adb pair "$PAIR_TARGET" "$PAIR_CODE" 2>&1 || true)
printf '%s\n' "$PAIR_OUT" | sed 's/^/    /'

case "$PAIR_OUT" in
  *Successfully\ paired*) ok "pair สำเร็จ" ;;
  *protocol\ fault*)
    warn "adb รายงาน protocol fault — มักแปลว่า pair ผ่านแล้วแต่พิมพ์ผลผิด"
    warn "จะลองเชื่อมต่อต่อเลย ถ้าไม่ติดแปลว่า pair ไม่จริง" ;;
  *) warn "pair ไม่สำเร็จ — จะยังลองเชื่อมต่อต่อ" ;;
esac

say "2) หาพอร์ต connect ล่าสุด"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

TARGETS=$(discover_targets || true)
if [ -n "$TARGETS" ]; then
  printf "  mDNS เจอ: %s\n" "$(printf '%s' "$TARGETS" | tr '\n' ' ')"
else
  warn "mDNS ไม่เจอ — จะถามพอร์ตจากคุณ"
  printf "  กลับไปหน้า ${BOLD}Wireless debugging${OFF} อ่านบรรทัด 'IP address & Port'\n"
  printf "  IP:พอร์ต (หรือพิมพ์แค่พอร์ต): "
  read -r CONN_IN || true
  if [ -n "$CONN_IN" ]; then
    TARGETS=$(expand "$CONN_IN" "$IP")
  fi
fi

[ -z "${TARGETS:-}" ] && { bad "ไม่ได้พอร์ต connect"; exit 1; }

say "3) Connect"
CONNECTED=0
for t in $TARGETS; do
  port="${t##*:}"
  probe_port "$port" || true
  if try_connect_port "$port"; then CONNECTED=1; break; fi
done

say "ผลลัพธ์"
show_devices

if [ "$CONNECTED" = 1 ] || devices_online; then
  ok "เชื่อมต่อสำเร็จ"
  printf "\n  ขั้นต่อไป:\n"
  printf "    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

bad "ยังเชื่อมไม่ได้"
cat <<EOF

  ตรวจตามลำดับ (ข้อ 1 พลาดบ่อยสุด):

  1. ${BOLD}Wi-Fi ต้องเปิดอยู่${OFF}
     ดูหน้า Wireless debugging — ถ้าไม่มีบรรทัด 'IP address & Port' แปลว่าไม่มี Wi-Fi
     และอย่าให้จอดับระหว่างทำ (บางเครื่องปิด wireless debugging เมื่อจอล็อก)

  2. ${BOLD}อย่าสลับแอประหว่าง pair${OFF}
     หน้าต่างรหัสจะปิดทันที → ใช้ split screen

  3. ${BOLD}รหัส 6 หลัก เปลี่ยนทุกครั้ง${OFF}
     ถ้าเปิดกล่องใหม่ ต้องใช้รหัสใหม่ ไม่ใช่รหัสเก่า

  4. ถ้าเห็น ${BOLD}unauthorized${OFF} ที่ adb devices
     → ดูหน้าจอมือถือ จะมีกล่อง 'Allow USB debugging?' → กด Allow

  5. ลองปิด-เปิด Wireless debugging ใหม่ แล้วรัน ${BOLD}bash setup-adb.sh${OFF} อีกครั้ง

EOF
exit 1
