#!/usr/bin/env bash
# diagnose.sh — เก็บข้อมูลจริงจากเครื่องเพื่อหาสาเหตุที่ ADB ไร้สายต่อไม่ติด
#
# วิธีใช้:  bash diagnose.sh
# แล้วคัดลอกผลลัพธ์ทั้งหมดส่งกลับมา (ไม่มีข้อมูลลับ — ไม่พิมพ์ API key)
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

hdr() { printf "\n${BOLD}${CYAN}=== %s ===${OFF}\n" "$*"; }
ok()  { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
no()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
q()   { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"

# ---------------------------------------------------------------------------
hdr "1. สภาพแวดล้อม"
q "วันที่: $(date)"
q "Termux: $([ -d /data/data/com.termux/files/usr ] && echo ใช่ || echo ไม่ใช่)"
q "Android: $(getprop ro.build.version.release 2>/dev/null) (SDK $(getprop ro.build.version.sdk 2>/dev/null))"
q "รุ่น: $(getprop ro.product.model 2>/dev/null)"
q "ROM: $(getprop ro.build.version.opporom 2>/dev/null || getprop ro.miui.ui.version.name 2>/dev/null || echo '-')"
q "adb: $(adb version 2>/dev/null | head -1)"

if command -v python >/dev/null 2>&1; then
  ok "python $(python --version 2>&1 | awk '{print $2}')"
else
  no "ไม่พบ python"
fi

# ---------------------------------------------------------------------------
hdr "2. สถานะ Wi-Fi"
WIFI_ON=$(settings get global wifi_on 2>/dev/null || echo "?")
q "wifi_on = ${WIFI_ON}   (1 = เปิด, 0 = ปิด)"
case "$WIFI_ON" in
  1) ok "Wi-Fi เปิด" ;;
  0) no "Wi-Fi ปิดอยู่ — ADB ไร้สายใช้ไม่ได้" ;;
  *) q "อ่านค่าไม่ได้ (Android 15 บล็อกคำสั่ง settings) — ดูจาก termux-api แทน" ;;
esac

q "IP ที่เครื่องเห็น:"
if command -v ip >/dev/null 2>&1; then
  ip -4 addr show 2>/dev/null | awk '/inet /{print "    " $2 "  (" $NF ")"}'
elif command -v ifconfig >/dev/null 2>&1; then
  ifconfig 2>/dev/null | awk '/inet /{print "    " $2}'
else
  q "    (ไม่มี ip/ifconfig — ใช้ termux-api และ python แทน)"
fi

# Android 15 บล็อก settings/ip หลายคำสั่ง — หา IP จาก termux-api ก่อน
IP=""
if command -v termux-wifi-connectioninfo >/dev/null 2>&1; then
  IP=$(termux-wifi-connectioninfo 2>/dev/null | python -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("ip", "") or "")
except Exception:
    print("")
' 2>/dev/null)
  case "$IP" in ""|0.0.0.0|127.0.0.1|169.254.*) IP="" ;; esac
fi
if [ -z "$IP" ] && command -v python >/dev/null 2>&1; then
  IP=$(python -c '
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
' 2>/dev/null)
fi
q "IP หลักที่ใช้: ${IP:-ไม่พบ}"
case "${IP:-}" in
  169.254.*) no "เป็น link-local (169.254.x) = ไม่ได้ต่อ Wi-Fi จริง" ;;
  10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ok "เป็น IP ในวง Wi-Fi ปกติ" ;;
  "") no "ไม่พบ IP" ;;
esac

q "ชื่อ Wi-Fi:"
STARTD=$(command -v termux-wifi-connectioninfo >/dev/null 2>&1 && echo yes || echo no)
if [ "$STARTD" = "yes" ]; then
  termux-wifi-connectioninfo 2>/dev/null | head -5 | sed 's/^/    /'
else
  q "    (ไม่มี termux-api — ข้าม)"
fi

# ---------------------------------------------------------------------------
hdr "3. สถานะ Wireless debugging"
ADB_WIFI=$(settings get global adb_wifi_enabled 2>/dev/null || echo "?")
q "adb_wifi_enabled = ${ADB_WIFI}   (1 = เปิด)"
case "$ADB_WIFI" in
  1) ok "Wireless debugging เปิดอยู่" ;;
  0) no "Wireless debugging ปิดอยู่" ;;
  *) q "อ่านค่าไม่ได้ (Android 15 บล็อกคำสั่ง settings) — ดูจากมือถือแทน" ;;
esac

THE_PORT=$(getprop service.adb.tcp.port 2>/dev/null || echo "")
q "service.adb.tcp.port = ${THE_PORT:-ว่าง}"

q "คีย์ adb ของเครื่องนี้:"
if [ -f "$HOME/.android/adbkey" ]; then
  ok "    มี ~/.android/adbkey"
else
  no "    ไม่มี ~/.android/adbkey (จะถูกสร้างตอน connect ครั้งแรก)"
fi

# ---------------------------------------------------------------------------
hdr "4. mDNS — พอร์ตที่เครื่องประกาศ"
TARGETS=""
if command -v python >/dev/null 2>&1 && [ -f "${SCRIPT_DIR}/find_port.py" ]; then
  TARGETS=$(timeout 20 python "${SCRIPT_DIR}/find_port.py" 2>&1 | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' || true)
  if [ -n "$TARGETS" ]; then
    printf '%s\n' "$TARGETS" | sed 's/^/    /'
  else
    no "mDNS ไม่พบพอร์ต connect"
  fi
else
  no "ไม่มี find_port.py"
fi

# ---------------------------------------------------------------------------
hdr "5. ทดสอบ TCP ว่าพอร์ตมีใครฟังจริงไหม"
probe() {
  local host="$1" port="$2"
  if command -v timeout >/dev/null 2>&1; then
    timeout 2 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null && return 0
    return 1
  fi
  (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null && return 0
  return 1
}

if [ -n "$TARGETS" ]; then
  for t in $TARGETS; do
    port="${t##*:}"
    if probe "$IP" "$port"; then ok "    ${IP}:${port} — เปิดอยู่ (LAN)"; else no "    ${IP}:${port} — ไม่มีใครฟัง"; fi
    if probe 127.0.0.1 "$port"; then ok "    127.0.0.1:${port} — เปิดอยู่ (loopback)"; else no "    127.0.0.1:${port} — ไม่มีใครฟัง"; fi
  done
else
  q "    ข้าม (ไม่มีพอร์ตหรือไม่มี IP)"
fi

# ---------------------------------------------------------------------------
hdr "6. adb connect / devices"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

if [ -n "$TARGETS" ]; then
  for t in $TARGETS; do
    port="${t##*:}"
    for host in "$IP" 127.0.0.1; do
      printf "  adb connect %s:%s\n" "$host" "$port"
      timeout 15 adb connect "${host}:${port}" 2>&1 | sed 's/^/      /'
    done
  done
fi

printf "\n  adb devices -l:\n"
adb devices -l 2>&1 | sed 's/^/      /'

# ---------------------------------------------------------------------------
hdr "7. สรุป"
PROBLEMS=0
[ "${WIFI_ON:-}" = "0" ] && { no "Wi-Fi ปิด"; PROBLEMS=$((PROBLEMS+1)); }
[ "${ADB_WIFI:-}" = "0" ] && { no "Wireless debugging ปิด"; PROBLEMS=$((PROBLEMS+1)); }
case "${IP:-}" in 169.254.*|"") no "ไม่มี IP ของ Wi-Fi"; PROBLEMS=$((PROBLEMS+1));; esac
[ -n "$TARGETS" ] || { no "mDNS ไม่ประกาศพอร์ต connect"; PROBLEMS=$((PROBLEMS+1)); }
adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device$' \
  && ok "มีอุปกรณ์ online แล้ว" \
  || { no "ยังไม่มีอุปกรณ์ online"; PROBLEMS=$((PROBLEMS+1)); }

if [ "$PROBLEMS" -eq 0 ]; then
  printf "\n  ทุกอย่างดูปกติ — ส่งผลลัพธ์ข้างบนมาให้ดูหน่อย\n"
else
  printf "\n  พบ %s จุดที่ต้องแก้ — ดูเครื่องหมาย ✗ ด้านบน\n" "$PROBLEMS"
fi

cat <<'EOF'

  ────────────────────────────────────────
  คัดลอกผลลัพธ์ทั้งหมด (ตั้งแต่ === 1. ===)
  ส่งกลับมาในแชทได้เลย
  ────────────────────────────────────────
EOF
