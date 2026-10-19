"""The agent loop: observe -> think -> act -> check, with a human gate for risk."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import safety
from .adb import AdbError, AndroidDevice, UiElement
from .imaging import downscale_png
from .config import APP_DIR, Config
from .llm import LlmClient, LlmError
from .notify import Notifier

SYSTEM_PROMPT = """You are an Android automation agent. You control a real phone \
through ADB, one action at a time, to finish the user's goal.

You receive:
1. A screenshot (may be downscaled).
2. A list of UI elements from the Android accessibility tree with REAL device
   pixel coordinates, e.g. "Settings" @(540,312) tappable
3. The current foreground app and your action history.

Rules:
- Reply with ONE JSON object and nothing else.
- Prefer tapping elements from the accessibility list; those coordinates are exact.
- If the list is empty or useless (Flutter/React Native/overlay), estimate
  coordinates from the screenshot. Remember the screenshot may be scaled: the
  prompt tells you the real screen size, answer in REAL device pixels.
- Never repeat the same tap more than twice. If nothing changed, try a different
  approach (scroll, back, another element).
- Use press_key "back" to dismiss dialogs, "home" to leave an app.
- When the goal is achieved, set "done": true and write what you did in "summary".
- If the goal is impossible from here, set "failed": true with a short reason.
- Do not ask questions in JSON. If information is genuinely missing, fail with a
  reason; the human will be asked.
- Thai text cannot be typed with plain adb. Use the type_text tool anyway; the
  executor routes Thai through the ADBKeyboard IME.

JSON schema:
{
  "thought": "one short sentence about what you see and why",
  "action": {"tool": "tap|long_press|swipe|type_text|press_key|launch|wait|scroll"},
  "args": {...},
  "done": false,
  "failed": false,
  "summary": ""
}

Tool arguments:
  tap            {"x": int, "y": int}
  long_press     {"x": int, "y": int, "duration_ms": int}
  swipe          {"x1": int, "y1": int, "x2": int, "y2": int, "duration_ms": int}
  scroll         {"direction": "up|down|left|right", "amount": "small|medium|large"}
  type_text      {"text": "...", "press_enter": true|false}
  press_key      {"key": "back|home|enter|recent|delete|tab"}
  launch         {"package": "com.example.app"}
  wait           {"seconds": float}
"""

PLANNER_PROMPT = """You break an Android task into 2-5 concrete, verifiable steps.
Reply with JSON only: {"steps": ["...", "..."]}
Each step must be something visible on screen (e.g. "open the search bar",
"type the query", "tap the first result"). No explanations."""


@dataclass
class Step:
    n: int
    thought: str
    action: dict
    ok: bool
    detail: str = ""


@dataclass
class RunResult:
    goal: str
    success: bool
    steps: list[Step] = field(default_factory=list)
    summary: str = ""
    failure: str = ""
    elapsed: float = 0.0

    def to_json(self) -> dict:
        return {
            "goal": self.goal,
            "success": self.success,
            "summary": self.summary,
            "failure": self.failure,
            "steps_taken": len(self.steps),
            "elapsed_seconds": round(self.elapsed, 1),
            "actions": [
                {"n": s.n, "thought": s.thought, "action": s.action, "ok": s.ok}
                for s in self.steps
            ],
        }


# ---------------------------------------------------------------------------


def acquire_lock(goal: str) -> Path:
    """Only one agent may drive the screen at a time."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lock = APP_DIR / "agent.lock"
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
            pid = int(info.get("pid", 0))
            os.kill(pid, 0)
            raise RuntimeError(
                f"มีเอเจนต์รันอยู่แล้ว (pid {pid}) — รอให้เสร็จก่อน "
                f"หรือลบไฟล์ {lock} ถ้าแน่ใจว่าค้าง"
            )
        except (ProcessLookupError, ValueError, json.JSONDecodeError, OSError):
            lock.unlink(missing_ok=True)
    lock.write_text(
        json.dumps(
            {"pid": os.getpid(), "goal": goal, "started_at": time.time()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return lock


def release_lock(lock: Path) -> None:
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


class AndroidAgent:
    def __init__(self, config: Config, notifier: Notifier, device: AndroidDevice | None = None):
        self.config = config
        self.notify = notifier
        self.device = device
        self.llm = LlmClient(config)

    # -- public ------------------------------------------------------------
    def run(self, goal: str) -> RunResult:
        started = time.time()
        result = RunResult(goal=goal, success=False)
        lock = acquire_lock(goal)
        try:
            self._execute(goal, result)
        except KeyboardInterrupt:
            result.failure = "ผู้ใช้สั่งหยุด (Ctrl-C)"
        except (AdbError, LlmError, RuntimeError) as exc:
            result.failure = str(exc)
        finally:
            release_lock(lock)
            result.elapsed = time.time() - started
        return result

    # -- internals ---------------------------------------------------------
    def _execute(self, goal: str, result: RunResult) -> None:
        if self.device is None:
            self.device = AndroidDevice(self.config.device)

        heads_up = safety.goal_heads_up(goal)
        if heads_up.risky and self.config.confirm_mode != "none":
            self.notify.warn(f"⚠️  เป้าหมายนี้อาจมีการเงิน/ลบข้อมูล: {heads_up.reason}")
            if not self.notify.ask(
                "ยืนยันจะให้เอเจนต์ทำภารกิจนี้หรือไม่?",
                timeout=self.config.confirm_timeout,
                auto_yes=self.config.auto_yes,
            ):
                result.failure = "ผู้ใช้ไม่อนุมัติภารกิจที่มีความเสี่ยง"
                return

        plan = self._plan(goal)
        if plan:
            self.notify.info("แผนที่วางไว้:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan)))

        screen_w, screen_h = self.device.screen_size()
        self.notify.info(f"📱 {self.device.serial}  ({screen_w}x{screen_h})")
        self.notify.info(f"🤖 {self.config.provider}/{self.config.model}")

        recent_taps: list[tuple[int, int]] = []

        for step_no in range(1, self.config.max_steps + 1):
            observation = self._observe()
            if observation is None:
                result.failure = "อ่านหน้าจอไม่ได้"
                return

            png, scale, elements, app = observation
            prompt = self._build_prompt(goal, plan, result.steps, elements, app,
                                         screen_w, screen_h, png, scale)

            try:
                decision = self.llm.complete_json(SYSTEM_PROMPT, prompt, image_png=png)
            except LlmError as exc:
                result.failure = f"AI ตอบผิดพลาด: {exc}"
                return

            thought = str(decision.get("thought", "")).strip()
            action = decision.get("action") or {}
            args = decision.get("args") or {}

            if decision.get("done"):
                result.success = True
                result.summary = str(decision.get("summary") or "สำเร็จ")
                self.notify.info(f"\n✅ เสร็จแล้ว: {result.summary}")
                return
            if decision.get("failed"):
                result.failure = str(decision.get("summary") or "เอเจนต์บอกว่าทำไม่ได้")
                self.notify.err(f"\n❌ {result.failure}")
                return

            tool = str(action.get("tool", "")).strip().lower()
            if not tool:
                result.failure = "โมเดลไม่ได้ระบุ action"
                return

            self.notify.step(step_no, f"{thought}" if thought else tool)
            self.notify.ok(_human_action(tool, args))

            guard = self._guard(tool, args, elements)
            if guard and not self._confirm(guard, tool, args):
                result.failure = f"ผู้ใช้ปฏิเสธการกระทำ: {tool}"
                step = Step(step_no, thought, {"tool": tool, **args}, False, "ถูกปฏิเสธ")
                result.steps.append(step)
                return

            if tool == "tap":
                point = (int(args.get("x", 0)), int(args.get("y", 0)))
                if self._is_stuck(point, recent_taps):
                    result.failure = (
                        f"ติดลูป: กดจุดเดิม {point} ซ้ำหลายครั้ง — หยุดเพื่อไม่ให้เปลืองโควตา"
                    )
                    self.notify.err(result.failure)
                    return
                recent_taps.append(point)
                recent_taps = recent_taps[-4:]

            ok, detail = self._act(tool, args)
            result.steps.append(Step(step_no, thought, {"tool": tool, **args}, ok, detail))
            if not ok:
                self.notify.warn(detail)

            if self.config.dry_run:
                result.failure = "dry-run: หยุดหลังดูแผนครั้งแรก"
                return

            time.sleep(max(0.0, self.config.step_pause))

        result.failure = f"ใช้ครบ {self.config.max_steps} ก้าวแล้วยังไม่เสร็จ"

    # -- pieces ------------------------------------------------------------
    def _observe(self) -> tuple[bytes, float, list[UiElement], str] | None:
        try:
            png = self.device.screenshot()
            elements = self.device.ui_dump()
            app = self.device.current_app()
        except AdbError as exc:
            self.notify.err(f"ADB: {exc}")
            return None
        png, scale = downscale_png(png, self.config.image_width)
        return png, scale, elements, app

    def _build_prompt(
        self,
        goal: str,
        plan: list[str],
        history: list[Step],
        elements: list[UiElement],
        app: str,
        screen_w: int,
        screen_h: int,
        png: bytes,
        scale: float = 1.0,
    ) -> str:
        lines = [f"GOAL: {goal}"]
        if plan:
            lines.append("PLAN: " + " -> ".join(plan))
        lines.append(f"FOREGROUND APP: {app or 'unknown'}")
        lines.append(f"SCREEN SIZE (real pixels): {screen_w}x{screen_h}")
        if scale < 1.0:
            lines.append(
                f"SCREENSHOT: {len(png)} bytes, downscaled to {scale:.0%} of real size. "
                "Element coordinates below are already REAL pixels — use them as-is. "
                "If you estimate from the image, divide by "
                f"{scale:.3f} to convert back to real pixels."
            )
        else:
            lines.append(f"SCREENSHOT: {len(png)} bytes, full resolution")

        if history:
            tail = history[-6:]
            lines.append("RECENT ACTIONS:")
            for s in tail:
                status = "ok" if s.ok else "failed"
                lines.append(f"  {s.n}. {s.action.get('tool')} {s.action.get('args', '')} [{status}]")

        if elements:
            lines.append(f"UI ELEMENTS ({len(elements)}):")
            for idx, el in enumerate(elements[:70]):
                lines.append("  " + el.describe(index=idx))
        else:
            lines.append(
                "UI ELEMENTS: none available (accessibility tree empty). "
                "Use vision only and estimate coordinates from the screenshot."
            )
        lines.append("\nDecide the single next action. JSON only.")
        return "\n".join(lines)

    def _plan(self, goal: str) -> list[str]:
        try:
            data = self.llm.complete_json(
                PLANNER_PROMPT,
                f"Goal: {goal}\nBreak it into 2-5 on-screen steps.",
                image_png=None,
            )
        except LlmError:
            return []
        steps = data.get("steps") or []
        if not isinstance(steps, list):
            return []
        return [str(s) for s in steps][:5]

    def _guard(
        self, tool: str, args: dict, elements: list[UiElement] | None = None
    ) -> safety.RiskAssessment | None:
        """Is this individual action dangerous?"""
        if tool == "type_text":
            text = str(args.get("text", ""))
            hit = safety.assess(text)
            if hit:
                return hit
        if tool == "tap":
            label = _label_under(args, elements or [])
            if label:
                hit = safety.assess(label)
                if hit:
                    return hit
        if tool == "launch":
            package = str(args.get("package", "")).lower()
            if any(k in package for k in ("bank", "wallet", "pay")):
                return safety.RiskAssessment(True, reason=f"เปิดแอปการเงิน ({package})")
        return None

    def _confirm(self, guard: safety.RiskAssessment, tool: str, args: dict) -> bool:
        if not safety.should_ask(self.config.confirm_mode, guard):
            return True
        self.notify.warn(f"\n🛑 {guard.reason}")
        self.notify.warn(f"   จะทำ: {_human_action(tool, args)}")
        return self.notify.ask(
            "ยืนยันให้ทำขั้นตอนนี้ไหม?",
            timeout=self.config.confirm_timeout,
            auto_yes=self.config.auto_yes,
        )

    @staticmethod
    def _is_stuck(point: tuple[int, int], recent: list[tuple[int, int]]) -> bool:
        if len(recent) < 3:
            return False
        x, y = point
        near = [p for p in recent[-3:] if abs(p[0] - x) < 60 and abs(p[1] - y) < 60]
        return len(near) >= 3

    def _act(self, tool: str, args: dict) -> tuple[bool, str]:
        device = self.device
        assert device is not None
        try:
            if tool == "tap":
                device.tap(int(args["x"]), int(args["y"]))
                return True, f"tap ({args['x']},{args['y']})"
            if tool == "long_press":
                device.long_press(int(args["x"]), int(args["y"]),
                                  int(args.get("duration_ms", 900)))
                return True, "long press"
            if tool == "swipe":
                device.swipe(int(args["x1"]), int(args["y1"]),
                             int(args["x2"]), int(args["y2"]),
                             int(args.get("duration_ms", 300)))
                return True, "swipe"
            if tool == "scroll":
                return self._scroll(str(args.get("direction", "down")),
                                    str(args.get("amount", "medium")))
            if tool == "type_text":
                used = device.type_text(str(args.get("text", "")),
                                        bool(args.get("press_enter", False)))
                return True, f"typed via {used}"
            if tool == "press_key":
                device.key(str(args.get("key", "back")))
                return True, f"key {args.get('key')}"
            if tool == "launch":
                package = str(args.get("package", "")).strip()
                if not package:
                    return False, "ไม่มีชื่อ package"
                device.shell("monkey", "-p", package,
                             "-c", "android.intent.category.LAUNCHER", "1")
                return True, f"launch {package}"
            if tool == "wait":
                seconds = min(float(args.get("seconds", 2)), 8.0)
                time.sleep(max(0.5, seconds))
                return True, f"wait {seconds}s"
            return False, f"ไม่รู้จัก tool: {tool}"
        except (AdbError, KeyError, ValueError) as exc:
            return False, f"{tool} ล้มเหลว: {exc}"

    def _scroll(self, direction: str, amount: str) -> tuple[bool, str]:
        assert self.device is not None
        w, h = self.device.screen_size()
        fractions = {"small": 0.2, "medium": 0.4, "large": 0.65}
        frac = fractions.get(amount, 0.4)
        cx, cy = w // 2, h // 2
        dx, dy = int(w * frac), int(h * frac)
        vectors = {
            "down": (cx, cy + dy // 2, cx, cy - dy // 2),
            "up": (cx, cy - dy // 2, cx, cy + dy // 2),
            "left": (cx + dx // 2, cy, cx - dx // 2, cy),
            "right": (cx - dx // 2, cy, cx + dx // 2, cy),
        }
        if direction not in vectors:
            return False, f"ทิศทางไม่ถูกต้อง: {direction}"
        self.device.swipe(*vectors[direction], duration_ms=350)
        return True, f"scroll {direction}"


def _label_under(args: dict, elements: list[UiElement]) -> str:
    """Which visible element sits under this tap? Used for risk checks."""
    try:
        x, y = int(args.get("x", -1)), int(args.get("y", -1))
    except (TypeError, ValueError):
        return ""
    for el in elements:
        left, top, right, bottom = el.bounds
        if left <= x <= right and top <= y <= bottom:
            return el.label()
    return ""


def _human_action(tool: str, args: dict) -> str:
    if tool == "tap":
        return f"แตะที่ ({args.get('x')}, {args.get('y')})"
    if tool == "type_text":
        return f'พิมพ์ "{args.get("text")}"'
    if tool == "press_key":
        return f"กดปุ่ม {args.get('key')}"
    if tool == "scroll":
        return f"เลื่อน {args.get('direction')}"
    if tool == "launch":
        return f"เปิดแอป {args.get('package')}"
    if tool == "wait":
        return f"รอ {args.get('seconds')} วินาที"
    return json.dumps({"tool": tool, **args}, ensure_ascii=False)
