#!/usr/bin/env bash
# watch-connect.sh — เฝ้าจอตัวเองแล้วต่อ ADB ทันทีที่พอร์ตใหม่โผล่
#
# ปัญหาที่มันแก้: พอร์ต wireless debugging เปลี่ยนทุกครั้งที่จอล็อก/สลับเน็ต/ปิด-เปิด
#   พอเราอ่านเลขจากจอแล้วพิมพ์ตาม พอร์ตมักตายไปแล้ว -> Connection refused
#   สคริปต์นี้สแกนเองวนไปเรื่อย ๆ พอมีพอร์ตใหม่ก็ adb connect ให้ทันทีในเสี้ยววินาที
#
# วิธีใช้:
#   1. ต่อ Wi-Fi (wireless debugging ต้องมี Wi-Fi)
#   2. รัน:  bash watch-connect.sh
#   3. บนมือถือ: ปิด Wireless debugging แล้วเปิดใหม่ (หรือล็อก/ปลดล็อกจอ)
#   4. รอไม่เกิน 3 นาที — สคริปต์จะต่อให้เอง

set -u

BOLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'
GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'

ok()  { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
bad() { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say() { printf "\n${BOLD}%s${OFF}\n" "$*"; }
q()   { printf "  ${DIM}%s${OFF}\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
FINDER="$SCRIPT_DIR/find_port.py"
ROUNDS="${ROUNDS:-40}"
START="${START:-30000}"
END="${END:-50000}"

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb — รัน: pkg install android-tools"; exit 1; }
[ -f "$FINDER" ] || { bad "ไม่พบ find_port.py (ต้องอยู่โฟลเดอร์เดียวกับสคริปต์นี้)"; exit 1; }

command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null || true

state_of() {
  adb devices 2>/dev/null | tr -d '\r' | awk -v t="$1" '$1==t {print $2}'
}

online() { adb devices 2>/dev/null | tr -d '\r' | awk '$2=="device"' | grep -q .; }

HOSTS=$(
  python "$FINDER" --hosts 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
  || printf '127.0.0.1\n'
)
HOSTS=$(printf '%s\n' $HOSTS | awk '!seen[$0]++')
[ -n "$HOSTS" ] || HOSTS="127.0.0.1"

say "เริ่มเฝ้าพอร์ต"
q "IP ที่จะสแกน: $(printf '%s ' $HOSTS)"
q "ช่วงพอร์ต: ${START}-${END}  (วนสูงสุด ${ROUNDS} รอบ)"
printf "\n  ${BOLD}${YELLOW}ทำบนมือถือตอนนี้:${OFF}\n"
printf "    1. เปิด Wi-Fi (ต้องต่อ Wi-Fi ไม่ใช่แค่ 4G/5G)\n"
printf "    2. ไปที่ Developer options → ${BOLD}Wireless debugging${OFF}\n"
printf "    3. ${BOLD}ปิดสวิตช์ แล้วเปิดใหม่${OFF} (หรือล็อกจอ-ปลดล็อก)\n"
printf "    4. กลับมาดูจอนี้ — ไม่ต้องพิมพ์อะไรอีก\n\n"

SEEN=""
ROUND=0
while [ "$ROUND" -lt "$ROUNDS" ]; do
  ROUND=$((ROUND + 1))
  printf "\r  ${DIM}รอบ %d/%d — สแกนอยู่ ...${OFF}   " "$ROUND" "$ROUNDS"

  for ip in $HOSTS; do
    PORTS=$(timeout 60 python "$FINDER" --scan-pair --ip "$ip" \
              --port-start "$START" --port-end "$END" 2>/dev/null \
            | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' \
            | awk -F: '{print $NF}' | sort -n -u || true)
    [ -n "$PORTS" ] || continue

    for p in $PORTS; do
      TARGET="$ip:$p"
      case " $SEEN " in *" $TARGET "*) continue ;; esac
      SEEN="$SEEN $TARGET"

      printf "\r%-60s\r" " "
      printf "  พบพอร์ตใหม่ %s ... " "$TARGET"
      OUT=$(timeout 20 adb connect "$TARGET" 2>&1 || true)
      printf "${DIM}%s${OFF}\n" "$(printf '%s' "$OUT" | head -1)"

      ST=""
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        ST=$(state_of "$TARGET")
        [ "$ST" = "device" ] && break
        sleep 0.4
      done

      if [ "$ST" = "device" ]; then
        printf "\n"
        ok "เชื่อมต่อสำเร็จ: ${BOLD}${TARGET}${OFF}"
        adb devices | tr -d '\r' | sed 's/^/    /'
        printf "\n  เริ่มใช้งาน:\n    ${BOLD}python -m android_agent --check${OFF}\n\n"
        command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null || true
        exit 0
      fi

      case "$ST" in
        unauthorized) printf "    ${YELLOW}รอการอนุญาตบนมือถือ — กด Allow${OFF}\n" ;;
        offline|"")   printf "    ${DIM}ไม่ใช่ adbd (หรือพอร์ตตาย) — ตัดทิ้ง${OFF}\n" ;;
        *)            printf "    ${DIM}สถานะ '%s' — ตัดทิ้ง${OFF}\n" "$ST" ;;
      esac
      adb disconnect "$TARGET" >/dev/null 2>&1 || true
    done
  done
done

printf "\r%-70s\r" " "
bad "ครบ ${ROUNDS} รอบแล้วยังไม่เจอพอร์ตของ adbd"
q "ตรวจว่า: ต่อ Wi-Fi อยู่ / Wireless debugging เปิด / จอไม่ล็อก"
q "ลองใหม่: ปิด-เปิด Wireless debugging แล้วรันสคริปต์นี้อีกครั้ง"
command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock 2>/dev/null || true
exit 1
