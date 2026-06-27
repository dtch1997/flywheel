"""Output gate: a finished run must leave a persistable report behind."""

import importlib.util

import pytest

from flywheel.cli import main
from flywheel.config import Config
from flywheel.models import Idea, Status
from flywheel.output import NullGate, make_gate, resolve_report_path

HAS_REPORTLY = importlib.util.find_spec("reportly") is not None

GOOD_REPORT = """\
---
vibe: positive
---

# Chain-of-thought halves the negation-neglect error rate

## TL;DR
CoT cut the error rate from 40% to 18% on the held-out set.

## Setup
We compared direct vs CoT prompting on 200 negation items.

## Result
![headline](figs/headline.png)

The error rate dropped from 40% to 18%.

## Discussion
CoT gives the model room to surface the negation before answering.

## Next steps
Test whether the effect survives distillation back into the base model.

## Reproduce
```bash
python run.py --mode cot --seed 0
```

*Branch: run-output-gate · Model: claude · Artifacts: gs://... · Code: run.py*
"""

BAD_REPORT = "just some notes, no structure at all\n"


def _new_idea(**kw):
    return Idea.new(kw.pop("hypothesis", "does X cause Y"), **kw)


# --- gate units (no reportly needed) -------------------------------------
def test_null_gate_always_passes():
    assert NullGate().check(_new_idea()).ok


def test_require_report_false_gives_null_gate():
    gate = make_gate("reportly", require_report=False)
    assert isinstance(gate, NullGate)
    assert gate.check(_new_idea()).ok


def test_exists_gate_needs_a_path(tmp_path):
    gate = make_gate("none", root=str(tmp_path))
    res = gate.check(_new_idea())
    assert not res.ok and "no report" in res.reason


def test_exists_gate_needs_the_file_present(tmp_path):
    gate = make_gate("none", root=str(tmp_path))
    res = gate.check(_new_idea(), report_path="ghost.md")
    assert not res.ok and "not found" in res.reason


def test_exists_gate_passes_when_present(tmp_path):
    (tmp_path / "r.md").write_text("anything")
    gate = make_gate("none", root=str(tmp_path))
    assert gate.check(_new_idea(), report_path="r.md").ok


def test_resolve_prefers_explicit_over_link(tmp_path):
    idea = _new_idea()
    idea.links["report"] = "old.md"
    assert resolve_report_path(idea, "new.md", root=str(tmp_path)).endswith("new.md")
    assert resolve_report_path(idea, None, root=str(tmp_path)).endswith("old.md")


def test_unknown_validator_raises():
    with pytest.raises(ValueError):
        make_gate("bogus")


def test_reportly_missing_gives_helpful_error(monkeypatch):
    import sys
    # sys.modules[name] = None makes `import name` raise ImportError.
    monkeypatch.setitem(sys.modules, "reportly", None)
    with pytest.raises(RuntimeError, match="reportly"):
        make_gate("reportly")


# --- cmd_update integration (validator="none", no reportly) --------------
def _project(tmp_path, validator="none"):
    (tmp_path / "flywheel.toml").write_text(
        "backlog_path = 'queue.md'\n"
        "[output]\n"
        f"validator = '{validator}'\n"
    )
    cfg = Config.load(str(tmp_path))
    bl = cfg.backlog()
    bl.add(Idea.new("the experiment", id="exp", status="running"))
    return cfg


def test_done_refused_without_report(tmp_path, capsys):
    cfg = _project(tmp_path)
    rc = main(["-C", str(tmp_path), "update", "exp", "--status", "done"])
    assert rc == 1
    assert "refusing to mark" in capsys.readouterr().err
    # status unchanged — the transition did not apply
    assert cfg.backlog().get("exp").status == Status.RUNNING


def test_done_allowed_with_report(tmp_path):
    cfg = _project(tmp_path)
    (tmp_path / "report.md").write_text("a report")
    rc = main(["-C", str(tmp_path), "update", "exp", "--status", "done",
               "--report", "report.md"])
    assert rc == 0
    idea = cfg.backlog().get("exp")
    assert idea.status == Status.DONE
    assert idea.links["report"] == "report.md"


def test_no_gate_overrides(tmp_path):
    cfg = _project(tmp_path)
    rc = main(["-C", str(tmp_path), "update", "exp", "--status", "done", "--no-gate"])
    assert rc == 0
    assert cfg.backlog().get("exp").status == Status.DONE


def test_non_done_update_is_not_gated(tmp_path):
    cfg = _project(tmp_path)
    rc = main(["-C", str(tmp_path), "update", "exp", "--priority", "5"])
    assert rc == 0
    assert cfg.backlog().get("exp").priority == 5


# --- reportly validator (skipped if reportly absent) ---------------------
@pytest.mark.skipif(not HAS_REPORTLY, reason="reportly not installed")
def test_reportly_gate_rejects_bad_report(tmp_path):
    (tmp_path / "bad.md").write_text(BAD_REPORT)
    gate = make_gate("reportly", root=str(tmp_path))
    res = gate.check(_new_idea(), report_path="bad.md")
    assert not res.ok and "reportly" in res.reason.lower()


@pytest.mark.skipif(not HAS_REPORTLY, reason="reportly not installed")
def test_reportly_gate_accepts_good_report(tmp_path):
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "headline.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "good.md").write_text(GOOD_REPORT)
    gate = make_gate("reportly", root=str(tmp_path))
    res = gate.check(_new_idea(), report_path="good.md")
    assert res.ok, res.reason


@pytest.mark.skipif(not HAS_REPORTLY, reason="reportly not installed")
def test_cmd_update_gated_by_reportly(tmp_path):
    cfg = _project(tmp_path, validator="reportly")
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "headline.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "bad.md").write_text(BAD_REPORT)
    rc = main(["-C", str(tmp_path), "update", "exp", "--status", "done",
               "--report", "bad.md"])
    assert rc == 1 and cfg.backlog().get("exp").status == Status.RUNNING
    (tmp_path / "good.md").write_text(GOOD_REPORT)
    rc = main(["-C", str(tmp_path), "update", "exp", "--status", "done",
               "--report", "good.md"])
    assert rc == 0 and cfg.backlog().get("exp").status == Status.DONE
