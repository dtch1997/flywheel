"""Critique: grade a finished report against the rubric, feed it back."""

import json

from flywheel.backlog import MarkdownBacklog
from flywheel.cli import main
from flywheel.config import Config
from flywheel.critique import (
    DEFAULT_RUBRIC, apply_critique, build_critique_prompt, parse_critique,
)
from flywheel.models import Idea, Status

VERDICT = {
    "claimed_rung": "L3",
    "earned_rung": "L1",
    "c_gap": ["C7", "C8"],
    "r_fix": ["R9"],
    "conclusion": "Only a behavioral pattern under one setting; no evidence of a mechanism.",
    "summary": "behavioral only; over-claims intent",
    "followups": [
        {"hypothesis": "add a negative control isolating instruction ambiguity",
         "rationale": "closes C7 via R9", "tier": 1, "cost": "$10", "priority": 6},
    ],
}


# --- units ---------------------------------------------------------------
def test_parse_extracts_verdict():
    text = "blah blah\n" + json.dumps(VERDICT) + "\ntrailing"
    obj = parse_critique(text)
    assert obj["earned_rung"] == "L1" and obj["c_gap"] == ["C7", "C8"]


def test_parse_missing_returns_empty():
    obj = parse_critique("no json here")
    assert obj["earned_rung"] == "" and obj["followups"] == []


def test_build_prompt_includes_rubric_and_report():
    idea = Idea.new("models scheme", id="exp")
    p = build_critique_prompt(DEFAULT_RUBRIC, "THE REPORT BODY", idea, context="CTX")
    assert "evidence ladder" in p.lower()
    assert "THE REPORT BODY" in p and "exp" in p and "CTX" in p
    assert "Return ONLY JSON" in p


# --- apply ---------------------------------------------------------------
def _backlog(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea.new("the experiment", id="exp", status="done", notes="found X"))
    return bl


def test_apply_records_verdict_without_changing_status(tmp_path):
    bl = _backlog(tmp_path)
    summary = apply_critique(bl, "exp", VERDICT,
                             critique_dir=str(tmp_path / "critiques"),
                             log_path=str(tmp_path / "critique.jsonl"))
    idea = bl.get("exp")
    # status untouched — feedback, not a gate
    assert idea.status == Status.DONE
    # artifact written + linked
    cpath = tmp_path / "critiques" / "exp.md"
    assert cpath.exists()
    assert idea.links["critique"] == summary["critique_path"]
    body = cpath.read_text()
    assert "claims L3, earns L1" in body and "C7, C8" in body
    # verdict prepended to notes, original note preserved
    assert idea.notes.startswith("critique: claims L3 / earns L1")
    assert "found X" in idea.notes
    # logged
    rec = json.loads((tmp_path / "critique.jsonl").read_text().strip())
    assert rec["id"] == "exp" and rec["verdict"]["earned_rung"] == "L1"


def test_apply_files_followups(tmp_path):
    bl = _backlog(tmp_path)
    summary = apply_critique(bl, "exp", VERDICT,
                             critique_dir=str(tmp_path / "critiques"))
    assert summary["filed"]
    child = bl.get(summary["filed"][0])
    assert child.source == "exp:critique" and child.status == Status.PROPOSED
    assert child.tier == 1 and child.priority == 6


def test_apply_can_skip_followups(tmp_path):
    bl = _backlog(tmp_path)
    summary = apply_critique(bl, "exp", VERDICT,
                             critique_dir=str(tmp_path / "critiques"),
                             file_followups=False)
    assert summary["filed"] == []
    # only the original idea remains
    assert [i.id for i in bl.all()] == ["exp"]


def test_apply_unknown_id_raises(tmp_path):
    bl = _backlog(tmp_path)
    import pytest
    with pytest.raises(KeyError):
        apply_critique(bl, "ghost", VERDICT, critique_dir=str(tmp_path / "c"))


# --- cmd integration -----------------------------------------------------
def _project(tmp_path):
    (tmp_path / "flywheel.toml").write_text(
        "backlog_path = 'queue.md'\n[output]\nvalidator='none'\n")
    cfg = Config.load(str(tmp_path))
    bl = cfg.backlog()
    (tmp_path / "report.md").write_text("# A finding\nbody")
    bl.add(Idea.new("the experiment", id="exp", status="done",
                    links={"report": "report.md"}))
    return cfg


def test_cmd_default_prints_prompt(tmp_path, capsys):
    _project(tmp_path)
    rc = main(["-C", str(tmp_path), "critique"])
    out = capsys.readouterr().out
    assert rc == 0 and "Return ONLY JSON" in out and "A finding" in out


def test_cmd_apply_records(tmp_path, capsys):
    cfg = _project(tmp_path)
    import io
    import sys
    sys.stdin = io.StringIO(json.dumps(VERDICT))
    try:
        rc = main(["-C", str(tmp_path), "critique", "exp", "--apply", "-"])
    finally:
        sys.stdin = sys.__stdin__
    assert rc == 0
    assert cfg.backlog().get("exp").links.get("critique")
    assert (tmp_path / "critiques" / "exp.md").exists()


def test_cmd_picks_last_done_without_critique(tmp_path):
    cfg = _project(tmp_path)
    # add a second, already-critiqued done idea — should be skipped
    cfg.backlog().add(Idea.new("older", id="old", status="done",
                               links={"report": "report.md", "critique": "x.md"}))
    from flywheel.cli import _pick_critique_target
    assert _pick_critique_target(cfg, None).id == "exp"


def test_cmd_errors_when_nothing_to_critique(tmp_path, capsys):
    (tmp_path / "flywheel.toml").write_text("backlog_path='queue.md'\n")
    rc = main(["-C", str(tmp_path), "critique"])
    assert rc == 1 and "no experiment to critique" in capsys.readouterr().err


def test_cmd_errors_when_no_report(tmp_path, capsys):
    (tmp_path / "flywheel.toml").write_text("backlog_path='queue.md'\n")
    cfg = Config.load(str(tmp_path))
    cfg.backlog().add(Idea.new("no report", id="exp", status="done"))
    rc = main(["-C", str(tmp_path), "critique", "exp"])
    assert rc == 1 and "no report to critique" in capsys.readouterr().err
