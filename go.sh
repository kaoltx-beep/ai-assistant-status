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

# รับ IP ได้จาก: --host=IP, อาร์กิวเมนต์ตัวแรก, หรือ env ADB_HOST
HOST_ARG="${ADB_HOST:-}"
for arg in "$@"; do
  case "$arg" in
    --host=*) HOST_ARG="${arg#*=}" ;;
    *[!0-9.]*|"") : ;;
    *.*) [ -z "$HOST_ARG" ] && HOST_ARG="$arg" ;;
  esac
done

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

online() { adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="device"' | grep -q .; }

# adb lists a transport as 'offline' while it waits for the phone to approve
# our key. That state is recoverable: the user just has to tap Allow.
offline_count() {
  adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="offline"' | grep -c . || true
}

unauthorized_count() {
  adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="unauthorized"' | grep -c . || true
}

# Wait up to $1 seconds for any transport to reach 'device'.
wait_online() {
  local deadline=$(( $(date +%s) + ${1:-20} ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    online && return 0
    sleep 1
  done
  return 1
}

# Try the currently listed transports again — adb often needs a second nudge
# after the phone has approved the key.
retry_existing_transports() {
  local serials
  serials=$(adb devices 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -E ':[0-9]+$' || true)
  [ -z "$serials" ] && return 1
  for s in $serials; do
    adb disconnect "$s" >/dev/null 2>&1 || true
  done
  sleep 1
  for s in $serials; do
    adb connect "$s" >/dev/null 2>&1 || true
  done
  wait_online 15
}

mdns_ports() {  # $1 = "" | "--pair"
  [ -f "$FINDER" ] || return 0
  timeout 20 python "$FINDER" ${1:-} 2>/dev/null \
    | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' \
    | awk -F: '{print $NF}' | sort -n -u | tr '\n' ' '
}

scan_ports() {  # $1 = exclude list ; สแกนทุก IP แล้วรวมผล
  [ -f "$FINDER" ] || return 0
  local h out all=""
  for h in ${HOST_LIST:-$IP}; do
    out=$(timeout 90 python "$FINDER" --scan-pair --ip "$h" --exclude "${1:-}" 2>/dev/null \
      | grep -E '^[0-9]+\.' | awk -F: '{print $NF}' || true)
    [ -n "$out" ] && all="$all $out"
  done
  printf '%s\n' $all | grep -E '^[0-9]+$' | sort -n -u | tr '\n' ' '
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

# รวมทุก IP ของเครื่อง (Tailscale ก่อน แล้ว Wi-Fi แล้ว loopback)
collect_hosts() {
  local list=""
  if [ -f "$FINDER" ]; then
    list=$(timeout 15 python "$FINDER" --hosts 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || true)
  fi
  if [ -z "$list" ]; then
    local f
    f=$(detect_ip || true)
    list=$(printf '%s\n127.0.0.1' "${f:-}")
  fi
  printf '%s' "$list" | awk '!seen[$0]++' | tr '\n' ' '
}

HOST_LIST=$(collect_hosts)
IP="${HOST_ARG:-$(printf '%s\n' $HOST_LIST | head -1)}"

if [ -z "$IP" ]; then
  printf "  หา IP อัตโนมัติไม่ได้ — พิมพ์ IP (เช่น 100.94.117.13): "
  read -r IP || true
  HOST_LIST="$IP 127.0.0.1"
fi
[ -z "$IP" ] && { bad "ไม่รู้ IP"; exit 1; }

ok "IP ที่จะใช้: ${BOLD}${IP}${OFF}"
q "จะลองทั้งหมด: $(printf '%s' "$HOST_LIST" | tr -s ' ')"
TS_IP=$(printf '%s\n' $HOST_LIST | while read -r h; do
  python -c "
import sys
p=sys.argv[1].split('.')
sys.exit(0 if len(p)==4 and p[0]=='100' and 64<=int(p[1])<=127 else 1)
" "$h" 2>/dev/null && { echo "$h"; break; }
done)
[ -n "${TS_IP:-}" ] && ok "พบ Tailscale: ${BOLD}${TS_IP}${OFF} (จะลองตัวนี้ก่อน)"

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
    for h in $HOST_LIST; do
    printf "  adb pair %s:%s ... " "$h" "$p"
    OUT=$(timeout 30 adb pair "${h}:${p}" "$CODE" 2>&1 || true)
    case "$OUT" in
      *Successfully\ paired*|*"protocol fault"*Success*)
        printf "${GREEN}✓${OFF}\n"; PAIRED=1; PAIR_PORT="$p"; break ;;
      *"Wrong password"*|*"Failed: Wrong"*)
        printf "${RED}รหัสผิด/หมดอายุ${OFF}\n"; break ;;
      *)
        printf "${DIM}%s${OFF}\n" "$(printf '%s' "$OUT" | head -1)" ;;
    esac
    [ "$PAIRED" = 1 ] && break
    done
    [ "$PAIRED" = 1 ] && break
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

# สำคัญ: พอร์ต pair ยังเปิดอยู่ตราบใดที่กล่องจับคู่ยังเปิด
# ถ้าเอาไป connect จะได้สถานะ offline ค้างตลอด (พอร์ต pair ใช้ TLS-PSK ไม่ใช่ ADB ปกติ)
printf "\n  ${BOLD}${YELLOW}ปิดกล่อง 'จับคู่กับอุปกรณ์' บนมือถือก่อน${OFF}\n"
printf "  แตะ ${BOLD}ยกเลิก${OFF} หรือกดปุ่มย้อนกลับ — ให้กล่องหายไป\n"
printf "  (พอร์ต pair จะปิดตาม แล้วเหลือแต่พอร์ต connect)\n\n"
printf "  ปิดกล่องแล้วกด Enter: "
read -r _ || true

printf "  รอ 3 วินาทีให้ adbd เปิดพอร์ต connect ... "
sleep 3
printf "done\n"
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null 2>&1 || true

# เก็บพอร์ตที่ "เปิดจริง" เท่านั้น — mDNS มักประกาศพอร์ตเก่าค้างไว้
probe_open() {  # $1 = port ; คืน 0 ถ้ามีใครฟังอยู่
  local h
  for h in $HOST_LIST; do
    if command -v timeout >/dev/null 2>&1; then
      timeout 2 bash -c "exec 3<>/dev/tcp/$h/$1" 2>/dev/null && return 0
    else
      (exec 3<>"/dev/tcp/$h/$1") 2>/dev/null && return 0
    fi
  done
  return 1
}

MDNS_LIST=$(mdns_ports)
LIVE_PORTS=""
if [ -n "$MDNS_LIST" ]; then
  for p in $MDNS_LIST; do
    [ "$p" = "${PAIR_PORT:-}" ] && continue
    probe_open "$p" && LIVE_PORTS="$LIVE_PORTS $p"
  done
  if [ -n "$LIVE_PORTS" ]; then
    q "mDNS ประกาศ: $(printf '%s\n' $MDNS_LIST | tr '\n' ' ') → ที่เปิดจริง:$(printf '%s' "$LIVE_PORTS" | tr -s ' ')"
  else
    q "mDNS ประกาศ $(printf '%s\n' $MDNS_LIST | tr '\n' ' ') แต่ไม่มีตัวไหนเปิดอยู่ (พอร์ตเก่า)"
  fi
fi

# สแกนเสมอถ้าไม่มีพอร์ตที่เปิดจริง
if [ -z "$LIVE_PORTS" ]; then
  printf "  สแกนหาพอร์ตที่เปิดอยู่ ... "
  SCANNED=$(scan_ports "${PAIR_PORT:-}")
  if [ -n "$SCANNED" ]; then
    printf "${GREEN}เจอ %s${OFF}\n" "$(printf '%s' "$SCANNED" | tr -s ' ')"
    LIVE_PORTS="$SCANNED"
  else
    printf "${YELLOW}ไม่เจอ${OFF}\n"
  fi
fi

if [ -z "$LIVE_PORTS" ]; then
  printf "  หาพอร์ต connect ไม่เจอ — พิมพ์เอง (เช่น 41087): "
  read -r MANUAL || true
  LIVE_PORTS="$MANUAL"
fi
[ -z "${LIVE_PORTS// /}" ] && { bad "ไม่ได้พอร์ต connect"; exit 1; }
q "พอร์ตที่จะลอง:$(printf '%s' "$LIVE_PORTS" | tr -s ' ')"

HOSTS="$HOST_LIST"

CONNECTED=0
for p in $LIVE_PORTS; do
  for host in $HOSTS; do
    printf "  %-24s " "${host}:${p}"
    OUT=$(timeout 20 adb connect "${host}:${p}" 2>&1 || true)
    printf "${DIM}%s${OFF}\n" "$OUT"
    if wait_online 6; then CONNECTED=1; break 2; fi
    # ถ้าค้าง offline ให้ตัดทิ้ง ไม่งั้นจะบังพอร์ตถัดไป
    if adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="offline" {print $1}' | grep -qx "${host}:${p}"; then
      adb disconnect "${host}:${p}" >/dev/null 2>&1 || true
    fi
  done
done

# --- offline = รอให้กด Allow บนมือถือ -------------------------------------
if [ "$CONNECTED" = 0 ] && [ "$(offline_count)" -gt 0 ]; then
  say "มือถือรอการอนุญาตอยู่"
  printf "  ${BOLD}${YELLOW}ดูหน้าจอมือถือเดี๋ยวนี้${OFF}\n"
  printf "  จะมีกล่อง ${BOLD}'Allow USB debugging?'${OFF} (อนุญาตการดีบัก USB?)\n"
  printf "  ติ๊ก ${BOLD}'Always allow from this computer'${OFF} แล้วกด ${BOLD}Allow${OFF}\n\n"
  printf "  กำลังดึงสถานะ (adb reconnect offline) สูงสุด 90 วินาที "
  deadline=$(( $(date +%s) + 90 ))
  round=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    # reconnect offline คือคำสั่งที่ทำให้ adb ขออนุมัติคีย์ใหม่จากมือถือ
    adb reconnect offline >/dev/null 2>&1 || true
    if online; then break; fi
    round=$((round + 1))
    if [ $((round % 3)) -eq 0 ]; then
      for s in $(adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="offline" {print $1}'); do
        adb disconnect "$s" >/dev/null 2>&1 || true
        sleep 1
        adb connect "$s" >/dev/null 2>&1 || true
      done
    fi
    printf "."
    sleep 2
  done
  printf "\n"
  if online; then
    CONNECTED=1
  else
    warn "ยังไม่เห็นการกด Allow — จะลองเชื่อมต่อใหม่ให้"
    if retry_existing_transports; then CONNECTED=1; fi
  fi
fi

# ถ้าต่อไม่ติดทั้งที่พอร์ตเปิดอยู่ ให้สแกนใหม่แล้วลองอีกครั้ง
if [ "$CONNECTED" = 0 ]; then
  warn "ต่อไม่ติดกับพอร์ตที่ลองไป — สแกนใหม่แล้วลองอีกครั้ง"
  printf "  สแกน ... "
  RESCAN=$(scan_ports "${PAIR_PORT:-}")
  NEW_PORTS=""
  for p in $RESCAN; do
    case " $LIVE_PORTS " in *" $p "*) continue ;; esac
    NEW_PORTS="$NEW_PORTS $p"
  done
  if [ -n "${NEW_PORTS// /}" ]; then
    printf "${GREEN}เจอเพิ่ม:%s${OFF}\n" "$(printf '%s' "$NEW_PORTS" | tr -s ' ')"
    for p in $NEW_PORTS; do
      for host in $HOSTS; do
        printf "  %-24s " "${host}:${p}"
        OUT=$(timeout 20 adb connect "${host}:${p}" 2>&1 || true)
        printf "${DIM}%s${OFF}\n" "$OUT"
        if wait_online 6; then CONNECTED=1; break 2; fi
      done
    done
  else
    printf "${YELLOW}ไม่เจอพอร์ตใหม่${OFF}\n"
  fi
fi

if [ "$CONNECTED" = 1 ]; then
  say "ผลลัพธ์"
  adb devices -l 2>/dev/null | sed 's/^/    /'
  ok "เชื่อมต่อสำเร็จ"
  printf "\n  เริ่มใช้งาน:\n    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

say "ผลลัพธ์"
adb devices -l 2>/dev/null | sed 's/^/    /'
bad "ยังเชื่อมไม่ได้"
cat <<EOF

  ถ้าขึ้น ${BOLD}offline${OFF} = มือถือยังไม่ได้อนุมัติคีย์
     → ดูหน้าจอมือถือ กด ${BOLD}Allow${OFF} (ติ๊ก 'Always allow from this computer' ด้วย)

  ถ้าไม่มีกล่องเด้งเลย ให้ทำ 2 ข้อนี้แล้วลองใหม่:
    1. Developer options → เปิด ${BOLD}USB debugging${OFF}
    2. Developer options → เปิด ${BOLD}'ปิดการตรวจสอบสิทธิ์'${OFF}
       (Disable permission monitoring) — ถ้าไม่เปิด ColorOS จะเพิกถอนสิทธิ์เอง

  ถ้ายังไม่หาย: ล้างคีย์แล้ว pair ใหม่
    ${BOLD}bash repair-pair.sh${OFF}

EOF

# ถ้ามี transport ค้าง offline อยู่ ให้ลองดึงต่อทันที
if [ -n "$(adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="offline" {print $1}')" ]; then
  if [ -f "${SCRIPT_DIR}/last-mile.sh" ]; then
    say "พบ transport ที่ค้าง offline — กำลังดึงให้เป็น device"
    printf "  ${BOLD}มองหน้าจอมือถือไว้${OFF} ถ้ามีกล่อง Allow ให้กด Allow\n\n"
    if bash "${SCRIPT_DIR}/last-mile.sh" </dev/null; then
      exit 0
    fi
  fi
fi

exit 1
