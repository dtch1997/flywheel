"""Safety rails for autonomous iteration.

Even "fully autonomous" needs a blast-radius bound (DESIGN.md): a per-tier gate,
a daily spend budget, and a 3-strikes-per-hypothesis rule. The loop never asks a
human, but it will refuse to pick an idea these rails forbid.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from .models import Idea


def parse_cost(cost: str, default: float = 0.0) -> float:
    """Parse a human cost estimate into an upper-bound dollar figure.

    Handles ``$3``, ``<$10``, ``$5-20``, ``~$8``, ``5`` → 3.0/10.0/20.0/8.0/5.0.
    Returns ``default`` when nothing numeric is present.
    """
    if not cost:
        return default
    nums = re.findall(r"\d+(?:\.\d+)?", cost)
    if not nums:
        return default
    return max(float(n) for n in nums)  # upper bound of any range


class SpendLedger:
    """Append-only JSONL ledger of spend, for the daily budget cap."""

    def __init__(self, path: str):
        self.path = path

    def record(self, amount: float, idea_id: str = "", note: str = "") -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        entry = {
            "date": _dt.date.today().isoformat(),
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "amount": float(amount),
            "idea": idea_id,
            "note": note,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def spent_today(self, day: Optional[str] = None) -> float:
        day = day or _dt.date.today().isoformat()
        if not os.path.exists(self.path):
            return 0.0
        total = 0.0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("date") == day:
                    total += float(e.get("amount", 0.0))
        return total


@dataclass
class Guardrails:
    """Tier / budget / strike checks applied before an idea is picked.

    Defaults mirror DESIGN.md. For "fully autonomous" the loop sets ``max_tier``
    high; the daily budget remains the real rail.
    """

    max_tier: int = 2
    daily_budget_usd: float = 50.0
    max_strikes: int = 3
    # default per-tier cost upper bound, used when an idea has no estimate
    tier_cost_default: tuple = (10.0, 200.0, 1000.0)
    ledger: Optional[SpendLedger] = None

    def projected_cost(self, idea: Idea) -> float:
        explicit = parse_cost(idea.cost, default=0.0)
        if explicit > 0:
            return explicit
        tier = max(0, min(idea.tier, len(self.tier_cost_default) - 1))
        return self.tier_cost_default[tier]

    def check(self, idea: Idea) -> tuple[bool, str]:
        """Return (allowed, reason). Reason is empty when allowed."""
        if idea.tier > self.max_tier:
            return False, f"tier {idea.tier} > max_tier {self.max_tier}"
        if idea.strikes >= self.max_strikes:
            return False, f"{idea.strikes} strikes ≥ max {self.max_strikes}"
        cost = self.projected_cost(idea)
        spent = self.ledger.spent_today() if self.ledger else 0.0
        if spent + cost > self.daily_budget_usd:
            return (
                False,
                f"would exceed daily budget: spent ${spent:.0f} + est ${cost:.0f} "
                f"> ${self.daily_budget_usd:.0f}",
            )
        return True, ""

    def allows(self, idea: Idea) -> bool:
        return self.check(idea)[0]
