"""The hypothesis/experiment backlog — the queue the loop pulls from.

``Backlog`` is the storage seam. Everything else in flywheel talks to this
Protocol, never to a concrete file format, so swapping markdown for JSONL or
SQLite later is a one-class change (per the design: "markdown for now, don't
tightly couple").

``MarkdownBacklog`` is the default backend: a single human-readable,
hand-editable ``queue.md``. The on-disk format is regenerated from records on
every write, so it round-trips cleanly as long as hand-edits keep the structure
documented in ``MarkdownBacklog`` below.
"""

from __future__ import annotations

import os
from typing import Callable, Iterable, Optional, Protocol, runtime_checkable

from .models import Idea, Status, SELECTABLE

Predicate = Callable[[Idea], bool]


@runtime_checkable
class Backlog(Protocol):
    """Storage-agnostic contract for the experiment queue."""

    def all(self) -> list[Idea]: ...
    def get(self, idea_id: str) -> Optional[Idea]: ...
    def add(self, idea: Idea) -> Idea: ...
    def update(self, idea_id: str, **fields) -> Idea: ...
    def remove(self, idea_id: str) -> None: ...

    def next(self, predicate: Optional[Predicate] = None) -> Optional[Idea]:
        """Top selectable idea (highest priority, oldest first), optionally
        filtered by ``predicate`` (e.g. the guardrails' tier/budget check)."""
        ...


# Default selection ordering: highest priority first, then oldest (created asc),
# then id for determinism.
def _rank(idea: Idea):
    return (-idea.priority, idea.created, idea.id)


def select_next(
    ideas: Iterable[Idea], predicate: Optional[Predicate] = None
) -> Optional[Idea]:
    """Shared selection policy usable by any backend."""
    candidates = [i for i in ideas if i.status in SELECTABLE]
    if predicate is not None:
        candidates = [i for i in candidates if predicate(i)]
    if not candidates:
        return None
    return sorted(candidates, key=_rank)[0]


class MarkdownBacklog:
    """A ``queue.md`` backed backlog.

    On-disk format (one ``## <id>`` block per idea, regenerated on write)::

        # Experiment queue

        ## my-idea-id
        - **hypothesis**: one line
        - **rationale**: one line
        - **status**: proposed
        - **tier**: 0
        - **priority**: 5
        - **strikes**: 0
        - **cost**: $3
        - **source**: experiments/.../postmortem.md
        - **created**: 2026-06-26
        - **spec**:
        - **postmortem**:
        - **results**:
        - **report**:
        - **critique**:
        - **pr**:

        free-form notes until the next ## or EOF

    Hand-editing is fine: reorder blocks, bump ``priority``, flip ``status``.
    Keep the ``## id`` heading and the ``- **key**: value`` lines intact.
    """

    # Keys serialised as their own link sub-entries rather than top-level fields.
    # `report` is the run's required output (gated at the done transition);
    # `critique` is the rubric grading of that report (feedback for later loops);
    # `session` / `transcript` are provenance: the agent session + its decision trace.
    LINK_KEYS = ("spec", "postmortem", "results", "report", "critique",
                 "pr", "session", "transcript")
    HEADER = "# Experiment queue\n"

    def __init__(self, path: str):
        self.path = path

    # --- public API -------------------------------------------------------
    def all(self) -> list[Idea]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return self._parse(f.read())

    def get(self, idea_id: str) -> Optional[Idea]:
        for idea in self.all():
            if idea.id == idea_id:
                return idea
        return None

    def add(self, idea: Idea) -> Idea:
        ideas = self.all()
        if any(i.id == idea.id for i in ideas):
            # de-dupe by id: append a numeric suffix
            base, n = idea.id, 2
            existing = {i.id for i in ideas}
            while f"{base}-{n}" in existing:
                n += 1
            idea.id = f"{base}-{n}"
        ideas.append(idea)
        self._write(ideas)
        return idea

    def update(self, idea_id: str, **fields) -> Idea:
        ideas = self.all()
        target = None
        for idea in ideas:
            if idea.id == idea_id:
                target = idea
                break
        if target is None:
            raise KeyError(f"no idea with id {idea_id!r}")
        links = fields.pop("links", None)
        for k, v in fields.items():
            if k == "status" and isinstance(v, str):
                v = Status(v)
            if not hasattr(target, k):
                raise AttributeError(f"Idea has no field {k!r}")
            setattr(target, k, v)
        if links:
            target.links.update(links)
        target.__post_init__()  # re-coerce types
        self._write(ideas)
        return target

    def remove(self, idea_id: str) -> None:
        ideas = [i for i in self.all() if i.id != idea_id]
        self._write(ideas)

    def next(self, predicate: Optional[Predicate] = None) -> Optional[Idea]:
        return select_next(self.all(), predicate)

    # --- serialisation ----------------------------------------------------
    def _write(self, ideas: list[Idea]) -> None:
        out = [self.HEADER]
        for idea in ideas:
            out.append(self._render(idea))
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out).rstrip() + "\n")
        os.replace(tmp, self.path)

    def _render(self, idea: Idea) -> str:
        lines = [f"## {idea.id}"]
        lines.append(f"- **hypothesis**: {idea.hypothesis}")
        lines.append(f"- **rationale**: {idea.rationale}")
        lines.append(f"- **status**: {idea.status}")
        lines.append(f"- **tier**: {idea.tier}")
        lines.append(f"- **priority**: {idea.priority}")
        lines.append(f"- **strikes**: {idea.strikes}")
        lines.append(f"- **cost**: {idea.cost}")
        lines.append(f"- **source**: {idea.source}")
        lines.append(f"- **created**: {idea.created}")
        for k in self.LINK_KEYS:
            lines.append(f"- **{k}**: {idea.links.get(k, '')}")
        notes = idea.notes.strip()
        if notes:
            lines.append("")
            lines.append(notes)
        return "\n".join(lines) + "\n"

    def _parse(self, text: str) -> list[Idea]:
        ideas: list[Idea] = []
        # Split into blocks on level-2 headings.
        blocks = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if current:
                    blocks.append(current)
                current = [line]
            elif current:
                current.append(line)
        if current:
            blocks.append(current)

        for block in blocks:
            idea = self._parse_block(block)
            if idea is not None:
                ideas.append(idea)
        return ideas

    def _parse_block(self, block: list[str]) -> Optional[Idea]:
        heading = block[0][3:].strip()
        if not heading:
            return None
        fields: dict[str, str] = {}
        links: dict[str, str] = {}
        note_lines: list[str] = []
        in_notes = False
        for line in block[1:]:
            stripped = line.strip()
            if not in_notes and stripped.startswith("- **") and "**:" in stripped:
                key, _, val = stripped[4:].partition("**:")
                key = key.strip()
                val = val.strip()
                if key in self.LINK_KEYS:
                    if val:
                        links[key] = val
                else:
                    fields[key] = val
            elif not stripped and not in_notes:
                in_notes = True  # first blank line ends the field list
            elif in_notes:
                note_lines.append(line)
        data: dict = {"id": heading, "links": links}
        data.update({k: v for k, v in fields.items() if v != "" or k == "hypothesis"})
        data["notes"] = "\n".join(note_lines).strip()
        # hypothesis is required; default empty rather than crash on malformed
        data.setdefault("hypothesis", "")
        return Idea.from_dict(data)
