"""Configuration loaded from environment / .env file.

Deliberately dependency-free: the .env parser below is 15 lines, so this
runs on a fresh Termux install without pip installing anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(os.environ.get("ANDROID_AGENT_HOME", Path.home() / ".android_agent"))
ENV_FILE = Path(os.environ.get("ANDROID_AGENT_ENV", Path.cwd() / ".env"))

# Known free-tier providers, all OpenAI-compatible.
PROVIDERS = {
    # Google AI Studio key (free tier). Get one at https://aistudio.google.com/apikey
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
        "vision": True,
    },
    # Groq free tier. Get one at https://console.groq.com/keys
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "vision": True,
    },
    # Paid, but lets you pick any model.
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": "google/gemini-2.5-flash",
        "vision": True,
    },
}


def load_env_file(path: Path | None = None) -> None:
    """Minimal .env loader — sets os.environ for KEY=VALUE lines."""
    path = path or ENV_FILE
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        # Real environment wins over the file.
        os.environ.setdefault(key, value)


@dataclass
class Config:
    provider: str = "gemini"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    device: str = ""                     # empty = auto-detect

    max_steps: int = 25
    step_pause: float = 1.5              # seconds between actions
    image_width: int = 0                 # 0 = ส่งภาพเต็มความละเอียด; >0 = ย่อก่อนส่ง
    confirm_mode: str = "risky"          # "risky" | "all" | "none"

    telegram_token: str = ""
    telegram_chat_id: str = ""
    confirm_timeout: int = 180           # seconds to wait for a Telegram yes/no

    quiet: bool = False
    dry_run: bool = False
    auto_yes: bool = False

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        load_env_file()
        provider = (os.environ.get("AGENT_PROVIDER") or "gemini").lower()
        spec = PROVIDERS.get(provider, PROVIDERS["gemini"])

        cfg = cls(
            provider=provider,
            base_url=os.environ.get("AGENT_BASE_URL") or spec["base_url"],
            model=os.environ.get("AGENT_MODEL") or spec["model"],
            api_key=os.environ.get(spec["key_env"], ""),
            device=os.environ.get("ANDROID_DEVICE", ""),
            max_steps=int(os.environ.get("AGENT_MAX_STEPS", cls.max_steps)),
            step_pause=float(os.environ.get("AGENT_STEP_PAUSE", cls.step_pause)),
            image_width=int(os.environ.get("AGENT_IMAGE_WIDTH", cls.image_width)),
            confirm_mode=os.environ.get("AGENT_CONFIRM_MODE", cls.confirm_mode),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def describe_provider(provider: str) -> str:
    spec = PROVIDERS.get(provider)
    if not spec:
        return f"ไม่รู้จัก provider: {provider}"
    return f"{provider} / {spec['model']}"
