"""Session provenance — tie an experiment to the agent session that produced it.

The backlog records *what* was decided; the session transcript records *why*.
This module captures the Claude Code session id behind an iteration and locates
(optionally archives) its transcript, so reviewing an experiment opens the
agent's full decision trace.

- In-harness (``/loop``): the live session id is in ``$CLAUDE_CODE_SESSION_ID``.
- Headless (``claude -p --output-format json``): the runner parses ``session_id``
  from the result and records it automatically.
"""

from __future__ import annotations

import glob
import os
import shutil
from typing import Optional

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def current_session_id() -> Optional[str]:
    """The Claude Code session id of the running (in-harness) agent, if any."""
    return os.environ.get(SESSION_ENV) or None


def _projects_root() -> str:
    return os.path.expanduser(os.path.join("~", ".claude", "projects"))


def transcript_path(session_id: str, projects_root: Optional[str] = None) -> Optional[str]:
    """Locate ``<projects>/**/<session_id>.jsonl`` (Claude Code's transcript)."""
    if not session_id:
        return None
    root = projects_root or _projects_root()
    hits = glob.glob(os.path.join(root, "**", f"{session_id}.jsonl"), recursive=True)
    return hits[0] if hits else None


def archive_transcript(session_id: str, dest_dir: str,
                       projects_root: Optional[str] = None) -> Optional[str]:
    """Copy the session transcript into ``dest_dir`` for durable provenance.

    Transcripts live under the user's ``~/.claude`` and can rotate/disappear;
    archiving a copy next to the experiment keeps the decision history with the
    result. Returns the archived path, or None if the transcript wasn't found.
    """
    src = transcript_path(session_id, projects_root)
    if not src:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"session-{session_id}.jsonl")
    shutil.copy2(src, dest)
    return dest
