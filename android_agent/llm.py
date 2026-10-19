"""LLM client — one OpenAI-compatible interface for all providers.

Uses `urllib` instead of the `openai` SDK so a fresh Termux install needs
zero pip packages. If you prefer the SDK, nothing outside this module needs
to change.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import Config


class LlmError(RuntimeError):
    """Raised when the model call fails."""


@dataclass
class ModelReply:
    text: str
    raw: dict | None = None


class LlmClient:
    def __init__(self, config: Config, timeout: int = 90):
        if not config.api_key:
            raise LlmError(
                "ยังไม่มี API key — ใส่ GEMINI_API_KEY=... ในไฟล์ .env ก่อน"
            )
        self.config = config
        self.timeout = timeout

    # -- public ------------------------------------------------------------
    def complete(
        self,
        system: str,
        user: str,
        image_png: bytes | None = None,
        json_mode: bool = True,
        max_tokens: int = 700,
    ) -> ModelReply:
        messages = [{"role": "system", "content": system}]
        if image_png is not None:
            b64 = base64.b64encode(image_png).decode("ascii")
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user})

        payload: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = self._post(payload)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LlmError(f"รูปแบบผลลัพธ์ไม่ถูกต้อง: {data}") from exc
        return ModelReply(text=text.strip(), raw=data)

    def complete_json(self, system: str, user: str, image_png: bytes | None = None) -> dict:
        reply = self.complete(system, user, image_png=image_png, json_mode=True)
        return extract_json(reply.text)

    # -- plumbing ----------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise LlmError(f"API ตอบ {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LlmError(f"ต่อ API ไม่ได้: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmError("API ไม่ตอบภายในเวลาที่กำหนด") from exc


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LlmError(f"โมเดลตอบไม่เป็น JSON: {text[:200]}") from exc
    raise LlmError(f"โมเดลตอบไม่เป็น JSON: {text[:200]}")
