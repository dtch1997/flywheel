"""``flywheel`` command-line interface.

Subcommands:
  init     scaffold flywheel.toml + an empty queue in the current dir
  add      add an idea to the backlog
  list     show backlog ideas (filterable)
  next     show the idea the loop would pick next (respects guardrails)
  update   change an idea's fields (status, strikes, links, ...)
  spend    log a dollar amount against the daily budget
  status   summarise the backlog + today's spend
  prompt   print the assembled iteration prompt (for in-harness /loop use)
  run      drive N headless iterations via the configured agent runner
  triage   an agent re-prioritizes the backlog (north stars + what's learned)
  dashboard  render (and optionally serve) a live status page via stagehand
  session  record the agent session (provenance) on an idea
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

from .config import Config
from .engine import LoopEngine
from .models import Idea, Status
from .prompt import DEFAULT_PROTOCOL, DEFAULT_TEMPLATE
from .runner import ClaudeCliRunner, EmitRunner


_SCAFFOLD_TOML = """\
# flywheel — autonomous experiment loop config.
# Everything here has a default; trim what you don't need.

backlog_path = "queue.md"
ledger_path  = ".flywheel/spend.jsonl"
cli          = "flywheel"

# What the agent reads as project context each iteration. Order matters.
[[sources]]
kind  = "file"
label = "north stars"
path  = "NORTH_STARS.md"

# Example: the N most recently touched experiment writeups.
# [[sources]]
# kind       = "recent_glob"
# label      = "recent postmortems"
# pattern    = "experiments/*/postmortem.md"
# n          = 5
# max_chars  = 3000

[guardrails]
max_tier         = 2      # highest cost tier the loop may pick unattended
daily_budget_usd = 50.0   # the real rail for "fully autonomous"
max_strikes      = 3      # uninformative runs before an idea is dropped

[runner]
kind = "claude"           # "claude" (headless) | "emit" (in-harness /loop)
bin  = "claude"
# args = ["--permission-mode", "acceptEdits"]   # your permission posture
# model = ""
# timeout = 0

# [prompt]
# protocol_file = "EXPERIMENT_PROTOCOL.md"   # override the built-in protocol
# template_file = "ITERATION_PROMPT.md"      # override the whole prompt

[output]
# A run's output must be a persistable report. `update --status done` is gated
# on it: no valid report -> the idea can't be marked done (override: --no-gate).
require_report = true
validator      = "reportly"   # "reportly" (lint the report) | "none" (exists-only)
level          = "error"      # reportly fail threshold: "error" | "warn"
report_link    = "report"     # which link field holds the report path
"""


# --- helpers -------------------------------------------------------------
def _load(args) -> Config:
    return Config.load(args.config or ".")


def _engine(cfg: Config, force_emit: bool = False) -> LoopEngine:
    if force_emit or cfg.runner == "emit":
        runner = EmitRunner()
    else:
        runner = ClaudeCliRunner(
            bin=cfg.claude_bin,
            model=cfg.model,
            extra_args=tuple(cfg.claude_args),
            timeout=cfg.timeout or None,
        )
    return LoopEngine(
        backlog=cfg.backlog(),
        context_loader=cfg.context_loader(),
        guardrails=cfg.guardrails(),
        runner=runner,
        cli=cfg.cli,
        protocol=cfg.protocol_text() or DEFAULT_PROTOCOL,
        template=cfg.template_text() or DEFAULT_TEMPLATE,
        cwd=cfg.root,
    )


def _fmt_idea(idea: Idea, verbose: bool = False) -> str:
    head = (
        f"[{idea.status}] {idea.id}  (tier {idea.tier}, prio {idea.priority}"
        f", {idea.strikes} strikes{', ' + idea.cost if idea.cost else ''})"
    )
    if not verbose:
        return f"{head}\n    {idea.hypothesis}"
    lines = [head, f"    hypothesis: {idea.hypothesis}"]
    if idea.rationale:
        lines.append(f"    rationale:  {idea.rationale}")
    if idea.source:
        lines.append(f"    source:     {idea.source}")
    links = {k: v for k, v in idea.links.items() if v and not k.startswith("_")}
    if links:
        lines.append("    links:      " + ", ".join(f"{k}={v}" for k, v in links.items()))
    return "\n".join(lines)


# --- commands ------------------------------------------------------------
def cmd_init(args) -> int:
    import os

    root = args.config if args.config and os.path.isdir(args.config) else "."
    cfg_path = os.path.join(root, "flywheel.toml")
    queue_path = os.path.join(root, "queue.md")
    if os.path.exists(cfg_path) and not args.force:
        print(f"{cfg_path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(_SCAFFOLD_TOML)
    if not os.path.exists(queue_path):
        with open(queue_path, "w", encoding="utf-8") as f:
            f.write("# Experiment queue\n")
    print(f"wrote {cfg_path} and {queue_path}")
    return 0


def cmd_add(args) -> int:
    cfg = _load(args)
    backlog = cfg.backlog()
    if args.json:
        data = json.loads(sys.stdin.read() if args.json == "-" else args.json)
        ideas = data if isinstance(data, list) else [data]
        added = [backlog.add(Idea.from_dict(d)) for d in ideas]
        for idea in added:
            print(f"added {idea.id}")
        return 0
    if not args.hypothesis:
        print("error: --hypothesis is required (or use --json)", file=sys.stderr)
        return 2
    idea = Idea.new(
        args.hypothesis,
        rationale=args.rationale or "",
        tier=args.tier,
        priority=args.priority,
        cost=args.cost or "",
        source=args.source or "",
        notes=args.notes or "",
    )
    if args.id:
        idea.id = args.id
    added = backlog.add(idea)
    print(f"added {added.id}")
    return 0


def cmd_list(args) -> int:
    cfg = _load(args)
    ideas = cfg.backlog().all()
    if args.status:
        ideas = [i for i in ideas if str(i.status) == args.status]
    if args.tier is not None:
        ideas = [i for i in ideas if i.tier == args.tier]
    if not ideas:
        print("(backlog empty)")
        return 0
    for idea in ideas:
        print(_fmt_idea(idea, verbose=args.verbose))
    return 0


def cmd_next(args) -> int:
    cfg = _load(args)
    engine = _engine(cfg, force_emit=True)
    idea = engine.select()
    if idea is None:
        # explain why nothing is eligible
        guard = cfg.guardrails()
        blocked = []
        for i in cfg.backlog().all():
            if i.status in (Status.PROPOSED, Status.PICKED):
                ok, reason = guard.check(i)
                if not ok:
                    blocked.append(f"  {i.id}: {reason}")
        print("nothing eligible to pick.")
        if blocked:
            print("blocked by guardrails:")
            print("\n".join(blocked))
        return 0
    print(_fmt_idea(idea, verbose=True))
    return 0


def cmd_update(args) -> int:
    cfg = _load(args)
    backlog = cfg.backlog()
    fields = {}
    if args.status:
        fields["status"] = args.status
    if args.strikes is not None:
        fields["strikes"] = args.strikes
    if args.priority is not None:
        fields["priority"] = args.priority
    if args.tier is not None:
        fields["tier"] = args.tier
    if args.cost is not None:
        fields["cost"] = args.cost
    if args.notes is not None:
        fields["notes"] = args.notes
    links = {}
    for k in ("spec", "postmortem", "results", "report", "pr", "session", "transcript"):
        v = getattr(args, k)
        if v is not None:
            links[k] = v
    if links:
        fields["links"] = links
    if not fields:
        print("nothing to update", file=sys.stderr)
        return 2

    # Output gate: a run's *output* must be a persistable report. Refuse the
    # done transition until one exists and validates — covers both the headless
    # runner and the in-harness agent, since both close out via `update`.
    if fields.get("status") == Status.DONE.value and not args.no_gate:
        current = backlog.get(args.id)
        if current is None:
            print(f"error: no idea with id {args.id!r}", file=sys.stderr)
            return 1
        try:
            result = cfg.gate().check(current, report_path=args.report)
        except RuntimeError as e:  # validator not installed / misconfigured
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not result.ok:
            print(f"refusing to mark {args.id!r} done: {result.reason}",
                  file=sys.stderr)
            print("(fix the report, or pass --no-gate to override)", file=sys.stderr)
            return 1

    try:
        idea = backlog.update(args.id, **fields)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(_fmt_idea(idea, verbose=True))
    return 0


def cmd_spend(args) -> int:
    cfg = _load(args)
    ledger = cfg.ledger()
    ledger.record(args.amount, idea_id=args.idea or "", note=args.note or "")
    print(
        f"logged ${args.amount:.2f}; spent today "
        f"${ledger.spent_today():.2f} / ${cfg.daily_budget_usd:.0f}"
    )
    return 0


def cmd_status(args) -> int:
    cfg = _load(args)
    ideas = cfg.backlog().all()
    counts: dict[str, int] = {}
    for i in ideas:
        counts[str(i.status)] = counts.get(str(i.status), 0) + 1
    spent = cfg.ledger().spent_today()
    print(f"backlog: {len(ideas)} ideas")
    for s in ("proposed", "picked", "running", "done", "dropped"):
        if counts.get(s):
            print(f"  {s:9} {counts[s]}")
    print(f"spend today: ${spent:.2f} / ${cfg.daily_budget_usd:.0f}")
    engine = _engine(cfg, force_emit=True)
    nxt = engine.select()
    print(f"next pick: {nxt.id if nxt else '(none eligible)'}")
    return 0


def cmd_prompt(args) -> int:
    cfg = _load(args)
    engine = _engine(cfg, force_emit=True)
    if args.id:
        idea = cfg.backlog().get(args.id)
        if idea is None:
            print(f"no idea with id {args.id!r}", file=sys.stderr)
            return 1
    else:
        idea = engine.select()
    if idea is None:
        print("nothing eligible to pick.", file=sys.stderr)
        return 1
    if args.mark_running:
        cfg.backlog().update(idea.id, status=Status.RUNNING)
    print(engine.prepare(idea))
    return 0


def cmd_run(args) -> int:
    cfg = _load(args)
    engine = _engine(cfg)
    results = engine.run(max_iters=args.max_iters)
    worked = 0
    for r in results:
        if not r.did_work:
            print(r.message)
            break
        worked += 1
        print(f"• {r.picked.id}: {r.message}")
        if r.result and not r.result.ok and args.verbose:
            print(r.result.error)
    print(f"ran {worked} iteration(s)")
    return 0


def _triage_prompt(cfg):
    from . import triage
    ideas = cfg.backlog().all()
    proposed = [i for i in ideas if i.status in (Status.PROPOSED, Status.PICKED)]
    done = [i for i in ideas if i.status in (Status.DONE, Status.DROPPED)]
    return triage.build_triage_prompt(cfg.context_loader().load(), proposed, done)


def _apply_triage(cfg, obj) -> int:
    from . import triage
    summary = triage.apply_triage(cfg.backlog(), obj.get("rankings", []),
                                  obj.get("drop", []), log_path=cfg.triage_log())
    for iid, prio, reason in summary["updated"]:
        print(f"  prio {prio:>2}  {iid}  — {reason}")
    for iid, reason in summary["dropped"]:
        print(f"  DROP     {iid}  — {reason}")
    if summary["skipped"]:
        print(f"  (skipped unknown ids: {', '.join(filter(None, summary['skipped']))})")
    return 0


def cmd_triage(args) -> int:
    cfg = _load(args)
    if args.apply:
        import json as _json
        raw = sys.stdin.read() if args.apply == "-" else open(args.apply).read()
        return _apply_triage(cfg, _json.loads(raw))
    if args.run:
        from . import triage
        from .runner import ClaudeCliRunner
        runner = ClaudeCliRunner(bin=cfg.claude_bin, model=cfg.model,
                                 extra_args=tuple(cfg.claude_args), timeout=cfg.timeout or None)
        res = runner.run(_triage_prompt(cfg), cwd=cfg.root)
        if not res.ok:
            print(f"triage agent failed: {res.error}", file=sys.stderr)
            return 1
        return _apply_triage(cfg, triage.parse_rankings(res.output))
    # default: print the prompt for an in-harness agent to act on
    print(_triage_prompt(cfg))
    return 0


# --- dashboard (optional, via stagehand) --------------------------------
# Map backlog statuses onto stagehand's colour vocabulary (running/done/failed).
_DASH_STATE = {"proposed": "proposed", "picked": "running", "running": "running",
               "done": "done", "dropped": "failed"}


def _dashboard_monitors(cfg):
    """Project the backlog into stagehand monitor-dicts (one root per idea).

    Each idea is a root; live `*.progress.json` units written by a running
    iteration (parent = idea id) nest underneath. The backlog carries the
    permanent state, so those live files can be ephemeral (cleanup=True)."""
    monitors = []
    for idea in cfg.backlog().all():
        st = _DASH_STATE.get(str(idea.status), str(idea.status))
        extra = {"tier": idea.tier, "prio": idea.priority}
        if idea.strikes:
            extra["strikes"] = idea.strikes
        if idea.cost:
            extra["cost"] = idea.cost
        if idea.links.get("session"):
            extra["session"] = idea.links["session"][:8]  # provenance marker
        monitors.append({
            "name": idea.id, "parent": None, "total": 1,
            "done": 1 if st == "done" else 0, "state": st,
            "started": None, "ended": None, "extra": extra, "meta": {},
        })
    return monitors


def _dashboard_html(cfg, stagehand):
    backlog = cfg.backlog().all()
    spent = cfg.ledger().spent_today()
    done = sum(1 for i in backlog if str(i.status) == "done")
    proj = os.path.basename(os.path.abspath(cfg.root)) or "flywheel"
    title = (f"flywheel · {proj} · ${spent:.0f}/${cfg.daily_budget_usd:.0f} today "
             f"· {done}/{len(backlog)} done")
    live = stagehand.read_monitors(cfg.root)          # live iteration progress
    return stagehand.render_dashboard(
        _dashboard_monitors(cfg) + live, started=time.time(), title=title)


def cmd_dashboard(args) -> int:
    cfg = _load(args)
    try:
        import stagehand
    except ImportError:
        print("flywheel dashboard needs stagehand:\n"
              "  uv tool install --force <flywheel> --with stagehand\n"
              "  (or `pip install` it into the same env)", file=sys.stderr)
        return 1
    out = os.path.join(cfg.root, "status.html")

    def regen():
        with open(out, "w", encoding="utf-8") as f:
            f.write(_dashboard_html(cfg, stagehand))

    regen()
    print(f"wrote {out}", flush=True)
    stop = None
    if args.serve:
        url, stop = stagehand.serve(cfg.root)
        print(url, flush=True)   # flush: under --watch this process stays alive
    if not (args.serve or args.watch):
        return 0
    # keep the process alive, regenerating so the auto-refreshing page is live
    try:
        while True:
            time.sleep(args.interval)
            regen()
    except KeyboardInterrupt:
        pass
    finally:
        if stop:
            stop()
    return 0


def cmd_session(args) -> int:
    from . import provenance

    sid = args.id or provenance.current_session_id()
    if not sid:
        print("no session id (pass --id or run inside Claude Code so "
              "$CLAUDE_CODE_SESSION_ID is set)", file=sys.stderr)
        return 1
    tpath = provenance.transcript_path(sid)
    if args.archive:
        archived = provenance.archive_transcript(sid, args.archive)
        if archived:
            tpath = archived
            print(f"archived transcript -> {archived}")
        else:
            print(f"warning: transcript for {sid} not found to archive", file=sys.stderr)
    if args.idea:
        cfg = _load(args)
        links = {"session": sid}
        if tpath:
            links["transcript"] = tpath
        try:
            cfg.backlog().update(args.idea, links=links)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"recorded session {sid} on {args.idea}")
    else:
        print(f"session: {sid}")
        print(f"transcript: {tpath or '(not found)'}")
    return 0


# --- parser --------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flywheel", description=__doc__)
    p.add_argument("-C", "--config", help="flywheel.toml or a dir to search from")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="scaffold flywheel.toml + queue.md")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add", help="add an idea")
    sp.add_argument("--hypothesis")
    sp.add_argument("--rationale")
    sp.add_argument("--tier", type=int, default=0)
    sp.add_argument("--priority", type=int, default=0)
    sp.add_argument("--cost")
    sp.add_argument("--source")
    sp.add_argument("--notes")
    sp.add_argument("--id")
    sp.add_argument("--json", help="JSON object/array, or '-' for stdin")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("list", help="list ideas")
    sp.add_argument("--status")
    sp.add_argument("--tier", type=int)
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("next", help="show the next pick")
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser("update", help="update an idea")
    sp.add_argument("id")
    sp.add_argument("--status", choices=[s.value for s in Status])
    sp.add_argument("--strikes", type=int)
    sp.add_argument("--priority", type=int)
    sp.add_argument("--tier", type=int)
    sp.add_argument("--cost")
    sp.add_argument("--notes")
    sp.add_argument("--spec")
    sp.add_argument("--postmortem")
    sp.add_argument("--results")
    sp.add_argument("--report", help="path to the run's report (gated on --status done)")
    sp.add_argument("--pr")
    sp.add_argument("--session", help="agent session id (provenance)")
    sp.add_argument("--transcript", help="path to the session transcript")
    sp.add_argument("--no-gate", action="store_true",
                    help="skip the output gate when marking done (override)")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("spend", help="log spend")
    sp.add_argument("amount", type=float)
    sp.add_argument("--idea")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_spend)

    sp = sub.add_parser("status", help="summary")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("prompt", help="print the iteration prompt")
    sp.add_argument("--id", help="prompt for a specific idea (default: next pick)")
    sp.add_argument("--mark-running", action="store_true")
    sp.set_defaults(func=cmd_prompt)

    sp = sub.add_parser("run", help="drive headless iterations")
    sp.add_argument("--max-iters", type=int, default=1)
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("triage", help="re-prioritize the backlog (agent judgment)")
    sp.add_argument("--apply", metavar="FILE", help="apply a rankings JSON ('-' for stdin)")
    sp.add_argument("--run", action="store_true", help="run the triage agent headlessly + apply")
    sp.set_defaults(func=cmd_triage)

    sp = sub.add_parser("dashboard", help="render/serve a live status page (needs stagehand)")
    sp.add_argument("--serve", action="store_true", help="serve behind a Cloudflare tunnel")
    sp.add_argument("--watch", action="store_true", help="keep regenerating the page")
    sp.add_argument("--interval", type=float, default=3.0, help="watch/serve regen seconds")
    sp.set_defaults(func=cmd_dashboard)

    sp = sub.add_parser("session", help="record the agent session (provenance) on an idea")
    sp.add_argument("--idea", help="idea id to attach the session to")
    sp.add_argument("--id", help="session id (default: $CLAUDE_CODE_SESSION_ID)")
    sp.add_argument("--archive", metavar="DIR",
                    help="copy the transcript into DIR for durable provenance")
    sp.set_defaults(func=cmd_session)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
