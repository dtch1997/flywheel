"""Core data model for the experiment loop.

An ``Idea`` is one entry in the hypothesis/experiment backlog. The dataclass is
deliberately storage-agnostic: it serialises to/from a plain ``dict`` so that any
``Backlog`` backend (markdown today, JSONL/SQLite tomorrow) can persist it
without the model knowing how.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(str, Enum):
    """Lifecycle of a backlog idea."""

    PROPOSED = "proposed"   # suggested, not yet started
    PICKED = "picked"       # selected for the current iteration
    RUNNING = "running"     # an experiment is in flight
    DONE = "done"           # concluded; links point at the writeup
    DROPPED = "dropped"     # abandoned (e.g. 3 strikes) — kept for the record

    def __str__(self) -> str:  # so f-strings render the value, not "Status.DONE"
        return self.value


# Statuses an idea must be in to be eligible for selection by the loop.
SELECTABLE = (Status.PROPOSED, Status.PICKED)


def _today() -> str:
    return _dt.date.today().isoformat()


def slugify(text: str, max_len: int = 48) -> str:
    """Turn free text into a stable, filename-safe id fragment."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "idea"


@dataclass
class Idea:
    """One experiment hypothesis in the backlog.

    Fields map 1:1 to what the DESIGN hypothesis-queue calls for: a hypothesis,
    an interestingness rationale, a cost tier, a status, provenance, a strike
    count, and links to the artifacts a run produces.
    """

    id: str
    hypothesis: str
    rationale: str = ""
    status: Status = Status.PROPOSED
    tier: int = 0                      # cost tier 0/1/2 (see DESIGN autonomy ladder)
    priority: int = 0                  # higher = picked sooner; hand-editable
    strikes: int = 0                   # uninformative runs on this hypothesis
    cost: str = ""                     # human estimate, e.g. "$3" / "<$10" / "$5-20"
    source: str = ""                   # where it came from (postmortem path, paper, manual)
    created: str = field(default_factory=_today)
    links: dict[str, str] = field(default_factory=dict)  # spec/postmortem/results/pr
    notes: str = ""                    # free-form

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = Status(self.status)
        if self.tier is not None:
            self.tier = int(self.tier)
        self.priority = int(self.priority)
        self.strikes = int(self.strikes)

    # --- serialisation (storage-agnostic) ---------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Idea":
        d = dict(d)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        extra = {k: v for k, v in d.items() if k not in known}
        clean = {k: v for k, v in d.items() if k in known}
        idea = cls(**clean)
        # stash unknown keys in notes-free way? keep simple: ignore but don't crash
        if extra:
            idea.links.setdefault("_extra", str(extra))
        return idea

    @classmethod
    def new(cls, hypothesis: str, **kw) -> "Idea":
        """Construct with an auto-derived id from the hypothesis."""
        idea_id = kw.pop("id", None) or slugify(hypothesis)
        return cls(id=idea_id, hypothesis=hypothesis, **kw)
