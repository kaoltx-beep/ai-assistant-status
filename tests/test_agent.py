import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android_agent import agent as agent_module
from android_agent.adb import UiElement
from android_agent.agent import AndroidAgent
from android_agent.config import Config
from android_agent.llm import LlmError


class FakeDevice:
    serial = "fake-device"

    def __init__(self):
        self.taps = []
        self.typed = []
        self.keys = []
        self.shell_calls = []

    def screen_size(self):
        return 1080, 2400

    def screenshot(self):
        return b"\x89PNG fake"

    def ui_dump(self):
        return [
            UiElement("Settings", "", "com.android.settings:id/title",
                      (40, 100, 400, 160), True),
            UiElement("Delete account", "", "com.android.settings:id/del",
                      (40, 600, 700, 660), True),
        ]

    def current_app(self):
        return "com.android.settings"

    def tap(self, x, y):
        self.taps.append((x, y))

    def long_press(self, x, y, duration_ms=900):
        self.taps.append((x, y, "long"))

    def swipe(self, *a, **k):
        self.shell_calls.append(("swipe", a))

    def key(self, name):
        self.keys.append(name)

    def type_text(self, text, press_enter=False):
        self.typed.append((text, press_enter))
        return "input text"

    def shell(self, *args, **kwargs):
        self.shell_calls.append(args)
        return ""


class FakeLlm:
    def __init__(self, decisions, steps=None):
        self.decisions = list(decisions)
        self.steps = steps if steps is not None else ["open settings"]
        self.calls = 0

    def complete_json(self, system, user, image_png=None):
        if image_png is None:
            return {"steps": self.steps}
        self.calls += 1
        if not self.decisions:
            raise AssertionError("model asked for more decisions than expected")
        return self.decisions.pop(0)


class StubNotifier:
    def __init__(self, answers=None):
        self.messages = []
        self.answers = list(answers or [])
        self.asked = 0

    def info(self, text):
        self.messages.append(("info", text))

    def step(self, n, text):
        self.messages.append(("step", text))

    def ok(self, text):
        self.messages.append(("ok", text))

    def warn(self, text):
        self.messages.append(("warn", text))

    def err(self, text):
        self.messages.append(("err", text))

    def screenshot(self, png, caption):
        pass

    def ask(self, question, timeout=180, auto_yes=False):
        self.asked += 1
        return self.answers.pop(0) if self.answers else False


def make_agent(decisions, answers=None, **cfg):
    config = Config(api_key="test-key", max_steps=cfg.pop("max_steps", 5),
                    step_pause=0, quiet=True, **cfg)
    notifier = StubNotifier(answers)
    agent = AndroidAgent(config, notifier, device=FakeDevice())
    agent.llm = FakeLlm(decisions)
    return agent, notifier


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(agent_module, "APP_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_done_on_first_decision(self):
        agent, notifier = make_agent(
            [{"thought": "already there", "done": True, "summary": "เปิด Settings แล้ว"}]
        )
        result = agent.run("เปิด Settings")
        self.assertTrue(result.success)
        self.assertEqual(result.summary, "เปิด Settings แล้ว")
        self.assertEqual(len(result.steps), 0)

    def test_tap_then_done(self):
        agent, _ = make_agent([
            {"thought": "tap settings", "action": {"tool": "tap"}, "args": {"x": 200, "y": 130}},
            {"thought": "finished", "done": True, "summary": "done"},
        ])
        result = agent.run("เปิด Settings")
        self.assertTrue(result.success)
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(agent.device.taps, [(200, 130)])

    def test_risky_action_denied_stops_run(self):
        agent, notifier = make_agent(
            [
                {"thought": "tap delete", "action": {"tool": "tap"}, "args": {"x": 300, "y": 630}},
                {"thought": "done", "done": True},
            ],
            answers=[False],
        )
        result = agent.run("เปิด Settings")
        self.assertFalse(result.success)
        self.assertIn("ปฏิเสธ", result.failure)
        self.assertGreaterEqual(notifier.asked, 1)
        self.assertEqual(agent.device.taps, [])

    def test_risky_action_allowed_proceeds(self):
        agent, _ = make_agent(
            [
                {"thought": "tap delete", "action": {"tool": "tap"}, "args": {"x": 300, "y": 630}},
                {"thought": "done", "done": True, "summary": "ok"},
            ],
            answers=[True],
        )
        result = agent.run("เปิด Settings")
        self.assertTrue(result.success)
        self.assertEqual(agent.device.taps, [(300, 630)])

    def test_confirm_mode_none_skips_questions(self):
        agent, notifier = make_agent(
            [
                {"thought": "tap delete", "action": {"tool": "tap"}, "args": {"x": 300, "y": 630}},
                {"thought": "done", "done": True, "summary": "ok"},
            ],
            confirm_mode="none",
        )
        result = agent.run("เปิด Settings")
        self.assertTrue(result.success)
        self.assertEqual(notifier.asked, 0)

    def test_stuck_loop_breaker(self):
        tap = {"thought": "tap", "action": {"tool": "tap"}, "args": {"x": 200, "y": 130}}
        agent, _ = make_agent([dict(tap) for _ in range(6)], max_steps=6)
        result = agent.run("เปิด Settings")
        self.assertFalse(result.success)
        self.assertIn("ติดลูป", result.failure)
        self.assertLessEqual(len(agent.device.taps), 3)

    def test_failed_decision_reports(self):
        agent, _ = make_agent([{"thought": "nope", "failed": True, "summary": "หาไม่เจอ"}])
        result = agent.run("ทำอะไรสักอย่าง")
        self.assertFalse(result.success)
        self.assertEqual(result.failure, "หาไม่เจอ")

    def test_max_steps_exhausted(self):
        tap = {"thought": "tap", "action": {"tool": "tap"}, "args": {"x": 500, "y": 900}}
        agent, _ = make_agent([dict(tap) for _ in range(4)], max_steps=2)
        result = agent.run("เปิด Settings")
        # Coordinate changes nothing; loop breaker may fire first. Either way: not success.
        self.assertFalse(result.success)

    def test_llm_error_is_reported(self):
        class BoomLlm(FakeLlm):
            def complete_json(self, system, user, image_png=None):
                if image_png is None:
                    return {"steps": []}
                raise LlmError("quota หมด")

        agent, _ = make_agent([])
        agent.llm = BoomLlm([])
        result = agent.run("เปิด Settings")
        self.assertFalse(result.success)
        self.assertIn("quota", result.failure)

    def test_result_json_is_serialisable(self):
        agent, _ = make_agent([{"thought": "done", "done": True, "summary": "ok"}])
        result = agent.run("เปิด Settings")
        payload = json.dumps(result.to_json(), ensure_ascii=False)
        self.assertIn("เปิด Settings", payload)

    def test_lock_is_released_after_run(self):
        agent, _ = make_agent([{"thought": "done", "done": True, "summary": "ok"}])
        agent.run("เปิด Settings")
        self.assertFalse((Path(self.tmp.name) / "agent.lock").exists())


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(agent_module, "APP_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stale_lock_is_replaced(self):
        lock = Path(self.tmp.name) / "agent.lock"
        lock.write_text(json.dumps({"pid": 999999, "goal": "x"}), encoding="utf-8")
        acquired = agent_module.acquire_lock("new goal")
        try:
            self.assertTrue(acquired.exists())
            self.assertIn("new goal", acquired.read_text(encoding="utf-8"))
        finally:
            agent_module.release_lock(acquired)

    def test_live_lock_blocks(self):
        lock = Path(self.tmp.name) / "agent.lock"
        lock.write_text(json.dumps({"pid": __import__("os").getpid()}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            agent_module.acquire_lock("another")
        lock.unlink()


if __name__ == "__main__":
    unittest.main()
