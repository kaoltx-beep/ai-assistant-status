"""Notifications + remote approval over Telegram, and a console fallback.

Everything here is stdlib `urllib`, so it works on a bare Termux install.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str, timeout: int = 20):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self._last_update_id = self._prime_offset() if token else 0

    # -- basics ------------------------------------------------------------
    def _call(self, method: str, payload: dict | None = None) -> dict:
        url = TELEGRAM_API.format(token=self.token, method=method)
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"Telegram {method} ตอบ {exc.code}: {detail}") from exc

    def _prime_offset(self) -> int:
        """Skip messages that were already waiting before this run started."""
        try:
            res = self._call("getUpdates", {"limit": 1, "offset": -1})
        except Exception:
            return 0
        for update in res.get("result", []):
            return int(update.get("update_id", 0)) + 1
        return 0

    def send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            return False
        try:
            self._call(
                "sendMessage",
                {"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True},
            )
            return True
        except Exception:
            return False

    def send_photo(self, png_bytes: bytes, caption: str = "") -> bool:
        """multipart upload without `requests`."""
        if not self.token or not self.chat_id:
            return False
        boundary = "----agentboundary7f3a"
        parts: list[bytes] = []
        fields = {
            "chat_id": self.chat_id,
            "caption": caption[:900],
        }
        for name, value in fields.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
            f'filename="screen.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
        )
        parts.append(png_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        url = TELEGRAM_API.format(token=self.token, method="sendPhoto")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            return True
        except Exception:
            return False

    # -- approval ----------------------------------------------------------
    def ask(self, question: str, timeout: int = 180) -> bool:
        """Send a yes/no question; return True if the user replies yes.

        Times out to False — silence never means consent.
        """
        if not self.token or not self.chat_id:
            return False
        self.send(question + "\n\nตอบ 'yes' เพื่อทำต่อ หรือ 'no' เพื่อยกเลิก")

        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(5, int(deadline - time.time()))
            try:
                res = self._call(
                    "getUpdates",
                    {"offset": self._last_update_id, "timeout": min(25, remaining)},
                )
            except Exception:
                time.sleep(2)
                continue

            for update in res.get("result", []):
                self._last_update_id = max(
                    self._last_update_id, int(update.get("update_id", 0)) + 1
                )
                message = update.get("message") or {}
                chat = str((message.get("chat") or {}).get("id", ""))
                answer = (message.get("text") or "").strip().lower()
                if chat != str(self.chat_id):
                    continue
                if answer in {"yes", "y", "ใช่", "ได้", "ok", "โอเค", "ยืนยัน"}:
                    return True
                if answer in {"no", "n", "ไม่", "ยกเลิก", "stop"}:
                    return False
            time.sleep(1)
        self.send("⏱ หมดเวลา — ยกเลิกคำสั่งนี้เพื่อความปลอดภัย")
        return False


# ---------------------------------------------------------------------------
# Console fallback
# ---------------------------------------------------------------------------

class Console:
    """Terminal output + y/n prompt. Used when Telegram is not configured."""

    COLOR = os.environ.get("NO_COLOR") is None
    C = {
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "bold": "\033[1m",
        "off": "\033[0m",
    }

    @classmethod
    def _paint(cls, text: str, color: str) -> str:
        if not cls.COLOR:
            return text
        return f"{cls.C.get(color, '')}{text}{cls.C['off']}"

    @classmethod
    def info(cls, text: str) -> None:
        print(text, flush=True)

    @classmethod
    def step(cls, n: int, text: str) -> None:
        print(cls._paint(f"\n[{n}] {text}", "blue"), flush=True)

    @classmethod
    def ok(cls, text: str) -> None:
        print(cls._paint(f"    ✓ {text}", "green"), flush=True)

    @classmethod
    def warn(cls, text: str) -> None:
        print(cls._paint(f"    ! {text}", "yellow"), flush=True)

    @classmethod
    def err(cls, text: str) -> None:
        print(cls._paint(f"    ✗ {text}", "red"), flush=True)

    @classmethod
    def dim(cls, text: str) -> None:
        print(cls._paint(f"    {text}", "dim"), flush=True)

    @classmethod
    def ask(cls, question: str, auto_yes: bool = False) -> bool:
        if auto_yes:
            cls.warn("auto-yes เปิดอยู่ — ทำต่อทันที")
            return True
        try:
            raw = input(f"\n{question}\nทำต่อไหม? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return raw in {"y", "yes", "ใช่", "ได้", "ok"}


class Notifier:
    """One entry point: prints to console and mirrors to Telegram if configured."""

    def __init__(self, telegram: Telegram | None = None, quiet: bool = False):
        self.telegram = telegram
        self.quiet = quiet

    def info(self, text: str) -> None:
        if not self.quiet:
            Console.info(text)
        if self.telegram:
            self.telegram.send(text)

    def step(self, n: int, text: str) -> None:
        if not self.quiet:
            Console.step(n, text)
        if self.telegram:
            self.telegram.send(text)

    def ok(self, text: str) -> None:
        if not self.quiet:
            Console.ok(text)

    def warn(self, text: str) -> None:
        Console.warn(text)
        if self.telegram:
            self.telegram.send(text)

    def err(self, text: str) -> None:
        Console.err(text)
        if self.telegram:
            self.telegram.send(text)

    def screenshot(self, png: bytes, caption: str) -> None:
        if self.telegram:
            self.telegram.send_photo(png, caption)

    def ask(self, question: str, timeout: int = 180, auto_yes: bool = False) -> bool:
        if self.telegram:
            Console.warn("ส่งคำขออนุญาตไปที่ Telegram...")
            return self.telegram.ask(question, timeout=timeout)
        return Console.ask(question, auto_yes=auto_yes)
