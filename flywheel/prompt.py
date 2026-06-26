"""The iteration prompt — what the agent is told to do each loop.

The template is a string with ``{placeholders}``. Projects override it (or the
``protocol`` block) via config so the generic loop becomes project-specific
without code changes. The jarvis config, for example, points ``protocol`` at its
experiment runbook, outbox style, and the "wrap up" reproducibility checklist.
"""

from __future__ import annotations

DEFAULT_PROTOCOL = """\
1. SPEC FIRST. Write a spec before spending: hypothesis, a registered
   prediction with a confidence, the design, positive AND negative controls,
   and a cost estimate. An experiment that fails its controls is discarded.
2. RUN IT. Execute the experiment. Keep it cheap-first (dry-run, then scale).
3. WRITE UP. Record results vs the registered prediction. Flag any surprise
   (result contradicts prediction) prominently — discovery or bug.
4. REPRODUCIBILITY. Commit the spec + exact command + seeds/config so a fresh
   run regenerates the result. Persist large artifacts to durable storage and
   commit a pointer, not the bytes.
5. BRAINSTORM NEXT. Propose 2-4 concrete follow-up experiments, each with an
   interestingness rationale and a cost tier.
"""

DEFAULT_TEMPLATE = """\
You are running ONE iteration of an autonomous experiment loop. Do the whole
iteration end-to-end, then stop.

== PROJECT CONTEXT ==
{context}

== THE EXPERIMENT YOU ARE RUNNING THIS ITERATION ==
This was selected from the backlog. Do THIS one (don't re-pick):

  id:         {idea_id}
  hypothesis: {hypothesis}
  rationale:  {rationale}
  cost tier:  {tier}   (est. {cost})
  source:     {source}
  notes:      {notes}

== PROTOCOL (follow exactly) ==
{protocol}

== BOOKKEEPING (do this with the flywheel CLI) ==
- When you finish, record the outcome and artifact links:
    {cli} update {idea_id} --status done \\
        --spec <path> --postmortem <path> --results <path> --pr <url>
  If the run was uninformative (no signal, broken harness you couldn't fix),
  instead add a strike:
    {cli} update {idea_id} --strikes {next_strike}
  (At {max_strikes} strikes an idea is auto-dropped — escalate or drop.)
- Log spend so the daily budget stays accurate:
    {cli} spend <dollars> --idea {idea_id} --note "<what>"
- Record provenance — the session behind this decision (so it can be reviewed):
    {cli} session --idea {idea_id} --archive <run_dir>
  (headless `flywheel run` records the session id automatically; this is for the
  in-harness case.)
- File each follow-up you brainstormed back onto the backlog:
    {cli} add --hypothesis "<one line>" --rationale "<why interesting>" \\
        --tier <0|1|2> --cost "<$est>" --source {idea_id} --priority <n>

That last step is what keeps the flywheel turning: a future iteration will pick
up what you propose. Be specific and de-risked, not a vague remix.
"""


def build_prompt(
    *,
    idea,
    context: str,
    protocol: str = DEFAULT_PROTOCOL,
    template: str = DEFAULT_TEMPLATE,
    cli: str = "flywheel",
    max_strikes: int = 3,
) -> str:
    return template.format(
        context=context or "(no context sources configured)",
        idea_id=idea.id,
        hypothesis=idea.hypothesis,
        rationale=idea.rationale or "(none given)",
        tier=idea.tier,
        cost=idea.cost or "unknown",
        source=idea.source or "(none)",
        notes=idea.notes or "(none)",
        protocol=protocol,
        cli=cli,
        next_strike=idea.strikes + 1,
        max_strikes=max_strikes,
    )
