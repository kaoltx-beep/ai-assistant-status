#!/usr/bin/env bash
# ตัวติดตั้งอัตโนมัติ — ใช้บน Termux (Android) หรือคอมก็ได้
# วิธีใช้:  bash install.sh
set -uo pipefail

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; CYAN=$'\033[36m'; OFF=$'\033[0m'
REPO_URL="https://github.com/kaoltx-beep/ai-assistant-status.git"
TARGET_DIR="${HOME}/ai-assistant-status"

say()  { printf "\n${BOLD}${CYAN}%s${OFF}\n" "$*"; }
ok()   { printf "  ${GREEN}✓${OFF} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${OFF} %s\n" "$*"; }
bad()  { printf "  ${RED}✗${OFF} %s\n" "$*"; }
ask()  { printf "%s" "$*"; }

IS_TERMUX=0
[ -d /data/data/com.termux/files/usr ] && IS_TERMUX=1

# Known Termux packaging bug: python3.1x and python3.1x-ensurepip-wheels both
# claim .../ensurepip/_bundled/pip-*.whl, so dpkg aborts with
# "trying to overwrite ... which is also in package ...".
# Force the new interpreter to take ownership, then let apt settle.
repair_termux_dpkg() {
  say "พบปัญหาแพ็กเกจชนกัน (ensurepip) — กำลังซ่อมให้"
  apt --fix-broken install -y || true
  ( cd "$HOME" && apt download python3.11 python3.13 >/dev/null 2>&1 ) || true
  if ls "$HOME"/python3.11_*.deb >/dev/null 2>&1; then
    ( cd "$HOME" && dpkg -i --force-overwrite ./python3.11_*.deb ./python3.13_*.deb ) || true
  fi
  rm -f "$HOME"/python3.11_*.deb "$HOME"/python3.13_*.deb
  apt --fix-broken install -y || true
  ok "ซ่อมเสร็จแล้ว"
}

pause() {
  printf "\n${DIM}กด Enter เพื่อไปต่อ...${OFF}"
  read -r _ || true
}

# ---------------------------------------------------------------------------
say "ขั้นที่ 1 จาก 5 — เตรียมโปรแกรมที่ต้องใช้"

if [ "$IS_TERMUX" = 1 ]; then
  ok "ตรวจพบ Termux"
  need=0
  for cmd in python adb git; do
    command -v "$cmd" >/dev/null 2>&1 || need=1
  done
  if [ "$need" = 1 ]; then
    say "กำลังติดตั้ง python / android-tools / git (3-5 นาที ไม่ต้องกดอะไร)"
    pkg update -y >/dev/null 2>&1 || true
    if ! pkg install -y python android-tools git; then
      warn "ติดตั้งรอบแรกไม่สำเร็จ — ลองซ่อมแพ็กเกจแล้วติดตั้งซ้ำ"
      repair_termux_dpkg
      if ! pkg install -y python android-tools git; then
        bad "ติดตั้งไม่สำเร็จ — ลองรันเอง: pkg install -y python android-tools git"
        exit 1
      fi
    fi
  fi
else
  ok "ไม่ได้รันบน Termux — จะใช้ python/adb/git ที่มีอยู่ในเครื่อง"
fi

for cmd in python3 python; do
  command -v "$cmd" >/dev/null 2>&1 && { PY=$cmd; break; }
done
[ -z "${PY:-}" ] && { bad "ไม่พบ python"; exit 1; }
ok "python: $($PY --version 2>&1)"

if command -v adb >/dev/null 2>&1; then
  ok "adb: $(adb version 2>/dev/null | head -1)"
else
  bad "ไม่พบ adb — ต้องติดตั้งก่อน (Termux: pkg install android-tools)"
fi

# ---------------------------------------------------------------------------
say "ขั้นที่ 2 จาก 5 — ดาวน์โหลดโค้ด"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
if [ -f "${SCRIPT_DIR}/android_agent/agent.py" ]; then
  TARGET_DIR="$SCRIPT_DIR"
  ok "ใช้โค้ดที่มีอยู่แล้ว: $TARGET_DIR"
elif command -v git >/dev/null 2>&1; then
  if [ -d "${TARGET_DIR}/.git" ]; then
    ok "มีโค้ดอยู่แล้ว: $TARGET_DIR"
    git -C "$TARGET_DIR" pull --ff-only >/dev/null 2>&1 || warn "อัปเดตโค้ดไม่ได้ (ใช้ของเดิม)"
  else
    printf "  กำลังดาวน์โหลด...\n"
    if ! git clone --depth 1 "$REPO_URL" "$TARGET_DIR"; then
      bad "ดาวน์โหลดไม่สำเร็จ — ตรวจเน็ตแล้วลองใหม่"
      exit 1
    fi
    ok "ดาวน์โหลดแล้ว: $TARGET_DIR"
  fi
else
  bad "ไม่พบ git"
  exit 1
fi
cd "$TARGET_DIR" || exit 1

# ---------------------------------------------------------------------------
say "ขั้นที่ 3 จาก 5 — ใส่ API key (ฟรี)"

ENV_FILE="${TARGET_DIR}/.env"
if [ -f "$ENV_FILE" ] && grep -qE '^GEMINI_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
  ok "มี API key อยู่แล้ว — ข้ามขั้นนี้"
else
  printf "  เปิดลิงก์นี้ในเบราว์เซอร์เพื่อขอคีย์ฟรี:\n"
  printf "    ${BOLD}https://aistudio.google.com/apikey${OFF}\n"
  printf "  (ล็อกอิน Google → Create API key → คัดลอกคีย์ที่ขึ้นต้นด้วย AIza)\n\n"
  printf "  วางคีย์ที่นี่แล้วกด Enter: "
  read -r KEY || true
  KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"

  if [ -z "$KEY" ]; then
    warn "ไม่ได้ใส่คีย์ — จะข้ามไปก่อน ค่อยมาใส่ทีหลังได้"
    printf "  วิธีใส่ทีหลัง: nano %s\n" "$ENV_FILE"
  else
    {
      echo "# สร้างโดย install.sh"
      echo "AGENT_PROVIDER=gemini"
      echo "GEMINI_API_KEY=${KEY}"
      echo "AGENT_CONFIRM_MODE=risky"
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE" 2>/dev/null || true
    ok "บันทึกคีย์แล้ว (ไฟล์ .env สิทธิ์ 600 อ่านได้แค่คุณ)"
  fi
fi

# ---------------------------------------------------------------------------
say "ขั้นที่ 4 จาก 5 — เชื่อมต่อมือถือ (ADB)"

if adb devices 2>/dev/null | tail -n +2 | grep -q "device$"; then
  ok "เชื่อมต่อมือถือแล้ว: $(adb devices | tail -n +2 | grep 'device$' | head -1 | cut -f1)"
else
  warn "ยังไม่พบมือถือ"
  printf "\n  บนมือถือ: Settings → System → Developer options → Wireless debugging\n"
  printf "  แตะ 'Pair device with pairing code' แล้วทำตามที่จอถาม\n\n"

  ask "  ต้องการเชื่อมต่อเลยไหม? [y/N]: "
  read -r ANS || true
  if [ "${ANS:-}" = "y" ] || [ "${ANS:-}" = "Y" ]; then
    printf "\n  ${BOLD}อ่านก่อนทำ:${OFF}\n"
    printf "   • ต้องเห็นหน้า 'Pair device with pairing code' พร้อมกันตอนพิมพ์\n"
    printf "     → ใช้ split screen (กดปุ่มRecent → กดค้างที่ Termux → Split screen)\n"
    printf "   • หน้า pair มีเลข ${BOLD}2 ชุด${OFF} ที่ต่างกัน:\n"
    printf "       หมายเลขพอร์ต 5 หลัก  (ในหัวข้อ 'Wi-Fi pairing code' เช่น 37123)\n"
    printf "       รหัส pair  6 หลัก     (บรรทัด 'Pairing code' เช่น 482913)\n"
    printf "   • ถ้าหน้าต่าง pair ปิดไป ต้องกลับไปเปิดใหม่ (รหัสจะเปลี่ยนทุกครั้ง)\n\n"

    attempt=1
    paired=0
    while [ "$attempt" -le 3 ] && [ "$paired" = 0 ]; do
      printf "  ${DIM}--- ครั้งที่ %s จาก 3 ---${OFF}\n" "$attempt"
      ask "  พอร์ต pair (เช่น 37123): "
      read -r PAIR_PORT || true
      ask "  รหัส pair 6 หลัก (เช่น 482913): "
      read -r PAIR_CODE || true

      if [ -z "${PAIR_PORT:-}" ] || [ -z "${PAIR_CODE:-}" ]; then
        warn "ต้องใส่ทั้งพอร์ตและรหัส"
      else
        set -- pair "127.0.0.1:${PAIR_PORT}" "${PAIR_CODE}"
        if out=$(adb "$@" 2>&1); then
          printf '%s\n' "$out" | sed 's/^/    /'
          paired=1
        else
          printf '%s\n' "$out" | sed 's/^/    /'
          warn "pair ไม่สำเร็จ"
          printf "    ตรวจว่า: หน้าต่าง pair ยังเปิดอยู่ / รหัสเป็น 6 หลัก / พอร์ตตรงกับหน้าจอ\n"
          printf "    ถ้ายังไม่หาย: ปิด-เปิด Wireless debugging ใหม่ แล้วขอรหัสใหม่\n"
        fi
      fi
      attempt=$((attempt + 1))
    done

    if [ "$paired" = 1 ]; then
      ok "pair สำเร็จ"
    else
      warn "pair ไม่สำเร็จครบ 3 ครั้ง — ข้ามไปก่อน แล้วทำทีหลังได้"
    fi

    ask "  พอร์ตจากหน้า 'Wireless debugging' (เช่น 5555): "
    read -r CONN_PORT || true
    if [ -n "${CONN_PORT:-}" ]; then
      adb connect "127.0.0.1:${CONN_PORT}" || true
      sleep 1
      adb devices
      if ! adb devices 2>/dev/null | tail -n +2 | grep -q "device$"; then
        printf "\n  ${YELLOW}ยังไม่เห็น device${OFF} — ลอง:\n"
        printf "    adb kill-server && adb connect 127.0.0.1:%s\n" "$CONN_PORT"
      fi
    fi
  else
    warn "ข้ามไปก่อน — เชื่อมต่อทีหลังได้ด้วยคำสั่ง: adb pair 127.0.0.1:พอร์ต"
  fi
fi

# ---------------------------------------------------------------------------
say "ขั้นที่ 5 จาก 5 — ตรวจความพร้อม"

"$PY" -m android_agent --check || true

cat <<EOF

${BOLD}${GREEN}ติดตั้งเสร็จแล้ว${OFF}

ลองงานแรก (ใช้เวลาราว 30 วินาที):

  cd ${TARGET_DIR}
  ${PY} -m android_agent "เปิด Settings ดูว่า Android version อะไร"

อยากดูก่อนว่ามันจะกดอะไร โดยยังไม่กดจริง:

  ${PY} -m android_agent "เปิด Settings" --dry-run

อ่านคู่มือเต็มได้ที่: ${TARGET_DIR}/SETUP_TH.md
EOF
