"""Triage — an agent re-prioritizes the backlog instead of popping it blindly.

`select()` is a deterministic mechanism (pop highest priority). But priority is a
static integer set when an idea was filed, so the head of the queue drifts out of
date as results come in. Triage is the *judgment* layer: an agent reads the north
stars + the whole backlog + what's already been learned, and rewrites priorities
(and drops stale/subsumed ideas) so the next pop reflects current taste.

Judgment (this module, LLM) is kept separate from mechanism (`select`,
deterministic): triage only rewrites `priority` / `status`.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Optional

from .models import Status

TRIAGE_TEMPLATE = """\
You are TRIAGING an experiment backlog: decide what is most interesting/valuable
to run NEXT. Re-prioritize the PROPOSED ideas (and drop any that are stale,
already-answered, or low-value) given the north stars and what we've already
learned. Do not invent new ideas here — only rank and prune what's listed.

== PROJECT CONTEXT (north stars + recent results) ==
{context}

== ALREADY LEARNED (concluded experiments + outcome notes) ==
{learned}

== BACKLOG TO TRIAGE (proposed ideas) ==
{proposed}

Weigh: novelty / unexpectedness, whether it *validates a surprising-but-unconfirmed*
result (replication beats yet-another new hypothesis), information-per-dollar,
and fit to the north stars. Reward closing the loop on shaky findings over piling
up more.

Return ONLY JSON:
{{"rankings": [{{"id": "<id>", "priority": <int 0-10>, "reason": "<=15 words"}}],
  "drop": [{{"id": "<id>", "reason": "<=15 words"}}]}}
Higher priority = sooner. Every proposed id must appear in exactly one of rankings/drop.
"""


def _fmt_idea(i) -> str:
    bits = [f"tier {i.tier}", f"cost {i.cost or '?'}", f"cur_prio {i.priority}"]
    if i.source:
        bits.append(f"from {i.source}")
    return f"- {i.id} ({', '.join(bits)})\n    hyp: {i.hypothesis}\n    why: {i.rationale}"


def _fmt_learned(i) -> str:
    note = i.notes.strip().splitlines()[0] if i.notes.strip() else "(no outcome note)"
    return f"- {i.id} [{i.status}]: {i.hypothesis}\n    outcome: {note}"


def build_triage_prompt(context: str, proposed: list, done: list,
                        template: str = TRIAGE_TEMPLATE) -> str:
    return template.format(
        context=context or "(no context)",
        learned="\n".join(_fmt_learned(i) for i in done) or "(nothing concluded yet)",
        proposed="\n".join(_fmt_idea(i) for i in proposed) or "(backlog empty)",
    )


def apply_triage(backlog, rankings: list, drops: Optional[list] = None,
                 log_path: Optional[str] = None) -> dict:
    """Apply a triage decision: rewrite priorities, drop flagged ideas, log it.

    Returns a summary {updated, dropped, skipped}. Unknown ids are skipped, not
    fatal (the backlog may have changed since the prompt was built)."""
    drops = drops or []
    updated, dropped, skipped = [], [], []
    for r in rankings:
        iid = r.get("id")
        if backlog.get(iid) is None:
            skipped.append(iid)
            continue
        backlog.update(iid, priority=int(r["priority"]))
        updated.append((iid, int(r["priority"]), r.get("reason", "")))
    for d in drops:
        iid = d.get("id")
        if backlog.get(iid) is None:
            skipped.append(iid)
            continue
        backlog.update(iid, status=Status.DROPPED)
        dropped.append((iid, d.get("reason", "")))
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                "rankings": rankings, "drop": drops,
            }) + "\n")
    return {"updated": updated, "dropped": dropped, "skipped": skipped}


def parse_rankings(text: str) -> dict:
    """Extract the {rankings, drop} JSON object from an agent's output."""
    import re
    # last JSON object containing "rankings"
    for m in reversed(list(re.finditer(r"\{.*\}", text, re.S))):
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "rankings" in obj:
            return obj
    return {"rankings": [], "drop": []}
