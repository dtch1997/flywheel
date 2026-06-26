from flywheel.backlog import MarkdownBacklog, select_next
from flywheel.models import Idea, Status


def test_add_get_roundtrip(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    idea = Idea.new(
        "Does X cause Y?",
        rationale="untested implication of paper Z",
        tier=1,
        priority=5,
        cost="$3",
        source="experiments/foo/postmortem.md",
        notes="multi\nline note",
    )
    bl.add(idea)
    got = bl.get(idea.id)
    assert got is not None
    assert got.hypothesis == "Does X cause Y?"
    assert got.rationale == "untested implication of paper Z"
    assert got.tier == 1
    assert got.priority == 5
    assert got.cost == "$3"
    assert got.source == "experiments/foo/postmortem.md"
    assert got.notes == "multi\nline note"
    assert got.status == Status.PROPOSED


def test_links_roundtrip(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea.new("hyp"))
    iid = bl.all()[0].id
    bl.update(iid, status="done", links={"spec": "a/spec.md", "pr": "http://x/1"})
    got = bl.get(iid)
    assert got.status == Status.DONE
    assert got.links["spec"] == "a/spec.md"
    assert got.links["pr"] == "http://x/1"


def test_duplicate_id_suffixes(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    a = bl.add(Idea(id="dup", hypothesis="one"))
    b = bl.add(Idea(id="dup", hypothesis="two"))
    assert a.id == "dup"
    assert b.id == "dup-2"
    assert len(bl.all()) == 2


def test_remove(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "queue.md"))
    bl.add(Idea(id="keep", hypothesis="k"))
    bl.add(Idea(id="gone", hypothesis="g"))
    bl.remove("gone")
    assert [i.id for i in bl.all()] == ["keep"]


def test_select_next_priority_then_age():
    ideas = [
        Idea(id="low", hypothesis="a", priority=1, created="2026-01-01"),
        Idea(id="hi-old", hypothesis="b", priority=9, created="2026-01-01"),
        Idea(id="hi-new", hypothesis="c", priority=9, created="2026-02-01"),
        Idea(id="done", hypothesis="d", priority=99, status=Status.DONE),
    ]
    nxt = select_next(ideas)
    assert nxt.id == "hi-old"  # highest priority, oldest of the ties; done excluded


def test_select_next_predicate():
    ideas = [Idea(id="t2", hypothesis="x", tier=2), Idea(id="t0", hypothesis="y", tier=0)]
    nxt = select_next(ideas, predicate=lambda i: i.tier == 0)
    assert nxt.id == "t0"


def test_empty_backlog(tmp_path):
    bl = MarkdownBacklog(str(tmp_path / "nope.md"))
    assert bl.all() == []
    assert bl.next() is None
