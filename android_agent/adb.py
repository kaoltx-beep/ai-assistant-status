"""Thin ADB wrapper — everything that touches the phone goes through here."""

from __future__ import annotations

import base64
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

ADB_TIMEOUT = 30


class AdbError(RuntimeError):
    """Raised when an adb command fails or no device is connected."""


def _run(args: list[str], *, binary: bool = False, timeout: int = ADB_TIMEOUT):
    try:
        proc = subprocess.run(
            ["adb", *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise AdbError(
            "ไม่พบคำสั่ง adb — ติดตั้งก่อนด้วย: pkg install android-tools"
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise AdbError(f"adb ค้างเกิน {timeout}s: adb {' '.join(args)}") from exc

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise AdbError(f"adb ล้มเหลว ({proc.returncode}): {err or 'no stderr'}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def list_devices() -> list[tuple[str, str]]:
    """Return [(serial, state)] for connected devices."""
    out = _run(["devices"])
    devices: list[tuple[str, str]] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, _, state = line.partition("\t")
        devices.append((serial.strip(), state.strip()))
    return devices


def pick_device(preferred: str = "") -> str:
    devices = [d for d in list_devices() if d[1] == "device"]
    if preferred:
        for serial, _ in devices:
            if serial == preferred:
                return serial
        raise AdbError(
            f"ไม่พบอุปกรณ์ '{preferred}' (ที่ต่ออยู่: "
            f"{', '.join(s for s, _ in devices) or 'ไม่มี'})"
        )
    if not devices:
        raise AdbError(
            "ไม่พบมือถือที่เชื่อมต่อ — เปิด Wireless debugging แล้วสั่ง "
            "`adb connect localhost:<port>` ก่อน"
        )
    if len(devices) > 1:
        names = ", ".join(s for s, _ in devices)
        raise AdbError(f"เจอหลายเครื่อง ({names}) — ระบุด้วย --device")
    return devices[0][0]


class AndroidDevice:
    """High-level device operations used by the agent loop."""

    def __init__(self, serial: str = ""):
        self.serial = pick_device(serial)
        self._dump_path = "/sdcard/android_agent_dump.xml"

    # -- plumbing ---------------------------------------------------------
    def _adb(self, *args: str, binary: bool = False, timeout: int = ADB_TIMEOUT):
        return _run(["-s", self.serial, *args], binary=binary, timeout=timeout)

    def shell(self, *args: str, timeout: int = ADB_TIMEOUT) -> str:
        return self._adb("shell", *args, timeout=timeout)

    # -- observation ------------------------------------------------------
    def screen_size(self) -> tuple[int, int]:
        out = self.shell("wm", "size")
        match = re.search(r"(\d+)x(\d+)", out)
        if not match:
            raise AdbError(f"อ่านขนาดจอไม่ได้: {out.strip()}")
        return int(match.group(1)), int(match.group(2))

    def screenshot(self) -> bytes:
        """Raw PNG bytes of the current screen."""
        return self._adb("exec-out", "screencap", "-p", binary=True)

    def ui_dump(self) -> list["UiElement"]:
        """Parse the accessibility tree into a list of tappable elements.

        Returns an empty list when the tree is unusable (Flutter / React
        Native / overlay screens) — the agent then falls back to vision.
        """
        try:
            self.shell("uiautomator", "dump", self._dump_path)
            xml_text = self._adb("exec-out", "cat", self._dump_path)
        except AdbError:
            return []
        return parse_ui_xml(xml_text)

    def current_app(self) -> str:
        try:
            out = self.shell("dumpsys", "window")
        except AdbError:
            return ""
        match = re.search(r"mCurrentFocus=.*?([\w.]+)/[\w.$]+", out)
        return match.group(1) if match else ""

    # -- actions ----------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(int(x)), str(int(y)))

    def long_press(self, x: int, y: int, duration_ms: int = 900) -> None:
        self.shell("input", "swipe", str(int(x)), str(int(y)),
                   str(int(x)), str(int(y)), str(int(duration_ms)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell("input", "swipe", str(int(x1)), str(int(y1)),
                   str(int(x2)), str(int(y2)), str(int(duration_ms)))

    def key(self, name: str) -> None:
        codes = {
            "back": "KEYCODE_BACK",
            "home": "KEYCODE_HOME",
            "enter": "KEYCODE_ENTER",
            "recent": "KEYCODE_APP_SWITCH",
            "delete": "KEYCODE_DEL",
            "tab": "KEYCODE_TAB",
            "power": "KEYCODE_POWER",
        }
        if name not in codes:
            raise AdbError(f"ปุ่มที่ไม่รองรับ: {name}")
        self.shell("input", "keyevent", codes[name])

    def type_text(self, text: str, press_enter: bool = False) -> str:
        """Type text. Returns which input path was used.

        `adb shell input text` only handles ASCII. For Thai/emoji we need the
        ADBKeyboard IME (https://github.com/senzhk/ADBKeyBoard), which accepts
        base64 broadcasts.
        """
        if not text:
            return "noop"
        if _is_ascii(text):
            escaped = text.replace(" ", "%s")
            self.shell("input", "text", escaped)
            used = "input text"
        else:
            payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            try:
                self.shell(
                    "am", "broadcast", "-a", "ADB_INPUT_B64",
                    "--es", "msg", payload,
                )
            except AdbError as exc:
                raise AdbError(
                    "พิมพ์ภาษาไทยผ่าน adb ตรง ๆ ไม่ได้ — ต้องติดตั้ง ADBKeyboard "
                    "ก่อน (ดูขั้นตอนที่ 5 ใน SETUP_TH.md)"
                ) from exc
            used = "ADBKeyboard"
        if press_enter:
            self.key("enter")
        return used

    def wake(self) -> None:
        """Wake the screen without pressing Home (keeps the current app)."""
        try:
            self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        except AdbError:
            pass


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class UiElement:
    text: str
    desc: str
    resource: str
    bounds: tuple[int, int, int, int]  # left, top, right, bottom (real pixels)
    clickable: bool

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2

    def label(self) -> str:
        return self.text or self.desc or self.resource.rsplit("/", 1)[-1]

    def describe(self, scale: float = 1.0, index: int | None = None) -> str:
        cx, cy = self.center
        cx, cy = int(cx / scale), int(cy / scale)
        prefix = f"[{index}] " if index is not None else ""
        flags = " tappable" if self.clickable else ""
        return f'{prefix}"{self.label()}" @({cx},{cy}){flags}'


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_ui_xml(xml_text: str, limit: int = 80) -> list[UiElement]:
    """Turn a uiautomator dump into a deduplicated list of labelled elements."""
    if not xml_text or "<hierarchy" not in xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    seen: set[tuple[int, int, str]] = set()
    elements: list[UiElement] = []

    for node in root.iter("node"):
        label = (node.get("text") or node.get("content-desc") or "").strip()
        if not label:
            continue
        match = _BOUNDS_RE.match(node.get("bounds") or "")
        if not match:
            continue
        bounds = tuple(int(v) for v in match.groups())  # type: ignore[assignment]
        clickable = node.get("clickable") == "true"
        el = UiElement(
            text=(node.get("text") or "").strip(),
            desc=(node.get("content-desc") or "").strip(),
            resource=node.get("resource-id") or "",
            bounds=bounds,  # type: ignore[arg-type]
            clickable=clickable,
        )
        key = (*el.center, label)
        if key in seen:
            continue
        seen.add(key)
        elements.append(el)
        if len(elements) >= limit:
            break

    # Tappable things first — they are what the model actually needs.
    elements.sort(key=lambda e: (not e.clickable, e.bounds[1], e.bounds[0]))
    return elements


def collect_screen_text(elements: Iterable[UiElement]) -> str:
    return " | ".join(e.label() for e in elements)
