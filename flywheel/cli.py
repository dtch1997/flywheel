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
"""

from __future__ import annotations

import argparse
import json
import sys
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
    for k in ("spec", "postmortem", "results", "pr"):
        v = getattr(args, k)
        if v is not None:
            links[k] = v
    if links:
        fields["links"] = links
    if not fields:
        print("nothing to update", file=sys.stderr)
        return 2
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
    sp.add_argument("--pr")
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

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
