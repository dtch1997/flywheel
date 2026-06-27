"""Critique — grade a finished experiment's write-up against a rubric.

The run produces a report; the critique step asks the question the report itself
can't: *given the rubric, what can we actually conclude from this experiment?*
It grades the write-up and emits a verdict — for the default Anthropomorphic
Misalignment Research (AMR) rubric that's the tuple **(claimed rung, earned
rung, the failure-mode gap, the fixes that would close it)** — then records it.

The point is feedback, not a gate: a critique never blocks the `done` transition.
Instead the verdict is (a) attached to the idea + written to a critique file that
later iterations load as context, and (b) turned into concrete follow-up ideas
filed back onto the backlog — so a weak experiment seeds the rubric-driven
experiments that would strengthen it. Judgment (this module, LLM) stays separate
from mechanism; like triage, it only reads the report and writes feedback.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Optional

# A compact, self-contained form of the AMR evidence framework (arXiv
# 2606.07612). Projects override it with the fuller write-up via
# [critique] rubric_file (in jarvis: the lab-notes-jarvis AMR note).
DEFAULT_RUBRIC = """\
AMR (Anthropomorphic Misalignment Research) evidence framework — grade how much
the evidence actually licenses. Core rule: the evidence required scales with the
claim; downgrade any claim the methods don't reach.

EVIDENCE LADDER (grade the highest rung the METHODS earn, then compare to what
the PROSE claims):
- L1 Behavioral: "under setting S, behavior B occurs at rate p." Says nothing
  about why. Needs a dataset + operational definition + scorer.
- L2 Functional: "in deployment-plausible context C, B reliably causes
  downstream effect E" — across contexts, without attributing intent.
- L3 Causal-mechanistic: "internal structure M causes B" (intent, a represented
  goal, a mechanism). Needs interventions (ablation/steering/fine-tuning) and
  alternative-explanation testing. Correlation is not enough.

RECOMMENDATIONS (R1-R12), by stage — the report passes a stage only at the level
it claims:
  S1 framing:   R1 define behavior + explicit exclusions · R2 declare evidence
                level upfront · R3 ground anthropomorphic terms in observables.
  S2 data:      R4 justify dataset size vs effect · R5 distributional diversity +
                surface-feature controls.
  S3 design:    R6 scorer reliability (human + audit the LLM judge) · R7 measure
                general capability to isolate the intervention · R8 ablate
                (paraphrase/scale/temperature) + report uncertainty · R9 test
                alternative explanations with negative controls.
  S4 mechanism: R10 interventionist evidence · R11 falsifiable mechanistic
                hypotheses · R12 match conclusions to evidence level.

FAILURE MODES (C1-C9) — symptoms that knock earned rung below claimed rung:
  C1 anthropomorphic concept underspecified · C2 concept hard to measure (proxy
  tracks prompt cues) · C3 dataset small/low-diversity · C4 definition drift into
  dataset design · C5 design choices unablated · C6 unreliable LLM judge · C7
  non-target mechanism unmeasured (instruction ambiguity / task-completion /
  capability shift confound) · C8 spurious correlation (fires on vocab/persona/
  framing) · C9 mechanistic method overstates functional relevance (predict ≠
  control).

VERDICT = (claimed rung Lx; earned rung Ly ≤ x; the C-gap {Ci} driving x→y; the
R-fix {Rj} that would close it; and a one-paragraph "what we can actually
conclude" stated at the EARNED rung).
"""

CRITIQUE_TEMPLATE = """\
You are CRITIQUING a finished experiment's write-up against the rubric below, to
determine what can ACTUALLY be concluded from it. Be a skeptical referee, not a
cheerleader: grade the evidence the methods earn, not the story the prose tells.
Apply the rubric strictly and cite its specific items (rungs / R# / C#).

== RUBRIC ==
{rubric}

== PROJECT CONTEXT (north stars + recent results) ==
{context}

== THE EXPERIMENT ==
  id:         {idea_id}
  hypothesis: {hypothesis}
  rationale:  {rationale}

== THE REPORT TO CRITIQUE ==
{report}

Grade it against the rubric. Then propose follow-up experiments that would close
the gap you found (each grounded in a specific R-fix), so the next loop iteration
can act on them. Be concrete and de-risked, not a vague remix.

Return ONLY JSON:
{{"claimed_rung": "<L1|L2|L3>",
  "earned_rung": "<L1|L2|L3>",
  "c_gap": ["<C#>", ...],
  "r_fix": ["<R#>", ...],
  "conclusion": "<one paragraph: what we can actually conclude, at the EARNED rung>",
  "summary": "<=20 words headline verdict",
  "followups": [{{"hypothesis": "<one line>", "rationale": "<which R-fix it closes & why>",
                  "tier": <0|1|2>, "cost": "<$est>", "priority": <int 0-10>}}]}}
The earned rung must be <= the claimed rung. followups may be [] if the evidence
already matches the claim.
"""


def build_critique_prompt(rubric: str, report: str, idea, context: str = "",
                          template: str = CRITIQUE_TEMPLATE) -> str:
    return template.format(
        rubric=rubric or DEFAULT_RUBRIC,
        context=context or "(no context)",
        idea_id=idea.id,
        hypothesis=idea.hypothesis,
        rationale=idea.rationale or "(none given)",
        report=report or "(report empty)",
    )


def _render_critique_md(idea_id: str, v: dict) -> str:
    """A human-readable critique artifact (also what later iterations re-read)."""
    gap = ", ".join(v.get("c_gap", [])) or "—"
    fix = ", ".join(v.get("r_fix", [])) or "—"
    lines = [
        f"# Critique — {idea_id}",
        "",
        f"**Verdict:** claims {v.get('claimed_rung', '?')}, "
        f"earns {v.get('earned_rung', '?')}  ·  gap: {gap}  ·  fix: {fix}",
        "",
        f"_{v.get('summary', '').strip()}_" if v.get("summary") else "",
        "",
        "## What we can actually conclude",
        v.get("conclusion", "").strip() or "(none given)",
    ]
    fus = v.get("followups") or []
    if fus:
        lines += ["", "## Follow-ups to close the gap"]
        for f in fus:
            lines.append(
                f"- ({f.get('tier', 0)}, {f.get('cost', '?')}) {f.get('hypothesis', '')}"
                f" — {f.get('rationale', '')}")
    return "\n".join(l for l in lines if l is not None).rstrip() + "\n"


def _verdict_line(v: dict) -> str:
    gap = ",".join(v.get("c_gap", [])) or "-"
    fix = ",".join(v.get("r_fix", [])) or "-"
    return (f"critique: claims {v.get('claimed_rung', '?')} / "
            f"earns {v.get('earned_rung', '?')} (gap {gap}; fix {fix})"
            + (f" — {v.get('summary', '').strip()}" if v.get("summary") else ""))


def apply_critique(backlog, idea_id: str, verdict: dict, *,
                   critique_dir: str, root: Optional[str] = None,
                   log_path: Optional[str] = None,
                   file_followups: bool = True) -> dict:
    """Record a critique: write the artifact, attach it + the verdict to the idea,
    file R-fix follow-ups back onto the backlog, and log it.

    Never changes the idea's status — the critique is feedback, not a gate.
    The artifact is written under ``critique_dir``; the link stored on the idea
    is relative to ``root`` (if given) so it stays portable in the committed repo.
    Returns {critique_path, verdict_line, filed}. Unknown id is fatal here
    (you critique a specific experiment), unlike triage.
    """
    if backlog.get(idea_id) is None:
        raise KeyError(f"no idea with id {idea_id!r}")

    os.makedirs(os.path.abspath(critique_dir), exist_ok=True)
    cpath = os.path.join(critique_dir, f"{idea_id}.md")
    with open(cpath, "w", encoding="utf-8") as f:
        f.write(_render_critique_md(idea_id, verdict))
    link = os.path.relpath(cpath, root) if root else cpath

    # Attach the artifact + a one-line verdict, prepended to notes so it surfaces
    # in `list`/context for later iterations. Status is untouched.
    idea = backlog.get(idea_id)
    vline = _verdict_line(verdict)
    notes = idea.notes.strip()
    new_notes = vline + ("\n" + notes if notes else "")
    backlog.update(idea_id, links={"critique": link}, notes=new_notes)

    # Feedback into subsequent iterations: file the rubric-driven follow-ups.
    filed = []
    if file_followups:
        from .models import Idea
        for f in (verdict.get("followups") or []):
            hyp = (f.get("hypothesis") or "").strip()
            if not hyp:
                continue
            new = backlog.add(Idea.new(
                hyp,
                rationale=f.get("rationale", ""),
                tier=int(f.get("tier", 0) or 0),
                priority=int(f.get("priority", 0) or 0),
                cost=f.get("cost", "") or "",
                source=f"{idea_id}:critique",
            ))
            filed.append(new.id)

    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                "id": idea_id, "verdict": verdict, "filed": filed,
            }) + "\n")

    return {"critique_path": link, "verdict_line": vline, "filed": filed}


def parse_critique(text: str) -> dict:
    """Extract the verdict JSON object from an agent's output."""
    import re
    for m in reversed(list(re.finditer(r"\{.*\}", text, re.S))):
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and ("earned_rung" in obj or "conclusion" in obj):
            return obj
    return {"claimed_rung": "", "earned_rung": "", "c_gap": [], "r_fix": [],
            "conclusion": "", "summary": "", "followups": []}
