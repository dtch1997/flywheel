"""The loop: select → prepare → run → finalize.

``LoopEngine`` wires the seams together. ``prepare`` is side-effect-free (used by
``flywheel prompt`` for in-harness driving); ``step``/``run`` drive a full
headless iteration and reconcile the backlog with whatever the agent recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .backlog import Backlog
from .context import ContextLoader
from .guardrails import Guardrails
from .models import Idea, Status
from .prompt import DEFAULT_PROTOCOL, DEFAULT_TEMPLATE, build_prompt
from .runner import AgentRunner, RunResult


@dataclass
class StepResult:
    picked: Optional[Idea]
    prompt: str = ""
    result: Optional[RunResult] = None
    final_status: str = ""
    message: str = ""

    @property
    def did_work(self) -> bool:
        return self.picked is not None


class LoopEngine:
    def __init__(
        self,
        backlog: Backlog,
        context_loader: ContextLoader,
        guardrails: Guardrails,
        runner: AgentRunner,
        *,
        cli: str = "flywheel",
        protocol: str = DEFAULT_PROTOCOL,
        template: str = DEFAULT_TEMPLATE,
        cwd: str = ".",
    ):
        self.backlog = backlog
        self.context_loader = context_loader
        self.guardrails = guardrails
        self.runner = runner
        self.cli = cli
        self.protocol = protocol
        self.template = template
        self.cwd = cwd

    # --- side-effect-free ------------------------------------------------
    def select(self) -> Optional[Idea]:
        return self.backlog.next(predicate=self.guardrails.allows)

    def prepare(self, idea: Idea) -> str:
        context = self.context_loader.load()
        return build_prompt(
            idea=idea,
            context=context,
            protocol=self.protocol,
            template=self.template,
            cli=self.cli,
            max_strikes=self.guardrails.max_strikes,
        )

    # --- full headless iteration -----------------------------------------
    def step(self) -> StepResult:
        idea = self.select()
        if idea is None:
            return StepResult(picked=None, message="no eligible idea on the backlog")

        prompt = self.prepare(idea)
        self.backlog.update(idea.id, status=Status.RUNNING)

        result = self.runner.run(prompt, cwd=self.cwd)
        message, final = self._finalize(idea, result)
        return StepResult(
            picked=idea,
            prompt=prompt,
            result=result,
            final_status=final,
            message=message,
        )

    def run(self, max_iters: int = 1) -> list[StepResult]:
        results: list[StepResult] = []
        for _ in range(max_iters):
            r = self.step()
            results.append(r)
            if not r.did_work:
                break
        return results

    def _finalize(self, idea: Idea, result: RunResult) -> tuple[str, str]:
        """Reconcile the backlog after a headless run.

        The agent is expected to record its own outcome (status/strikes/links)
        via the CLI. We only handle the cases it couldn't: a failed launch, or a
        run that returned without recording anything.
        """
        current = self.backlog.get(idea.id)
        if current is None:  # agent removed it — respect that
            return "idea removed by agent", "removed"

        # provenance: record which session produced this run (even on failure),
        # and auto-log the reported cost so the budget stays honest.
        if result.session_id:
            self.backlog.update(idea.id, links={"session": result.session_id})
        if result.cost_usd and self.guardrails.ledger is not None:
            self.guardrails.ledger.record(
                result.cost_usd, idea_id=idea.id, note="claude -p reported cost")

        if not result.ok:
            strikes = current.strikes + 1
            if strikes >= self.guardrails.max_strikes:
                self.backlog.update(idea.id, status=Status.DROPPED, strikes=strikes)
                return (
                    f"run failed ({result.error or result.returncode}); "
                    f"{strikes} strikes → dropped",
                    "dropped",
                )
            self.backlog.update(idea.id, status=Status.PROPOSED, strikes=strikes)
            return (
                f"run failed ({result.error or result.returncode}); strike {strikes}",
                "proposed",
            )

        if current.status == Status.RUNNING:
            # success, but the agent never recorded an outcome — leave it visible
            return (
                "run finished but agent did not record an outcome (still 'running')",
                "running",
            )
        return f"agent recorded status '{current.status}'", str(current.status)
