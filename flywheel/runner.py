"""How an iteration's prompt actually gets executed by an agent.

``AgentRunner`` is the execution seam. Two backends ship:

- ``ClaudeCliRunner`` — headless: shells out to ``claude -p <prompt>``. This is
  the fully-autonomous driver (cron / ``flywheel run``).
- ``EmitRunner`` — in-harness: doesn't execute anything; returns the prompt so
  the surrounding Claude Code session (driven by ``/loop``) performs it. Used by
  ``flywheel prompt``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class RunResult:
    ok: bool
    output: str
    returncode: Optional[int] = None
    error: str = ""
    session_id: str = ""           # provenance: the agent session behind this run
    cost_usd: Optional[float] = None  # reported spend, if the runner knows it


@runtime_checkable
class AgentRunner(Protocol):
    def run(self, prompt: str, cwd: str) -> RunResult: ...


@dataclass
class EmitRunner:
    """No-op runner: hands the prompt back for an in-harness agent to perform."""

    def run(self, prompt: str, cwd: str) -> RunResult:
        return RunResult(ok=True, output=prompt)


@dataclass
class ClaudeCliRunner:
    """Run an iteration headlessly via the Claude Code CLI.

    ``extra_args`` is where a project supplies its own permission posture (e.g.
    ``--permission-mode acceptEdits`` or, for a sandboxed autonomous box,
    ``--dangerously-skip-permissions``). flywheel does not pick that for you.
    """

    bin: str = "claude"
    model: str = ""
    extra_args: tuple = ()
    timeout: Optional[int] = None  # seconds; None = no limit
    capture_session: bool = True   # request JSON output to recover session_id + cost

    def _cmd(self, prompt: str) -> list[str]:
        cmd = [self.bin, "-p", prompt]
        if self.model:
            cmd += ["--model", self.model]
        # only add --output-format if the caller hasn't set one already
        if self.capture_session and not any(
            a == "--output-format" for a in self.extra_args
        ):
            cmd += ["--output-format", "json"]
        cmd += list(self.extra_args)
        return cmd

    def _parse(self, stdout: str) -> tuple[str, str, Optional[float]]:
        """Return (text, session_id, cost) from a `--output-format json` result.
        Falls back to raw stdout if it isn't the expected JSON object."""
        import json
        try:
            obj = json.loads(stdout)
            if isinstance(obj, dict):
                return (
                    obj.get("result", stdout),
                    obj.get("session_id", "") or "",
                    obj.get("total_cost_usd"),
                )
        except (json.JSONDecodeError, ValueError):
            pass
        return stdout, "", None

    def run(self, prompt: str, cwd: str) -> RunResult:
        try:
            proc = subprocess.run(
                self._cmd(prompt),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout or None,
            )
        except FileNotFoundError:
            return RunResult(
                ok=False, output="", error=f"agent binary not found: {self.bin!r}"
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                ok=False, output="", error=f"agent timed out after {self.timeout}s"
            )
        text, session_id, cost = (
            self._parse(proc.stdout) if self.capture_session
            else (proc.stdout, "", None)
        )
        return RunResult(
            ok=proc.returncode == 0,
            output=text,
            returncode=proc.returncode,
            error=proc.stderr if proc.returncode != 0 else "",
            session_id=session_id,
            cost_usd=cost,
        )
