#!/usr/bin/env bash
# fix-adb.sh — หา IP + พอร์ตให้ถูกต้องบน Android 15 / ColorOS แล้วทดสอบให้ชัดว่า
# อะไรคือสาเหตุจริง (พอร์ตตาย / pair ไม่ผ่าน / ต้องกด Allow)
#
# ทำไมต้องมีสคริปต์นี้:
#   • Android 15 บล็อก `settings get ...` → อ่านสถานะ Wi-Fi ตรง ๆ ไม่ได้
#   • Termux บนเครื่องนี้ไม่มี `ip` และ `ifconfig` → หา IP เองไม่ได้
#   • mDNS ยังทำงาน → ใช้เป็นแหล่งพอร์ตหลัก
#
# วิธีใช้:  bash fix-adb.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
q()    { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — pkg install android-tools"; exit 1; }
command -v python >/dev/null 2>&1 || { bad "ไม่พบ python"; exit 1; }

# ---------------------------------------------------------------------------
# IP: หาให้ได้แม้ไม่มี ip/ifconfig (Android 15 + Termux)
# ---------------------------------------------------------------------------
detect_ip() {
  local out=""

  # 1) Termux:API — แม่นที่สุด เพราะอ่านจาก Wi-Fi จริง
  if command -v termux-wifi-connectioninfo >/dev/null 2>&1; then
    out=$(termux-wifi-connectioninfo 2>/dev/null | python -c '
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get("ip", "") or "")
except Exception:
    print("")
' 2>/dev/null)
    case "$out" in
      ""|"0.0.0.0"|"127.0.0.1"|169.254.*) out="" ;;
      *) printf '%s' "$out"; return 0 ;;
    esac
  fi

  # 2) ให้ kernel บอกเองผ่าน UDP socket (ไม่ต้องต่อเน็ตจริง)
  out=$(python - <<'PY' 2>/dev/null
import socket
for probe in ("1.1.1.1", "8.8.8.8"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect((probe, 53))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith(("127.", "169.254.")):
            print(ip)
            break
    except OSError:
        continue
PY
)
  [ -n "$out" ] && { printf '%s' "$out"; return 0; }

  # 3) เครื่องมือเดิม (ถ้ามี)
  if command -v ip >/dev/null 2>&1; then
    out=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}')
    [ -n "$out" ] && { printf '%s' "$out"; return 0; }
    out=$(ip -4 addr show 2>/dev/null | awk '/inet /{sub("/.*","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
    [ -n "$out" ] && { printf '%s' "$out"; return 0; }
  fi
  if command -v ifconfig >/dev/null 2>&1; then
    out=$(ifconfig 2>/dev/null | awk '/inet /{sub("addr:","",$2); if ($2 !~ /^127\./) {print $2; exit}}')
    [ -n "$out" ] && { printf '%s' "$out"; return 0; }
  fi

  return 1
}

# ---------------------------------------------------------------------------
# TCP probe — ใช้ bash builtin ไม่ต้องมี nc
# ---------------------------------------------------------------------------
tcp_open() {
  local host="$1" port="$2"
  if command -v timeout >/dev/null 2>&1; then
    timeout 3 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null && return 0
    return 1
  fi
  (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null && return 0
  return 1
}

online() {
  # รองรับทั้ง "serial\tdevice" และ "serial\tdevice product:x model:y" (แบบ -l)
  adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device([[:space:]]|$)'
}

show_devices() { adb devices -l 2>/dev/null | sed 's/^/    /'; }

# ---------------------------------------------------------------------------
say "1) หา IP และพอร์ต"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

IP="${1:-}"
if [ -z "$IP" ]; then IP=$(detect_ip || true); fi

if [ -z "$IP" ]; then
  bad "หา IP ไม่ได้ — Wi-Fi อาจไม่ได้ต่อ"
  q "เปิด Settings → Wi-Fi ต่อให้เรียบร้อย แล้วรันอีกครั้ง"
  exit 1
fi
ok "IP: ${BOLD}${IP}${OFF}"

PORTS=""
if [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  MDNS=$(timeout 25 python "${SCRIPT_DIR}/find_port.py" 2>/dev/null \
    | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' | sort -n -u || true)
  PORTS="$MDNS"
fi

if [ -n "$PORTS" ]; then
  ok "mDNS ประกาศพอร์ต: ${BOLD}$(printf '%s' "$PORTS" | tr '\n' ' ')${OFF}"
else
  warn "mDNS ไม่พบพอร์ต — จะให้คุณอ่านจากหน้าจอ"
fi

# ---------------------------------------------------------------------------
say "2) ทดสอบว่าพอร์ตมีใครฟังอยู่จริงไหม"
if [ -z "$PORTS" ]; then
  printf "  เปิด Settings → System → Developer options → Wireless debugging\\n"
  printf "  อ่านบรรทัด 'ที่อยู่ IP และพอร์ต' แล้วพิมพ์เฉพาะพอร์ต (เช่น 41087): "
  read -r MANUAL_PORT || true
  [ -z "$MANUAL_PORT" ] && { bad "ไม่ได้ใส่พอร์ต"; exit 1; }
  PORTS="$MANUAL_PORT"
fi

OPEN_PORTS=""
for p in $PORTS; do
  lan_open=0; lo_open=0
  tcp_open "$IP" "$p" && lan_open=1
  tcp_open 127.0.0.1 "$p" && lo_open=1

  if [ "$lan_open" = 1 ] || [ "$lo_open" = 1 ]; then
    ok "พอร์ต ${BOLD}${p}${OFF} เปิดอยู่ $( [ "$lan_open" = 1 ] && printf '(LAN)' ; [ "$lo_open" = 1 ] && printf ' (loopback)' )"
    OPEN_PORTS="${OPEN_PORTS} ${p}"
  else
    bad "พอร์ต ${p} ไม่มีใครฟัง — เก่าไปแล้ว"
  fi
done

if [ -z "$OPEN_PORTS" ]; then
  say "สรุป: พอร์ตที่ mDNS ประกาศตายหมด"
  cat <<EOF

  mDNS ประกาศพอร์ตเก่าค้างไว้ แต่ไม่มีอะไรรอรับแล้ว
  (เกิดเมื่อเปิด-ปิด Wireless debugging หลายรอบ)

  วิธีแก้:
    1. เปิด Settings → System → Developer options → Wireless debugging
    2. ปิดสวิตช์ แล้วเปิดใหม่
    3. รันสคริปต์นี้อีกครั้ง:  ${BOLD}bash fix-adb.sh${OFF}

EOF
  exit 1
fi

# ---------------------------------------------------------------------------
say "3) ลองเชื่อมต่อ"
for p in $OPEN_PORTS; do
  for host in "$IP" 127.0.0.1; do
    printf "  %-28s " "${host}:${p}"
    OUT=$(timeout 20 adb connect "${host}:${p}" 2>&1 || true)
    printf "${DIM}%s${OFF}\n" "$OUT"
    if online; then
      ok "เชื่อมต่อสำเร็จ"
      break 2
    fi
  done
done

say "ผลลัพธ์"
show_devices

if online; then
  printf "\n  ขั้นต่อไป:\n"
  printf "    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

# ---------------------------------------------------------------------------
say "4) วิเคราะห์สาเหตุ"
STATE=$(adb devices 2>/dev/null | tail -n +2 | awk '{print $2}' | head -1)
case "${STATE:-}" in
  unauthorized)
    bad "อุปกรณ์ตอบ 'unauthorized' — ยังไม่ได้กด Allow บนมือถือ"
    cat <<EOF

  ดูหน้าจอมือถือตอนนี้ จะมีกล่อง:
      'Allow USB debugging?'
      fingerprint: xx:xx:...
  กด ${BOLD}Allow${OFF} (หรือ 'อนุญาต') แล้วรัน ${BOLD}bash fix-adb.sh${OFF} อีกครั้ง

  ถ้าไม่มีกล่องเด้งขึ้น ให้เพิกถอนคีย์เก่าก่อน:
      rm ~/.android/adbkey ~/.android/adbkey.pub
  แล้วเชื่อมต่อใหม่ (จะได้กล่อง Allow อีกครั้ง)

EOF
    ;;
  offline)
    bad "อุปกรณ์ขึ้น 'offline' — adb server กับมือถือคุยกันไม่รู้เรื่อง"
    cat <<EOF

  วิธีแก้: ปิด-เปิด Wireless debugging แล้วรันซ้ำ
     ${BOLD}bash fix-adb.sh${OFF}
EOF
    ;;
  *)
    bad "พอร์ตเปิดอยู่ แต่ adb ต่อไม่ผ่าน — คีย์ pair ไม่ตรงกัน"
    cat <<EOF

  แปลว่า pair ตอนนั้นไม่สำเร็จจริง (adb ขึ้น protocol fault แต่ไม่ได้ pair ให้)

  วิธีแก้ (ทำตามลำดับ):
    1. เปิด Settings → Developer options → Wireless debugging
    2. แตะ 'ยกเลิกการจับคู่' ทุกอุปกรณ์ที่มี (ถ้ามี)
    3. แตะ ${BOLD}'จับคู่กับอุปกรณ์ด้วยรหัส'${OFF} → ได้รหัส 6 หลักใหม่
    4. รัน ${BOLD}bash setup-adb.sh${OFF} แล้วกรอก IP:พอร์ต + รหัสจากกล่องขาว
       (ใช้ split screen เพื่อไม่ให้กล่องปิด)
    5. รัน ${BOLD}bash fix-adb.sh${OFF} อีกครั้งเพื่อเชื่อมต่อ

  หมายเหตุ: ถ้าเห็นกล่อง 'Allow USB debugging?' บนมือถือ ให้กด Allow ด้วย

EOF
    ;;
esac
exit 1
