import json

from flywheel.backlog import MarkdownBacklog
from flywheel.models import Idea, Status
from flywheel.triage import apply_triage, build_triage_prompt, parse_rankings


def _backlog(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea.new("cheap new probe", id="a", priority=1))
    bl.add(Idea.new("validate a surprising result", id="b", priority=1))
    bl.add(Idea.new("stale idea", id="c", priority=9))
    bl.add(Idea.new("already answered", id="d", status="done", notes="found X"))
    return bl


def test_apply_rewrites_priority_and_drops(tmp_path):
    bl = _backlog(tmp_path)
    log = tmp_path / "triage.jsonl"
    summary = apply_triage(
        bl,
        rankings=[{"id": "b", "priority": 10, "reason": "replicate the surprise"},
                  {"id": "a", "priority": 4, "reason": "cheap but minor"}],
        drops=[{"id": "c", "reason": "subsumed"}],
        log_path=str(log),
    )
    assert bl.get("b").priority == 10
    assert bl.get("a").priority == 4
    assert bl.get("c").status == Status.DROPPED
    assert summary["updated"] and summary["dropped"]
    # selection now favors the validation idea
    assert bl.next().id == "b"
    # logged
    rec = json.loads(log.read_text().strip())
    assert rec["rankings"][0]["id"] == "b"


def test_apply_skips_unknown_ids(tmp_path):
    bl = _backlog(tmp_path)
    summary = apply_triage(bl, rankings=[{"id": "ghost", "priority": 5}], drops=[])
    assert "ghost" in summary["skipped"]
    assert not summary["updated"]


def test_prompt_lists_proposed_and_learned(tmp_path):
    bl = _backlog(tmp_path)
    ideas = bl.all()
    proposed = [i for i in ideas if i.status in (Status.PROPOSED, Status.PICKED)]
    done = [i for i in ideas if i.status in (Status.DONE, Status.DROPPED)]
    p = build_triage_prompt("NORTH STARS: find interesting facts", proposed, done)
    assert "validate a surprising result" in p      # a proposed idea
    assert "already answered" in p                    # the learned/done idea
    assert "find interesting facts" in p              # context injected
    assert "ONLY JSON" in p


def test_parse_rankings_extracts_json():
    text = ('I considered the backlog.\n'
            '{"rankings":[{"id":"b","priority":9,"reason":"replicate"}],"drop":[]}\n'
            'done.')
    obj = parse_rankings(text)
    assert obj["rankings"][0]["id"] == "b"


def test_parse_rankings_empty_on_garbage():
    assert parse_rankings("no json here")["rankings"] == []
