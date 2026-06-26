from flywheel.backlog import MarkdownBacklog
from flywheel.context import ContextLoader, Source
from flywheel.engine import LoopEngine
from flywheel.guardrails import Guardrails
from flywheel.models import Idea, Status
from flywheel.runner import EmitRunner, RunResult


class FakeRunner:
    """Records prompts; optionally simulates the agent recording an outcome."""

    def __init__(self, ok=True, on_run=None):
        self.ok = ok
        self.on_run = on_run
        self.prompts = []

    def run(self, prompt, cwd):
        self.prompts.append(prompt)
        if self.on_run:
            self.on_run()
        return RunResult(ok=self.ok, output="done" if self.ok else "", error="boom" if not self.ok else "")


def _engine(tmp_path, runner, **gkw):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    ctx = ContextLoader(root=str(tmp_path), sources=[])
    guard = Guardrails(ledger=None, **gkw)
    return bl, LoopEngine(bl, ctx, guard, runner, cwd=str(tmp_path))


def test_prepare_includes_idea_and_context(tmp_path):
    (tmp_path / "NORTH_STARS.md").write_text("Goal: understand negation neglect.")
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    ctx = ContextLoader(
        root=str(tmp_path),
        sources=[Source(kind="file", label="north stars", path="NORTH_STARS.md")],
    )
    eng = LoopEngine(bl, ctx, Guardrails(), EmitRunner(), cwd=str(tmp_path))
    idea = Idea.new("Does CoT help?", rationale="cheap to test")
    prompt = eng.prepare(idea)
    assert "Does CoT help?" in prompt
    assert "negation neglect" in prompt
    assert "flywheel update" in prompt


def test_step_no_eligible(tmp_path):
    _, eng = _engine(tmp_path, FakeRunner())
    res = eng.step()
    assert not res.did_work
    assert "no eligible" in res.message


def test_step_marks_running_then_agent_records(tmp_path):
    runner = FakeRunner(ok=True)
    bl, eng = _engine(tmp_path, runner)
    idea = bl.add(Idea.new("hyp", cost="$1"))

    # simulate the agent updating status mid-run
    runner.on_run = lambda: bl.update(idea.id, status="done", links={"pr": "u/1"})

    res = eng.step()
    assert res.did_work
    assert res.final_status == "done"
    assert bl.get(idea.id).status == Status.DONE
    assert len(runner.prompts) == 1


def test_step_failure_adds_strike_and_reverts(tmp_path):
    runner = FakeRunner(ok=False)
    bl, eng = _engine(tmp_path, runner, max_strikes=3)
    idea = bl.add(Idea.new("hyp", cost="$1"))
    res = eng.step()
    got = bl.get(idea.id)
    assert got.strikes == 1
    assert got.status == Status.PROPOSED  # reverted for retry
    assert res.final_status == "proposed"


def test_step_failure_drops_at_max_strikes(tmp_path):
    runner = FakeRunner(ok=False)
    bl, eng = _engine(tmp_path, runner, max_strikes=2)
    idea = bl.add(Idea.new("hyp", cost="$1", strikes=1))
    res = eng.step()
    got = bl.get(idea.id)
    assert got.strikes == 2
    assert got.status == Status.DROPPED
    assert res.final_status == "dropped"


def test_step_success_but_no_record_stays_running(tmp_path):
    runner = FakeRunner(ok=True)  # agent does nothing to the backlog
    bl, eng = _engine(tmp_path, runner)
    idea = bl.add(Idea.new("hyp", cost="$1"))
    res = eng.step()
    assert bl.get(idea.id).status == Status.RUNNING
    assert res.final_status == "running"


def test_run_stops_when_empty(tmp_path):
    runner = FakeRunner(ok=True)
    bl, eng = _engine(tmp_path, runner)
    idea = bl.add(Idea.new("hyp", cost="$1"))
    runner.on_run = lambda: bl.update(idea.id, status="done")
    results = eng.run(max_iters=5)
    # one real iteration, then nothing eligible
    assert results[0].did_work
    assert not results[-1].did_work


def test_guardrail_blocks_selection(tmp_path):
    runner = FakeRunner(ok=True)
    bl, eng = _engine(tmp_path, runner, max_tier=0)
    bl.add(Idea.new("expensive", tier=2, cost="$500"))
    assert eng.select() is None
