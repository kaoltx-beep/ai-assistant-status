"""Command line entry point: python -m android_agent "goal" """

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import AndroidAgent
from .config import PROVIDERS, Config
from .notify import Notifier, Telegram


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-agent",
        description="สั่งมือถือ Android ด้วยภาษาคน ผ่าน ADB + AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""ตัวอย่าง:
  python -m android_agent "เปิด Settings แล้วดูเลข Android version"
  python -m android_agent "เปิด YouTube ค้นหา lo-fi music แล้วเล่นอันแรก"
  python -m android_agent --check
""",
    )
    parser.add_argument("goal", nargs="*", help="สิ่งที่อยากให้ทำ")
    parser.add_argument("--steps", type=int, default=None, help="จำนวนก้าวสูงสุด (ค่าเริ่มต้น 25)")
    parser.add_argument("--device", default=None, help="ADB serial (ไม่ระบุ = เลือกอัตโนมัติ)")
    parser.add_argument("--model", default=None, help="override ชื่อโมเดล")
    parser.add_argument("--provider", default=None, choices=sorted(PROVIDERS),
                        help="gemini | groq | openrouter")
    parser.add_argument("--confirm", default=None, choices=["all", "risky", "none"],
                        help="ระดับการถามยืนยัน (ค่าเริ่มต้น risky)")
    parser.add_argument("--yes", action="store_true", help="ตอบ yes อัตโนมัติ (ใช้ตอนทดสอบ)")
    parser.add_argument("--quiet", action="store_true", help="พิมพ์น้อยลง")
    parser.add_argument("--dry-run", action="store_true", help="ดูแผน + การตัดสินใจแรก แล้วหยุด")
    parser.add_argument("--json", action="store_true", help="พิมพ์ผลลัพธ์เป็น JSON")
    parser.add_argument("--check", action="store_true", help="ตรวจความพร้อมของระบบเท่านั้น")
    parser.add_argument("--screenshot", action="store_true", help="ถ่ายภาพหน้าจอแล้วจบ")
    return parser


def check(config: Config) -> int:
    """Health check that never raises — prints a checklist."""
    ok = True
    print("=== ตรวจความพร้อม ===")

    # adb
    try:
        from .adb import list_devices

        devices = list_devices()
    except Exception as exc:  # noqa: BLE001 - report anything
        print(f"  ✗ adb: {exc}")
        devices = []
        ok = False
    else:
        if not devices:
            print("  ✗ ไม่พบมือถือ (adb devices ว่าง)")
            ok = False
        else:
            for serial, state in devices:
                mark = "✓" if state == "device" else "✗"
                print(f"  {mark} อุปกรณ์ {serial} [{state}]")
                if state != "device":
                    ok = False

    # provider / key
    if config.api_key:
        print(f"  ✓ API key: {config.provider} ({len(config.api_key)} ตัวอักษร)")
    else:
        print(f"  ✗ ยังไม่มี API key สำหรับ provider '{config.provider}'")
        ok = False

    print(f"  ℹ โมเดล: {config.model}")
    print(f"  ℹ ระดับยืนยัน: {config.confirm_mode}")

    # telegram (optional)
    if config.has_telegram:
        print("  ℹ Telegram: ตั้งค่าแล้ว (จะส่งคำขอยืนยันไปที่แชท)")
    else:
        print("  ℹ Telegram: ไม่ได้ตั้งค่า → จะถามยืนยันใน terminal แทน")

    print("=== " + ("พร้อมใช้งาน ✅" if ok else "ยังมีจุดที่ต้องแก้ ❌") + " ===")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = Config.from_env(
            provider=args.provider,
            model=args.model,
            device=args.device,
            confirm_mode=args.confirm,
            max_steps=args.steps,
            quiet=args.quiet,
            dry_run=args.dry_run,
            auto_yes=args.yes,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ตั้งค่าไม่ได้: {exc}", file=sys.stderr)
        return 2

    if args.check:
        return check(config)

    telegram = (
        Telegram(config.telegram_token, config.telegram_chat_id)
        if config.has_telegram
        else None
    )
    notifier = Notifier(telegram=telegram, quiet=config.quiet)

    if args.screenshot:
        return _screenshot(config, notifier)

    goal = " ".join(args.goal).strip()
    if not goal:
        build_parser().print_help()
        return 2

    if not config.api_key:
        notifier.err(
            f"ยังไม่มี API key — ใส่ {PROVIDERS[config.provider]['key_env']}=... "
            "ในไฟล์ .env (ดู SETUP_TH.md)"
        )
        return 2

    try:
        agent = AndroidAgent(config, notifier)
        result = agent.run(goal)
    except KeyboardInterrupt:
        print("\nหยุดโดยผู้ใช้", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        notifier.err(f"ผิดพลาด: {exc}")
        return 1

    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_summary(result)

    _write_last_result(result)

    notifier.info(
        ("✅ สำเร็จ" if result.success else "❌ ไม่สำเร็จ")
        + f" — {len(result.steps)} ก้าว, {result.elapsed:.0f} วินาที"
    )
    return 0 if result.success else 1


def _screenshot(config: Config, notifier: Notifier) -> int:
    from .adb import AndroidDevice

    try:
        device = AndroidDevice(config.device)
        png = device.screenshot()
    except Exception as exc:  # noqa: BLE001
        notifier.err(f"ถ่ายภาพไม่สำเร็จ: {exc}")
        return 1
    target = Path.cwd() / "screenshot.png"
    target.write_bytes(png)
    notifier.info(f"บันทึกแล้ว: {target}")
    notifier.screenshot(png, "ภาพหน้าจอปัจจุบัน")
    return 0


def _print_summary(result) -> None:
    print("\n" + "=" * 50)
    print("สรุปผล")
    print("=" * 50)
    print(f"เป้าหมาย : {result.goal}")
    print(f"ผลลัพธ์  : {'สำเร็จ ✅' if result.success else 'ไม่สำเร็จ ❌'}")
    if result.summary:
        print(f"รายละเอียด: {result.summary}")
    if result.failure:
        print(f"สาเหตุ    : {result.failure}")
    print(f"จำนวนก้าว : {len(result.steps)}")
    print(f"เวลา      : {result.elapsed:.0f} วินาที")
    if result.steps:
        print("\nลำดับการทำงาน:")
        for step in result.steps[-10:]:
            mark = "✓" if step.ok else "✗"
            print(f"  {mark} {step.n}. {step.thought[:70]}")


def _write_last_result(result) -> None:
    from .config import APP_DIR

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        (APP_DIR / "last_result.json").write_text(
            json.dumps(result.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
