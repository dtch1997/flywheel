import os

from flywheel import provenance
from flywheel.backlog import MarkdownBacklog
from flywheel.models import Idea
from flywheel.runner import ClaudeCliRunner


def test_current_session_id_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-123")
    assert provenance.current_session_id() == "sess-123"
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert provenance.current_session_id() is None


def test_transcript_path_and_archive(tmp_path):
    root = tmp_path / "projects" / "encoded-cwd"
    root.mkdir(parents=True)
    sid = "abc-def"
    src = root / f"{sid}.jsonl"
    src.write_text('{"type":"x"}\n')
    found = provenance.transcript_path(sid, projects_root=str(tmp_path / "projects"))
    assert found == str(src)
    dest_dir = tmp_path / "run"
    archived = provenance.archive_transcript(sid, str(dest_dir),
                                             projects_root=str(tmp_path / "projects"))
    assert archived and os.path.exists(archived)
    assert (dest_dir / f"session-{sid}.jsonl").read_text() == '{"type":"x"}\n'


def test_transcript_path_missing(tmp_path):
    assert provenance.transcript_path("nope", projects_root=str(tmp_path)) is None


def test_session_link_roundtrip(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea.new("hyp", id="x"))
    bl.update("x", links={"session": "sess-9", "transcript": "/a/b.jsonl"})
    got = bl.get("x")
    assert got.links["session"] == "sess-9"
    assert got.links["transcript"] == "/a/b.jsonl"


def test_runner_parses_session_and_cost():
    r = ClaudeCliRunner()
    text, sid, cost = r._parse(
        '{"result":"all done","session_id":"sess-7","total_cost_usd":0.42}')
    assert text == "all done" and sid == "sess-7" and cost == 0.42


def test_runner_parse_falls_back_to_raw():
    r = ClaudeCliRunner()
    text, sid, cost = r._parse("not json")
    assert text == "not json" and sid == "" and cost is None


def test_cmd_uses_json_output_when_capturing():
    r = ClaudeCliRunner(capture_session=True)
    assert "--output-format" in r._cmd("hi") and "json" in r._cmd("hi")
    r2 = ClaudeCliRunner(capture_session=False)
    assert "--output-format" not in r2._cmd("hi")


def test_engine_records_session_and_cost(tmp_path):
    from flywheel.context import ContextLoader
    from flywheel.engine import LoopEngine
    from flywheel.guardrails import Guardrails, SpendLedger
    from flywheel.runner import RunResult

    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    idea = bl.add(Idea.new("hyp", id="x", cost="$1"))
    ledger = SpendLedger(str(tmp_path / "spend.jsonl"))

    class R:
        def run(self, prompt, cwd):
            bl.update("x", status="done")          # agent records outcome
            return RunResult(ok=True, output="ok", session_id="sess-77", cost_usd=0.5)

    eng = LoopEngine(bl, ContextLoader(root=str(tmp_path)),
                     Guardrails(ledger=ledger), R(), cwd=str(tmp_path))
    eng.step()
    assert bl.get("x").links["session"] == "sess-77"
    assert ledger.spent_today() == 0.5
