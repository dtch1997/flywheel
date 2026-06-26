"""flywheel — an autonomous experiment loop.

Pick the next experiment off a backlog, run it, write it up, brainstorm
follow-ups back onto the backlog, repeat. The library is the scaffolding around
an agent; the agent does the science.
"""

from .models import Idea, Status
from .backlog import Backlog, MarkdownBacklog, select_next
from .context import ContextLoader, Source
from .guardrails import Guardrails, SpendLedger, parse_cost
from .runner import AgentRunner, ClaudeCliRunner, EmitRunner, RunResult
from .engine import LoopEngine, StepResult
from .config import Config
from .provenance import (
    current_session_id, transcript_path, archive_transcript,
)
from .triage import build_triage_prompt, apply_triage, parse_rankings

__version__ = "0.1.0"

__all__ = [
    "Idea",
    "Status",
    "Backlog",
    "MarkdownBacklog",
    "select_next",
    "ContextLoader",
    "Source",
    "Guardrails",
    "SpendLedger",
    "parse_cost",
    "AgentRunner",
    "ClaudeCliRunner",
    "EmitRunner",
    "RunResult",
    "LoopEngine",
    "StepResult",
    "Config",
    "current_session_id",
    "transcript_path",
    "archive_transcript",
    "build_triage_prompt",
    "apply_triage",
    "parse_rankings",
    "__version__",
]
