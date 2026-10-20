#!/usr/bin/env bash
# last-mile.sh — ดึงสถานะ offline ให้กลายเป็น device
#
# ใช้เมื่อ: pair สำเร็จ, connect ติด, แต่ adb devices ขึ้น "offline"
# (adb ต่อ TCP ได้แล้ว แต่คีย์ยังไม่ได้รับการอนุมัติจากมือถือ)
#
# วิธีใช้:  bash last-mile.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'

ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
q()    { printf "  ${DIM}%s${OFF}\n" "$*"; }

command -v adb >/dev/null 2>&1 || { bad "ไม่พบ adb"; exit 1; }

SERIALS_WITH_STATE() {
  adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk 'NF>=2 {print $1, $2}'
}

online() {
  adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="device"' | grep -q .
}

offline_serials() {
  adb devices 2>/dev/null | tail -n +2 | tr -d '\r' | awk '$2=="offline" {print $1}'
}

show() { adb devices -l 2>/dev/null | sed 's/^/    /'; }

# ---------------------------------------------------------------------------
say "สถานะปัจจุบัน"
adb start-server >/dev/null 2>&1 || true

if online; then
  ok "อุปกรณ์ online อยู่แล้ว"
  show
  printf "\n  ใช้งานได้เลย:  ${BOLD}python -m android_agent --check${OFF}\n"
  exit 0
fi

SERIALS=$(offline_serials)
if [ -z "$SERIALS" ]; then
  warn "ไม่พบอุปกรณ์ที่สถานะ offline"
  show
  cat <<EOF

  ถ้าไม่มีรายการเลย แปลว่ายังไม่ได้ connect — รัน:
      ${BOLD}bash go.sh${OFF}

EOF
  exit 1
fi

ok "พบอุปกรณ์ offline: $(printf '%s' "$SERIALS" | tr '\n' ' ')"

# ---------------------------------------------------------------------------
say "ปิดกล่อง Allow ให้เด้งอีกครั้ง"
cat <<EOF
  ทำบนมือถือ 1 ข้อ (เลือกอย่างใดอย่างหนึ่ง):

  ${BOLD}ทาง A — ถ้าเคยเห็นกล่อง Allow มาก่อน${OFF}
    Settings → System → Developer options → ${BOLD}'Revoke USB debugging authorizations'${OFF}
    (เพิกถอนการอนุญาตการดีบัก USB) → กด OK

  ${BOLD}ทาง B — ถ้าไม่เคยเห็นเลย${OFF}
    Settings → System → Developer options → เปิด ${BOLD}'USB debugging'${OFF}
    (ภาษาไทย: การแก้ไขข้อบกพร่อง USB)
    และเปิด ${BOLD}'Disable adb authorization timeout'${OFF}
    (ภาษาไทย: ${BOLD}ปิดใช้ระยะหมดเวลาการให้สิทธิ์ adb${OFF}) — ข้อนี้ทำให้
    สิทธิ์ไม่ถูกเพิกถอนเอง ซึ่งเป็นสาเหตุที่สถานะค้าง offline บ่อยที่สุด

  ${BOLD}สำคัญ: ปลดล็อกหน้าจอค้างไว้ + อย่าให้จอดับ${OFF}

EOF
printf "  ทำแล้วกด Enter: "
read -r _ || true

# ---------------------------------------------------------------------------
say "ดึงสถานะ (adb reconnect offline)"
printf "  รอสูงสุด 90 วินาที — ${BOLD}มองหน้าจอมือถือไว้${OFF} ถ้ามีกล่อง Allow ให้กด Allow\n"

DEADLINE=$(( $(date +%s) + 90 ))
ROUND=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  ROUND=$((ROUND + 1))

  # reconnect offline คือคำสั่งที่ทำให้ adb ขออนุมัติคีย์ใหม่
  adb reconnect offline >/dev/null 2>&1 || true
  sleep 2
  if online; then break; fi

  # ทุก ๆ 3 รอบ ลอง connect ใหม่จากรายการ serial ที่ค้างอยู่
  if [ $((ROUND % 3)) -eq 0 ]; then
    for s in $(offline_serials); do
      adb disconnect "$s" >/dev/null 2>&1 || true
      sleep 1
      adb connect "$s" >/dev/null 2>&1 || true
    done
  fi

  printf "."
  sleep 2
done
printf "\n"

# ---------------------------------------------------------------------------
say "ผลลัพธ์"
show

if online; then
  ok "สำเร็จ — อุปกรณ์ online แล้ว"
  printf "\n  ทดสอบยิงคำสั่งเข้าอุปกรณ์:\n"
  if adb shell echo ok 2>/dev/null | grep -q ok; then
    ok "adb shell ใช้งานได้"
  else
    warn "adb shell ยังไม่ตอบ — ลองรันสคริปต์นี้อีกครั้ง"
  fi
  printf "\n  เริ่มใช้งาน:\n    ${BOLD}python -m android_agent --check${OFF}\n"
  printf "    ${BOLD}python -m android_agent \"เปิด Settings ดูเลข Android version\"${OFF}\n"
  exit 0
fi

bad "ยังค้างที่ offline"
cat <<EOF

  ถ้ามองหน้าจอมือถือแล้ว ${BOLD}ไม่มีกล่อง Allow เด้งเลย${OFF} — เป็นข้อจำกัดของ ColorOS
  กับการต่อจากเครื่องตัวเอง (Termux → adbd เครื่องเดียวกัน)

  ทางออกที่ชัวร์ที่สุด (ทำครั้งเดียวจบ):

    ${BOLD}ต่อสาย USB กับคอม${OFF} → กด Allow บนมือถือ → สั่ง
        adb tcpip 5555
    แล้วปลดสาย — คีย์จะถูกอนุมัติผ่าน USB จากนั้น Termux เชื่อมต่อได้เลย

  ทางเลือกอื่น:
    • เปิด ${BOLD}'USB debugging (Security settings)'${OFF} ใน Developer options
      (OPPO บางรุ่นมีข้อนี้) แล้วรัน ${BOLD}bash last-mile.sh${OFF} อีกครั้ง
    • ใช้ MacroDroid เป็นตัวกดจอแทน ADB (ไม่ต้องพึ่ง wireless debugging)

EOF
exit 1
