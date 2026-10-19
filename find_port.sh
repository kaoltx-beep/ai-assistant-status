#!/usr/bin/env bash
# find_port.sh — หาพอร์ต ADB ไร้สายโดยไม่ต้องพึ่ง mDNS
#
# adb ใน Termux บางเวอร์ชันไม่รองรับ `adb mdns services`
# สคริปต์นี้จะสแกนพอร์ตที่เปิดอยู่บนมือถือแล้วลองเชื่อมทีละตัว
#
# วิธีใช้:
#   bash find_port.sh                 # ใช้ IP ที่ตรวจพบอัตโนมัติ
#   bash find_port.sh 192.168.1.156   # ระบุ IP เอง
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb"; exit 1; }

# Best-effort LAN IP of this phone, without external tools.
detect_ip() {
  local candidate=""
  candidate=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  candidate=$(ip -4 addr show 2>/dev/null | awk '/inet /{sub("/.*","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  candidate=$(ifconfig 2>/dev/null | awk '/inet /{sub("addr:","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  return 1
}

IP="${1:-}"
if [ -z "$IP" ]; then
  IP=$(detect_ip || true)
fi
if [ -z "$IP" ]; then
  printf "  ใส่ IP ของมือถือ (เช่น 192.168.1.156): "
  read -r IP || true
fi
[ -z "$IP" ] && { bad "ไม่รู้ IP"; exit 1; }

PORT_START="${ADB_PORT_START:-30000}"
PORT_END="${ADB_PORT_END:-65535}"

say "สแกนพอร์ตบน ${IP}"
printf "  ${DIM}ช่วง %s-%s — ใช้เวลาราว 1-2 นาทีบนมือถือ${OFF}\n" "$PORT_START" "$PORT_END"

# /dev/tcp is a bash builtin: no netcat needed.
scan_one() {
  local host="$1" port="$2"
  (exec 3<>"/dev/tcp/${host}/${port}") >/dev/null 2>&1 && echo "$port"
  exec 3>&- 2>/dev/null || true
}
export -f scan_one 2>/dev/null || true

OPEN=""
if command -v timeout >/dev/null 2>&1; then
  OPEN=$(
    seq "$PORT_START" "$PORT_END" \
      | xargs -P 500 -I{} bash -c 'timeout 0.35 bash -c "exec 3<>/dev/tcp/'"$IP"'/{}" 2>/dev/null && echo {}' 2>/dev/null \
      | sort -n -u
  )
else
  for port in $(seq "$PORT_START" "$PORT_END"); do
    (exec 3<>"/dev/tcp/${IP}/${port}") >/dev/null 2>&1 && echo "$port"
    exec 3>&- 2>/dev/null || true
  done | sort -n -u
fi

if [ -z "$OPEN" ]; then
  warn "ไม่พบพอร์ตที่เปิดอยู่"
  printf "\n  ตรวจว่า:\n"
  printf "    • Wireless debugging เปิดอยู่ (สวิตช์สีฟ้า)\n"
  printf "    • มือถือต่อ Wi-Fi เดียวกับที่แจ้ง IP: %s\n" "$IP"
  printf "    • ลองปิด-เปิด Wireless debugging ใหม่\n"
  exit 1
fi

printf "  เจอพอร์ต: %s\n" "$(printf '%s' "$OPEN" | tr '\n' ' ')"

say "ลองเชื่อมต่อ"
for port in $OPEN; do
  target="${IP}:${port}"
  printf "  %s ... " "$target"
  out=$(adb connect "$target" 2>&1)
  case "$out" in
    *connected*) printf "${GREEN}✓${OFF}\n" ;;
    *)           printf "${DIM}%s${OFF}\n" "$out" ;;
  esac
done

say "ผลลัพธ์"
adb devices | tail -n +2 | sed 's/^/  /'

if adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$'; then
  ok "เชื่อมต่อสำเร็จ"
  printf "\n  ขั้นต่อไป:\n    ${BOLD}python -m android_agent --check${OFF}\n"
  exit 0
fi

bad "ยังเชื่อมไม่ได้"
printf "\n  ถ้าเห็น 'unauthorized' → ดูหน้าจอมือถือ กด Allow\n"
printf "  ถ้าไม่เห็นอะไรเลย → เปิดหน้า Wireless debugging อ่าน 'IP address & Port'\n"
printf "  แล้วรัน: ${BOLD}adb connect <IP>:<พอร์ต>${OFF}\n"
exit 1
