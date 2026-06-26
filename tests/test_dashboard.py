from flywheel.backlog import MarkdownBacklog
from flywheel.cli import _dashboard_monitors, _DASH_STATE
from flywheel.config import Config
from flywheel.models import Idea


def _cfg(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea.new("done one", id="a"))
    bl.add(Idea.new("running one", id="b", tier=1, priority=5, cost="$3"))
    bl.add(Idea.new("dropped one", id="c", strikes=3))
    bl.update("a", status="done")
    bl.update("b", status="running")
    bl.update("c", status="dropped")
    bl.add(Idea.new("proposed one", id="d"))
    cfg = Config(root=str(tmp_path), backlog_path="queue.md")
    return cfg


def test_status_maps_to_stagehand_vocab(tmp_path):
    mons = {m["name"]: m for m in _dashboard_monitors(_cfg(tmp_path))}
    assert mons["a"]["state"] == "done" and mons["a"]["done"] == 1
    assert mons["b"]["state"] == "running" and mons["b"]["done"] == 0
    assert mons["c"]["state"] == "failed"      # dropped -> failed (red)
    assert mons["d"]["state"] == "proposed"


def test_each_idea_is_a_root(tmp_path):
    mons = _dashboard_monitors(_cfg(tmp_path))
    assert all(m["parent"] is None for m in mons)   # ideas are roots; live units nest under them


def test_extra_carries_display_fields(tmp_path):
    mons = {m["name"]: m for m in _dashboard_monitors(_cfg(tmp_path))}
    assert mons["b"]["extra"]["tier"] == 1
    assert mons["b"]["extra"]["cost"] == "$3"
    assert mons["c"]["extra"]["strikes"] == 3
    assert "strikes" not in mons["a"]["extra"]      # omitted when zero
