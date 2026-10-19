#!/usr/bin/env bash
# find_port.sh — หาพอร์ต ADB ไร้สายของมือถือ แล้วเชื่อมต่อให้
#
# ใช้เมื่อ `adb connect` ไม่ติด / ไม่รู้ว่าพอร์ตปัจจุบันคืออะไร
# ไม่พึ่ง mDNS (adb ใน Termux หลายเวอร์ชันไม่รองรับ)
#
# วิธีใช้:
#   bash find_port.sh
#   bash find_port.sh 192.168.1.156
#
# ตัวแปรปรับได้:
#   ADB_PORT_START / ADB_PORT_END   ช่วงพอร์ตที่จะสแกน (ค่าเริ่มต้น 30000-65535)
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — pkg install android-tools"; exit 1; }

# ---------------------------------------------------------------------------
# IP ของเครื่องนี้ — ลองจากแหล่งที่เชื่อถือได้ก่อน
# ---------------------------------------------------------------------------
detect_ip() {
  local candidate=""
  candidate=$(ip route get 1.1.1.1 2>/dev/null \
    | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  candidate=$(ip -4 addr show 2>/dev/null \
    | awk '/inet /{sub("/.*","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  candidate=$(ifconfig 2>/dev/null \
    | awk '/inet /{sub("addr:","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
  [ -n "$candidate" ] && { printf '%s' "$candidate"; return 0; }

  return 1
}

# ---------------------------------------------------------------------------
# พอร์ตที่กำลัง listen อยู่ — อ่านจาก /proc เร็วกว่าสแกนมาก
# (บางเครื่อง SELinux ปิดไว้ จะอ่านไม่เห็นพอร์ตของ adbd ก็ไม่เป็นไร)
# ---------------------------------------------------------------------------
ports_from_proc() {
  local start="${1:-30000}" end="${2:-65535}"
  for f in /proc/net/tcp /proc/net/tcp6; do
    [ -r "$f" ] || continue
    awk 'NR>1 && $4=="0A" {split($2,a,":"); print a[2]}' "$f" 2>/dev/null
  done | while read -r hex; do
    [ -n "$hex" ] || continue
    port=$(printf '%d' "$((16#$hex))" 2>/dev/null) || continue
    [ "$port" -ge "$start" ] && [ "$port" -le "$end" ] && printf '%s\n' "$port"
  done | sort -n -u
}

# ---------------------------------------------------------------------------
# สแกนด้วย bash /dev/tcp (ไม่ต้องใช้ nc/root)
# ---------------------------------------------------------------------------
scan_ports() {
  local ip="$1" start="$2" end="$3"
  seq "$start" "$end" | xargs -P 400 -I{} \
    bash -c 'timeout 0.3 bash -c "exec 3<>/dev/tcp/'"$ip"'/{}" 2>/dev/null && echo {}' \
    2>/dev/null | sort -n -u
}

run_connections() {
  # Accepts either full "IP:PORT" strings or bare port numbers.
  local ip="$1"; shift
  local hosts found=0 item target out
  if [ -z "$ip" ] || [ "$ip" = "127.0.0.1" ]; then hosts="127.0.0.1"; else hosts="$ip 127.0.0.1"; fi

  for item in "$@"; do
    [ -n "$item" ] || continue
    case "$item" in
      *:*)
        printf "  %-24s " "$item"
        out=$(adb connect "$item" 2>&1)
        case "$out" in
          *connected*|*"already connected"*) printf "${GREEN}✓ %s${OFF}\n" "$out"; found=1 ;;
          *)                                 printf "${DIM}%s${OFF}\n" "$out" ;;
        esac
        ;;
      *)
        for host in $hosts; do
          target="${host}:${item}"
          printf "  %-24s " "$target"
          out=$(adb connect "$target" 2>&1)
          case "$out" in
            *connected*|*"already connected"*) printf "${GREEN}✓ %s${OFF}\n" "$out"; found=1 ;;
            *)                                 printf "${DIM}%s${OFF}\n" "$out" ;;
          esac
        done
        ;;
    esac
  done
  return $((1 - found))
}

# ---------------------------------------------------------------------------
IP="${1:-}"
if [ -z "$IP" ]; then
  IP=$(detect_ip || true)
fi
if [ -z "$IP" ]; then
  printf "  ใส่ IP ของมือถือ (ดูจากหน้า Wireless debugging เช่น 192.168.1.156): "
  read -r IP || true
fi
[ -z "$IP" ] && { bad "ไม่รู้ IP"; exit 1; }

PORT_START="${ADB_PORT_START:-30000}"
PORT_END="${ADB_PORT_END:-65535}"

say "หาเครื่องที่ ${IP}"

# ---- 1) มีการเชื่อมต่ออยู่แล้วหรือเปล่า -------------------------------------
if adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$'; then
  ok "เชื่อมต่ออยู่แล้ว:"
  adb devices | tail -n +2 | sed 's/^/    /'
  exit 0
fi

# ---- 2) mDNS (เร็วที่สุด ~5 วินาที) ---------------------------------------
say "1) ค้นหาผ่าน mDNS"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
if command -v python >/dev/null 2>&1 && [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  MDNS_OUT=$(python "${SCRIPT_DIR}/find_port.py" 2>&1 || true)
  MDNS_TARGETS=$(printf '%s\n' "$MDNS_OUT" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || true)
  if [ -n "$MDNS_TARGETS" ]; then
    printf "  เจอ: %s\n" "$(printf '%s' "$MDNS_TARGETS" | tr '\n' ' ')"
    if run_connections "" $MDNS_TARGETS; then
      say "ผลลัพธ์"; adb devices | tail -n +2 | sed 's/^/  /'
      ok "เชื่อมต่อสำเร็จ"
      exit 0
    fi
  else
    warn "mDNS ไม่พบอุปกรณ์ — จะลองวิธีอื่นต่อ"
  fi
else
  warn "ไม่มี python / find_port.py — ข้าม mDNS"
fi

# ---- 3) อ่านพอร์ตจาก /proc ------------------------------------------------
say "2) ตรวจพอร์ตที่เปิดอยู่บนเครื่อง"
PROC_PORTS=$(ports_from_proc "$PORT_START" "$PORT_END" || true)
if [ -n "$PROC_PORTS" ]; then
  printf "  เจอ: %s\n" "$(printf '%s' "$PROC_PORTS" | tr '\n' ' ')"
  if run_connections "$IP" $PROC_PORTS; then
    say "ผลลัพธ์"; adb devices | tail -n +2 | sed 's/^/  /'
    ok "เชื่อมต่อสำเร็จ"
    exit 0
  fi
  warn "พอร์ตที่เห็นยังไม่ใช่ของ adb (ปกติบน Android — SELinux ซ่อนไว้)"
else
  warn "อ่าน /proc ไม่ได้ (ปกติบน Android) — จะสแกนแทน"
fi

# ---- 3) สแกน --------------------------------------------------------------
say "3) สแกนพอร์ต ${PORT_START}-${PORT_END}"
printf "  ${DIM}ใช้เวลาราว 1-3 นาที ปล่อยให้ทำงาน${OFF}\n"

OPEN=$(scan_ports "$IP" "$PORT_START" "$PORT_END" || true)

if [ -z "$OPEN" ]; then
  bad "ไม่พบพอร์ตที่เปิดอยู่เลย"
  cat <<EOF

  แปลว่าเครื่องนี้มองไม่เห็น ${IP} เลย — ตรวจ 3 ข้อนี้:

  1. Wi-Fi เปิดอยู่ไหม (ต้องต่อ Wi-Fi จริง ไม่ใช่ 4G)
     ดูบรรทัด 'ที่อยู่ IP และพอร์ต' ในหน้า Wireless debugging
     ถ้าไม่มี IP ขึ้น แปลว่ายังไม่ต่อ Wi-Fi

  2. Wireless debugging สวิตช์สีฟ้าเปิดอยู่ไหม

  3. IP ที่ใช้ตรงกับที่หน้าจอแสดงไหม (อาจเปลี่ยนวง เช่น 192.168.1.x → 10.0.0.x)

  ถ้า 3 ข้อผ่านหมด ให้ปิด-เปิด Wireless debugging ใหม่ แล้วรันสคริปต์นี้อีกครั้ง

EOF
  exit 1
fi

printf "  เจอพอร์ต: %s\n" "$(printf '%s' "$OPEN" | tr '\n' ' ')"

say "4) ลองเชื่อมต่อ"
run_connections "$IP" $OPEN || true

say "ผลลัพธ์"
adb devices | tail -n +2 | sed 's/^/  /'

if adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$'; then
  ok "เชื่อมต่อสำเร็จ"
  printf "\n  ขั้นต่อไป:\n    ${BOLD}python -m android_agent --check${OFF}\n"
  exit 0
fi

bad "ยังเชื่อมไม่ได้"
cat <<'EOF'

  ถ้าเห็น 'unauthorized' → ดูหน้าจอมือถือ กด Allow
  ถ้าไม่เห็นอุปกรณ์เลย → เปิด-ปิด Wireless debugging ใหม่ แล้วรันซ้ำ
EOF
exit 1
