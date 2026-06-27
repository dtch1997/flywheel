"""Project configuration — ``flywheel.toml``.

A project wires the generic loop to its own conventions here: where the backlog
lives, what context to load, the guardrail thresholds, how to invoke the agent,
and (optionally) a custom protocol/prompt. Everything has a sensible default so
a bare repo works with an empty config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

try:  # py3.11+
    import tomllib as _toml

    def _load_toml(path: str) -> dict:
        with open(path, "rb") as f:
            return _toml.load(f)
except ModuleNotFoundError:  # py<3.11
    try:
        import tomli as _toml  # type: ignore

        def _load_toml(path: str) -> dict:
            with open(path, "rb") as f:
                return _toml.load(f)
    except ModuleNotFoundError:  # last resort: no TOML available
        def _load_toml(path: str) -> dict:  # pragma: no cover
            raise RuntimeError(
                "Reading flywheel.toml needs Python 3.11+ or `pip install tomli`."
            )

from .backlog import MarkdownBacklog
from .context import ContextLoader, Source
from .guardrails import Guardrails, SpendLedger

CONFIG_NAMES = ("flywheel.toml",)

DEFAULT_SOURCES = [
    {"kind": "file", "label": "north stars", "path": "NORTH_STARS.md"},
]


@dataclass
class Config:
    root: str = "."
    backlog_path: str = "queue.md"
    ledger_path: str = ".flywheel/spend.jsonl"
    triage_log_path: str = ".flywheel/triage.jsonl"
    cli: str = "flywheel"

    sources: list[dict] = field(default_factory=lambda: list(DEFAULT_SOURCES))

    # guardrails
    max_tier: int = 2
    daily_budget_usd: float = 50.0
    max_strikes: int = 3

    # runner
    runner: str = "claude"            # "claude" (headless) | "emit"
    claude_bin: str = "claude"
    claude_args: list[str] = field(default_factory=list)
    model: str = ""
    timeout: int = 0                  # seconds; 0 = no timeout

    # prompt overrides (paths relative to root; empty = built-in default)
    protocol_file: str = ""
    template_file: str = ""

    # output gate — what a finished run must leave behind (see output.py)
    require_report: bool = True
    output_validator: str = "reportly"   # "reportly" | "none"
    output_level: str = "error"          # "error" | "warn" (reportly fail threshold)
    report_link: str = "report"          # which link field holds the report path

    # --- loading ----------------------------------------------------------
    @classmethod
    def find(cls, start: str = ".") -> Optional[str]:
        """Walk up from ``start`` looking for a flywheel.toml."""
        cur = os.path.abspath(start)
        while True:
            for name in CONFIG_NAMES:
                p = os.path.join(cur, name)
                if os.path.exists(p):
                    return p
            parent = os.path.dirname(cur)
            if parent == cur:
                return None
            cur = parent

    @classmethod
    def load(cls, path_or_dir: str = ".") -> "Config":
        cfg_path = (
            path_or_dir
            if path_or_dir.endswith(".toml") and os.path.exists(path_or_dir)
            else cls.find(path_or_dir)
        )
        if not cfg_path:
            # no config file: defaults rooted at path_or_dir
            return cls(root=os.path.abspath(path_or_dir if os.path.isdir(path_or_dir) else "."))
        data = _load_toml(cfg_path)
        root = os.path.dirname(os.path.abspath(cfg_path))
        return cls._from_dict(data, root)

    @classmethod
    def _from_dict(cls, data: dict[str, Any], root: str) -> "Config":
        c = cls(root=root)
        c.backlog_path = data.get("backlog_path", c.backlog_path)
        c.ledger_path = data.get("ledger_path", c.ledger_path)
        c.triage_log_path = data.get("triage_log_path", c.triage_log_path)
        c.cli = data.get("cli", c.cli)
        if "sources" in data:
            c.sources = data["sources"]
        g = data.get("guardrails", {})
        c.max_tier = g.get("max_tier", c.max_tier)
        c.daily_budget_usd = g.get("daily_budget_usd", c.daily_budget_usd)
        c.max_strikes = g.get("max_strikes", c.max_strikes)
        r = data.get("runner", {})
        if isinstance(r, str):
            c.runner = r
        else:
            c.runner = r.get("kind", c.runner)
            c.claude_bin = r.get("bin", c.claude_bin)
            c.claude_args = r.get("args", c.claude_args)
            c.model = r.get("model", c.model)
            c.timeout = r.get("timeout", c.timeout)
        p = data.get("prompt", {})
        c.protocol_file = p.get("protocol_file", c.protocol_file)
        c.template_file = p.get("template_file", c.template_file)
        o = data.get("output", {})
        c.require_report = o.get("require_report", c.require_report)
        c.output_validator = o.get("validator", c.output_validator)
        c.output_level = o.get("level", c.output_level)
        c.report_link = o.get("report_link", c.report_link)
        return c

    # --- builders ---------------------------------------------------------
    def _abs(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    def backlog(self) -> MarkdownBacklog:
        return MarkdownBacklog(self._abs(self.backlog_path))

    def ledger(self) -> SpendLedger:
        return SpendLedger(self._abs(self.ledger_path))

    def triage_log(self) -> str:
        return self._abs(self.triage_log_path)

    def guardrails(self) -> Guardrails:
        return Guardrails(
            max_tier=self.max_tier,
            daily_budget_usd=self.daily_budget_usd,
            max_strikes=self.max_strikes,
            ledger=self.ledger(),
        )

    def context_loader(self) -> ContextLoader:
        sources = [Source(**s) for s in self.sources]
        return ContextLoader(root=self.root, sources=sources)

    def gate(self):
        from .output import make_gate
        return make_gate(
            self.output_validator,
            root=self.root,
            level=self.output_level,
            link_field=self.report_link,
            require_report=self.require_report,
        )

    def protocol_text(self) -> Optional[str]:
        if self.protocol_file:
            with open(self._abs(self.protocol_file), encoding="utf-8") as f:
                return f.read()
        return None

    def template_text(self) -> Optional[str]:
        if self.template_file:
            with open(self._abs(self.template_file), encoding="utf-8") as f:
                return f.read()
        return None
