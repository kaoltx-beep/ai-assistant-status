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
if [ "$WIFI_ON" = "1" ]; then ok "Wi-Fi เปิด"; else no "Wi-Fi ปิดอยู่ — ADB ไร้สายใช้ไม่ได้"; fi

q "IP ที่เครื่องเห็น:"
if command -v ip >/dev/null 2>&1; then
  ip -4 addr show 2>/dev/null | awk '/inet /{print "    " $2 "  (" $NF ")"} '
else
  ifconfig 2>/dev/null | awk '/inet /{print "    " $2}'
fi

IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1);exit}}')
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
if [ "$ADB_WIFI" = "1" ]; then ok "Wireless debugging เปิดอยู่"; else no "Wireless debugging ปิดอยู่"; fi

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

if [ -n "$TARGETS" ] && [ -n "$IP" ]; then
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

if [ -n "$TARGETS" ] && [ -n "$IP" ]; then
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
[ "${WIFI_ON:-}" = "1" ] || { no "Wi-Fi ปิด"; PROBLEMS=$((PROBLEMS+1)); }
[ "${ADB_WIFI:-}" = "1" ] || { no "Wireless debugging ปิด"; PROBLEMS=$((PROBLEMS+1)); }
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
