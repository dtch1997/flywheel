"""Assemble the project context an iteration needs.

The loop's first job is "load all context about the project, including north
stars". This module turns a declarative list of sources into a single
prompt-ready string. Sources are config, not code, so each project decides what
its agent should read (north-stars doc, prediction registry, recent
postmortems, the queue itself, ...).
"""

from __future__ import annotations

import glob as _glob
import os
from dataclasses import dataclass, field


@dataclass
class Source:
    """One context source.

    kind:
      - ``file``        : read a single file (``path``)
      - ``glob``        : read every file matching ``pattern``
      - ``recent_glob`` : read the ``n`` most-recently-modified matches of ``pattern``
    """

    kind: str
    label: str
    path: str = ""
    pattern: str = ""
    n: int = 3
    max_chars: int = 4000  # per file, truncated with a marker

    def resolve(self, root: str) -> list[tuple[str, str]]:
        """Return [(display_path, text)] for this source."""
        if self.kind == "file":
            p = os.path.join(root, self.path)
            return [(self.path, _read(p, self.max_chars))] if os.path.exists(p) else []
        pattern = os.path.join(root, self.pattern)
        matches = sorted(_glob.glob(pattern, recursive=True))
        if self.kind == "recent_glob":
            matches = sorted(matches, key=lambda p: os.path.getmtime(p), reverse=True)[
                : self.n
            ]
        out = []
        for m in matches:
            rel = os.path.relpath(m, root)
            out.append((rel, _read(m, self.max_chars)))
        return out


def _read(path: str, max_chars: int) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return f"<could not read {path}: {e}>"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n… [truncated, {len(text) - max_chars} more chars]"
    return text


@dataclass
class ContextLoader:
    """Render a list of sources into one Markdown context blob."""

    root: str = "."
    sources: list[Source] = field(default_factory=list)

    def load(self) -> str:
        sections: list[str] = []
        for src in self.sources:
            chunks = src.resolve(self.root)
            if not chunks:
                continue
            sections.append(f"# Context — {src.label}")
            for rel, text in chunks:
                sections.append(f"## `{rel}`\n\n{text.strip()}")
        return "\n\n".join(sections).strip()
