"""Risk classification — the guardrail that stops the agent at money.

The rule is simple and boring on purpose: if an action could cost money,
delete something, or broadcast something to other people, the agent pauses
and asks. Everything else runs free.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Thai + English triggers. Thai has no spaces, so these are substring matches.
_RISKY_TH = [
    "ชำระเงิน", "ชําระเงิน", "จ่ายเงิน", "โอนเงิน", "โอนบาท", "เติมเงิน",
    "ยืนยันการสั่งซื้อ", "ยืนยันคำสั่งซื้อ", "สั่งซื้อ", "ซื้อเลย", "กดสั่ง",
    "ลบบัญชี", "ลบข้อมูล", "ลบรายการ", "ลบทั้งหมด", "ยกเลิกการสมัคร",
    "ยกเลิกคำสั่งซื้อ", "คืนสินค้า", "ส่งเงิน", "ถอนเงิน", "รหัส OTP",
    "รหัสผ่าน", "ยืนยันตัวตน",
]

# English needs word boundaries so "pay" does not fire on "paypal-history".
_RISKY_EN = [
    r"\bpay\b", r"\bpayment\b", r"\bpay now\b", r"\bcheckout\b",
    r"\bplace (?:the )?order\b", r"\bconfirm (?:the )?order\b",
    r"\bbuy now\b", r"\bpurchase\b", r"\btransfer\b", r"\btop ?up\b",
    r"\bdelete\b", r"\bremove (?:account|all)\b", r"\bunsubscribe\b",
    r"\bwithdraw\b", r"\bsend (?:money|cash)\b", r"\botp\b",
    r"\bpassword\b", r"\b2fa\b",
]

_RISKY_EN_RE = re.compile("|".join(_RISKY_EN), re.IGNORECASE)

# Words that make the *goal itself* risky, used for a heads-up before step 1.
_GOAL_HINTS = ["จ่าย", "ซื้อ", "โอน", "ลบ", "bi", "buy", "pay", "order", "transfer", "delete"]


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").casefold()


@dataclass(frozen=True)
class RiskAssessment:
    risky: bool
    reason: str = ""
    matched: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.risky


def assess(text: str) -> RiskAssessment:
    """Classify a piece of text (what the agent will type, or a button label)."""
    if not text:
        return RiskAssessment(False)

    haystack = _normalize(text)
    hits: list[str] = []

    for term in _RISKY_TH:
        if _normalize(term) in haystack:
            hits.append(term)
    for match in _RISKY_EN_RE.finditer(haystack):
        hits.append(match.group(0))

    if not hits:
        return RiskAssessment(False)
    return RiskAssessment(
        True,
        reason=f"เจอคำที่อาจเสี่ยง: {', '.join(sorted(set(hits)))}",
        matched=tuple(sorted(set(hits))),
    )


def goal_heads_up(goal: str) -> RiskAssessment:
    """Cheap check on the user's goal so we can warn before spending steps."""
    haystack = _normalize(goal)
    for hint in _GOAL_HINTS:
        if _normalize(hint) in haystack:
            return RiskAssessment(True, reason=f"เป้าหมายอาจมีการจ่ายเงิน/ลบข้อมูล ({hint})")
    return RiskAssessment(False)


def should_ask(config_confirm_mode: str, assessment: RiskAssessment) -> bool:
    """Decide whether this action needs a human yes.

    confirm_mode:
      "all"   -> ask before every single action (very chatty, good for first runs)
      "risky" -> ask only when the action looks destructive or financial
      "none"  -> never ask (only for a throwaway test device)
    """
    mode = (config_confirm_mode or "risky").lower()
    if mode == "none":
        return False
    if mode == "all":
        return True
    return assessment.risky
