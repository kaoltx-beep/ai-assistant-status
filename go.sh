#!/usr/bin/env bash
# go.sh — คำสั่งเดียวจบ: pair + connect + ตรวจผล ให้เสร็จในตัว
#
# วิธีใช้:
#   1. เปิด Settings → Developer options → Wireless debugging → 'จับคู่กับอุปกรณ์ด้วยรหัส'
#      (ปล่อยกล่องค้างไว้ ใช้ split screen ถ้าได้)
#   2. พิมพ์:  bash go.sh
#   3. พิมพ์รหัส 6 หลักเมื่อถูกถาม
#
# ถ้าพลาด มันจะวนให้เองอีก 3 รอบ (สแกนใหม่ → ถามรหัส → pair)
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
q()    { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
FINDER="${SCRIPT_DIR}/find_port.py"

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — pkg install android-tools"; exit 1; }

detect_ip() {
  local out=""
  if command -v termux-wifi-connectioninfo >/dev/null 2>&1; then
    out=$(termux-wifi-connectioninfo 2>/dev/null | python -c '
import sys, json
try: print(json.load(sys.stdin).get("ip","") or "")
except Exception: print("")
' 2>/dev/null)
    case "$out" in ""|0.0.0.0|127.0.0.1|169.254.*) out="" ;; esac
  fi
  if [ -z "$out" ]; then
    out=$(python -c '
import socket
for probe in ("1.1.1.1","8.8.8.8"):
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(1)
        s.connect((probe,53)); ip=s.getsockname()[0]; s.close()
        if ip and not ip.startswith(("127.","169.254.")): print(ip); break
    except OSError: continue
' 2>/dev/null)
  fi
  [ -n "$out" ] && { printf '%s' "$out"; return 0; }
  return 1
}

online() { adb devices 2>/dev/null | tail -n +2 | grep -qE '[[:space:]]device([[:space:]]|$)'; }

mdns_ports() {  # $1 = "" | "--pair"
  [ -f "$FINDER" ] || return 0
  timeout 20 python "$FINDER" ${1:-} 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' \
    | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' '
}

scan_ports() {  # $1 = exclude list
  [ -f "$FINDER" ] || return 0
  timeout 200 python "$FINDER" --scan-pair --ip "$IP" --exclude "${1:-}" 2>/dev/null \
    | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' '
}

# ---------------------------------------------------------------------------
say "ตรวจสถานะ"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

if online; then
  ok "เชื่อมต่ออยู่แล้ว"
  adb devices | tail -n +2 | sed 's/^/    /'
  printf "\n  ใช้งานได้เลย:\n    ${BOLD}python -m android_agent --check${OFF}\n"
  exit 0
fi

IP=$(detect_ip || true)
if [ -z "$IP" ]; then
  printf "  หา IP อัตโนมัติไม่ได้ — พิมพ์ IP (เช่น 192.168.1.156): "
  read -r IP || true
fi
[ -z "$IP" ] && { bad "ไม่รู้ IP"; exit 1; }
ok "IP: ${BOLD}${IP}${OFF}"

cat <<EOF

  ${BOLD}ต่อไปนี้ต้องทำบนมือถือ:${OFF}
    1. Settings → System → Developer options → ${BOLD}Wireless debugging${OFF}
    2. แตะ ${BOLD}'จับคู่กับอุปกรณ์ด้วยรหัส'${OFF}
    3. ปล่อยกล่องนั้นค้างไว้ (${BOLD}ห้ามปิด${OFF}) — ถ้าทำได้ให้ใช้ split screen

  รหัสมีอายุสั้น สคริปต์จะสแกนก่อน แล้วถามรหัส แล้ว pair ทันที

EOF

ATTEMPT=1
MAX=3
while [ "$ATTEMPT" -le "$MAX" ]; do
  say "รอบที่ ${ATTEMPT}/${MAX}"

  printf "  เปิดกล่องจับคู่แล้วกด Enter: "
  read -r _ || true

  printf "  หาพอร์ต pair ... "
  CANDS=$(mdns_ports --pair)
  if [ -z "$CANDS" ]; then
    CANDS=$(scan_ports "$(mdns_ports)")
  fi
  if [ -z "$CANDS" ]; then
    printf "${YELLOW}ไม่เจอ${OFF}\n"
    warn "กล่องจับคู่ปิดอยู่หรือเปล่า? เปิดใหม่แล้วลองอีกรอบ"
    ATTEMPT=$((ATTEMPT + 1))
    continue
  fi
  printf "${GREEN}เจอ %s${OFF}\n" "$(printf '%s' "$CANDS" | tr -s ' ')"

  printf "  รหัส 6 หลัก: "
  read -r CODE || true
  case "$CODE" in *:*) CODE="${CODE##*:}" ;; esac
  if [ -z "$CODE" ]; then
    warn "ไม่ได้กรอกรหัส"
    ATTEMPT=$((ATTEMPT + 1))
    continue
  fi
  case "$CODE" in *[!0-9]*) bad "รหัสต้องเป็นตัวเลข"; ATTEMPT=$((ATTEMPT + 1)); continue ;; esac
  if [ "${#CODE}" -ne 6 ]; then
    bad "รหัสต้อง 6 หลัก (ได้ ${#CODE})"
    ATTEMPT=$((ATTEMPT + 1))
    continue
  fi

  PAIRED=0
  for p in $CANDS; do
    printf "  adb pair %s:%s ... " "$IP" "$p"
    OUT=$(timeout 30 adb pair "${IP}:${p}" "$CODE" 2>&1 || true)
    case "$OUT" in
      *Successfully\ paired*|*"protocol fault"*Success*)
        printf "${GREEN}✓${OFF}\n"; PAIRED=1; PAIR_PORT="$p"; break ;;
      *"Wrong password"*|*"Failed: Wrong"*)
        printf "${RED}รหัสผิด/หมดอายุ${OFF}\n"; break ;;
      *)
        printf "${DIM}%s${OFF}\n" "$(printf '%s' "$OUT" | head -1)" ;;
    esac
  done

  if [ "$PAIRED" = 1 ]; then
    ok "pair สำเร็จ"
    break
  fi

  warn "รอบนี้ไม่สำเร็จ — เปิดกล่องจับคู่ใหม่ (เอารหัสใหม่)"
  ATTEMPT=$((ATTEMPT + 1))
done

if [ "${PAIRED:-0}" != 1 ]; then
  bad "pair ไม่สำเร็จครบ ${MAX} รอบ"
  cat <<EOF

  ตรวจ 3 ข้อนี้ (สำคัญมากกับ OPPO/ColorOS):

    1. Developer options → เปิด ${BOLD}USB debugging${OFF} ด้วย
    2. Developer options → เปิด ${BOLD}'ปิดการตรวจสอบสิทธิ์'${OFF}
       (Disable permission monitoring) — ถ้าไม่เปิด ระบบจะเพิกถอนสิทธิ์ ADB
    3. Settings → Display → Screen timeout → ${BOLD}10 นาที${OFF}

  แล้วรัน ${BOLD}bash go.sh${OFF} อีกครั้ง

EOF
  exit 1
fi

# ---------------------------------------------------------------------------
say "เชื่อมต่อ"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

PORTS=$(mdns_ports)
[ -z "$PORTS" ] && PORTS=$(scan_ports "${PAIR_PORT:-}")
if [ -n "${PAIR_PORT:-}" ]; then
  PORTS=$(printf '%s\n' $PORTS | grep -vx "$PAIR_PORT" | tr '\n' ' ')
fi

if [ -z "${PORTS:-}" ]; then
  printf "  หาพอร์ต connect ไม่เจอ — พิมพ์เอง (เช่น 41087): "
  read -r PORTS || true
fi
q "พอร์ตที่จะลอง: $(printf '%s' "${PORTS:-}" | tr -s ' ')"

HOSTS="$IP 127.0.0.1"
[ "$IP" = "127.0.0.1" ] && HOSTS="127.0.0.1"
for p in ${PORTS:-}; do
  for host in $HOSTS; do
    printf "  %-24s " "${host}:${p}"
    OUT=$(timeout 20 adb connect "${host}:${p}" 2>&1 || true)
    printf "${DIM}%s${OFF}\n" "$OUT"
    if online; then
      say "ผลลัพธ์"
      adb devices -l 2>/dev/null | sed 's/^/    /'
      ok "เชื่อมต่อสำเร็จ"
      printf "\n  เริ่มใช้งาน:\n    ${BOLD}python -m android_agent --check${OFF}\n"
      printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
      exit 0
    fi
  done
done

say "ผลลัพธ์"
adb devices -l 2>/dev/null | sed 's/^/    /'
bad "ยังเชื่อมไม่ได้"
cat <<EOF

  ทำ 2 อย่างแล้วลอง ${BOLD}bash go.sh${OFF} อีกครั้ง:
    1. ปิด-เปิด Wireless debugging
    2. ตอนสคริปต์ connect ให้${BOLD}มองหน้าจอมือถือ${OFF} — ถ้าเด้ง
       'Allow USB debugging?' ให้กด ${BOLD}Allow${OFF}

EOF
exit 1
