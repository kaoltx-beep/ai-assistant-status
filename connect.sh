#!/usr/bin/env bash
# connect.sh — หาและเชื่อมต่อมือถือผ่าน ADB ไร้สายให้อัตโนมัติ
#
# ใช้เมื่อ:
#   • เพิ่ง pair สำเร็จ แต่ adb connect ไม่ติด
#   • รีบูตมือถือ / ปิด-เปิด Wireless debugging แล้วพอร์ตเปลี่ยน
#   • ไม่อยากพิมพ์ IP:พอร์ตเอง
#
# วิธีใช้:  bash connect.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — pkg install android-tools"; exit 1; }

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

connected() {
  adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$'
}

show_devices() {
  printf "  ${DIM}adb devices:${OFF}\n"
  adb devices 2>/dev/null | tail -n +2 | sed 's/^/    /'
}

# Parse `adb mdns services` for the wireless debugging (connect) endpoint.
# Output looks like:
#   adb-R58M1234-abcdef	_adb-tls-connect._tcp	192.168.1.156:37223
#   adb-R58M1234-abcdef	_adb-tls-pairing._tcp	192.168.1.156:32887
discover_connect_targets() {
  adb mdns services 2>/dev/null \
    | awk '$2 == "_adb-tls-connect._tcp" {print $3}' \
    | sort -u
}

try_connect() {
  target="$1"
  [ -z "$target" ] && return 1
  printf "  ลองเชื่อม %s ... " "$target"
  out=$(adb connect "$target" 2>&1)
  case "$out" in
    *connected*) printf "${GREEN}ok${OFF}\n"; return 0 ;;
    *)           printf "${RED}ไม่สำเร็จ${OFF}  ${DIM}%s${OFF}\n" "$out"; return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
say "1) ปิด adb server เก่าแล้วเปิดใหม่"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true
ok "adb server พร้อม"

if connected; then
  ok "เชื่อมต่อมือถืออยู่แล้ว:"
  adb devices | tail -n +2 | sed 's/^/    /'
  exit 0
fi

say "2) ค้นหามือถือผ่าน mDNS"
mdns_out=$(adb mdns services 2>&1 || true)
found=0

if printf '%s' "$mdns_out" | grep -qi "not supported"; then
  warn "adb เวอร์ชันนี้ไม่รองรับ mDNS — จะสแกนพอร์ตแทน"
else
  targets=$(printf '%s\n' "$mdns_out" | awk '$2 == "_adb-tls-connect._tcp" {print $3}' | sort -u)
  if [ -z "$targets" ]; then
    warn "mDNS ไม่พบอุปกรณ์ — จะสแกนพอร์ตแทน"
  else
    printf "  เจอ: %s\n" "$(printf '%s' "$targets" | tr '\n' ' ')"
    for t in $targets; do
      if try_connect "$t"; then found=1; fi
    done
  fi
fi

if [ "$found" = 0 ]; then
  say "3) สแกนหาพอร์ตที่เปิดอยู่"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
  IP_GUESS=$(detect_ip || true)
  if [ -f "${SCRIPT_DIR}/find_port.sh" ]; then
    if [ -n "${IP_GUESS:-}" ]; then
      bash "${SCRIPT_DIR}/find_port.sh" "$IP_GUESS" || true
    else
      bash "${SCRIPT_DIR}/find_port.sh" || true
    fi
    if connected; then
      ok "เชื่อมต่อสำเร็จ"
      adb devices | tail -n +2 | sed 's/^/    /'
      exit 0
    fi
  else
    warn "ไม่พบ find_port.sh — ข้ามการสแกน"
  fi
  found=0
fi

if [ "$found" = 0 ]; then
  say "4) ยังไม่สำเร็จ — ขอให้ระบุเอง"
  printf "  บนมือถือ: Settings → System → Developer options → Wireless debugging\n"
  printf "  ดูบรรทัด ${BOLD}'IP address & Port'${OFF} (เช่น 192.168.1.156:37223)\n\n"
  printf "  ใส่ IP:พอร์ต แล้ว Enter: "
  read -r manual || true
  manual="$(printf '%s' "$manual" | tr -d '[:space:]')"

  if [ -z "$manual" ]; then
    bad "ไม่ได้ใส่ค่า — ยกเลิก"
    exit 1
  fi

  # Accept a bare port by combining with the phone's LAN IP.
  case "$manual" in
    *:*) : ;;
    *)
      ip=$(ip route 2>/dev/null | awk '/^default/ {print $9; exit}')
      manual="${ip:-127.0.0.1}:${manual}"
      ;;
  esac

  if try_connect "$manual"; then found=1; fi
fi

say "ผลลัพธ์"
show_devices

if connected; then
  serial=$(adb devices | tail -n +2 | grep -E '[[:space:]]device$' | head -1 | cut -f1)
  ok "พร้อมใช้งาน: ${BOLD}${serial}${OFF}"
  printf "\n  ลองสั่งงานแรก:\n"
  printf "    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

bad "ยังเชื่อมไม่ได้"
cat <<'EOF'

  ตรวจตามนี้ทีละข้อ:

  1. Wi-Fi เปิดอยู่ไหม (ต้องต่อ Wi-Fi ไม่ใช่แค่ 4G)
  2. Wireless debugging เปิดอยู่ไหม (สวิตช์ต้องเป็นสีฟ้า)
  3. พอร์ตเปลี่ยนหรือเปล่า — เปิดหน้า Wireless debugging ดู 'IP address & Port'
     แล้วรัน:  adb connect <IP>:<พอร์ตใหม่>
  4. ถ้าขึ้น 'unauthorized' → ดูหน้าจอมือถือ จะมีกล่อง 'Allow USB debugging?' → กด Allow
  5. ยังไม่ได้ pair? → เปิด 'Pair device with pairing code' แล้วรัน:
       adb pair <IP>:<พอร์ตในกล่อง> <รหัส 6 หลัก>
     (ถ้าขึ้น 'protocol fault ... : Success' = pair สำเร็จแล้ว ให้กลับมาข้อ 3)

EOF
exit 1
