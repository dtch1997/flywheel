# flywheel

An autonomous **experiment loop**. One iteration:

1. **Load context** — north stars, recent results, the backlog.
2. **Pick** the top experiment off the backlog (respecting guardrails).
3. **Run** it — the agent does the science (spec → run → writeup → reproducibility).
4. **Brainstorm** follow-up experiments and **file them back onto the backlog**.

…so the next iteration has something to pick up. That feedback edge — ideas
flowing back onto the queue — is the flywheel.

The library is the *scaffolding* around an agent: it owns the backlog, the
context assembly, the guardrails, and the loop driver. The agent (Claude Code,
in-harness or headless) does the experiment.

## Install

```bash
pip install -e .          # or: pip install git+ssh://git@github.com/dtch1997/flywheel.git
# on this box the CLI is installed as a tool: uv tool install ./repos/flywheel
```

## Quick start

```bash
cd my-research-repo
flywheel init                       # writes flywheel.toml + queue.md
flywheel add --hypothesis "Does chain-of-thought reduce negation neglect?" \
             --rationale "cheap, untested implication of the QE result" \
             --tier 0 --cost '$3' --priority 5
flywheel status                     # backlog + today's spend + next pick
flywheel run --max-iters 1          # drive one headless iteration
```

Or drive it from inside a Claude Code session with `/loop`:

```
/loop "run the next flywheel experiment: flywheel prompt | then follow it"
```

`flywheel prompt` prints the fully-assembled iteration prompt (context + the
selected idea + the protocol + bookkeeping commands) for the surrounding agent
to perform.

## The pieces (all swappable)

| Seam | Default | Swap to |
|---|---|---|
| **Backlog** (`Backlog`) | `MarkdownBacklog` — a hand-editable `queue.md` | JSONL / SQLite (implement the Protocol) |
| **Context** (`ContextLoader`) | declarative `[[sources]]` in config | any file/glob/recent-glob set |
| **Guardrails** (`Guardrails`) | tier gate · `$50`/day budget · 3 strikes | tune in `[guardrails]` |
| **Runner** (`AgentRunner`) | `ClaudeCliRunner` (headless) / `EmitRunner` (in-harness) | any callable agent |

Storage is deliberately behind the `Backlog` Protocol — markdown today, but
nothing else in flywheel knows that.

## Configuration (`flywheel.toml`)

`flywheel init` scaffolds a commented file. Highlights:

```toml
backlog_path = "queue.md"

[[sources]]                 # what the agent reads as context each iteration
kind = "file"
label = "north stars"
path = "NORTH_STARS.md"

[guardrails]
max_tier = 2                # highest cost tier pickable unattended
daily_budget_usd = 50.0     # the real rail for fully-autonomous runs
max_strikes = 3             # uninformative runs before an idea is dropped

[runner]
kind = "claude"             # headless; or "emit" for in-harness /loop
args = ["--permission-mode", "acceptEdits"]   # your permission posture

[prompt]
protocol_file = "EXPERIMENT_PROTOCOL.md"      # override the built-in protocol
```

## CLI

| Command | Does |
|---|---|
| `flywheel init` | scaffold `flywheel.toml` + `queue.md` |
| `flywheel add` | add an idea (`--hypothesis … --tier … --cost …`, or `--json -`) |
| `flywheel list [-v]` | show the backlog (filter `--status` / `--tier`) |
| `flywheel next` | show the next pick (and why others are blocked) |
| `flywheel update <id>` | set `--status` / `--strikes` / links (`--spec --postmortem --results --report --pr --session --transcript`); `--status done` is gated on a valid report (`--no-gate` to override) |
| `flywheel spend <usd>` | log spend against the daily budget |
| `flywheel status` | counts + spend + next pick |
| `flywheel prompt` | print the iteration prompt (in-harness driver) |
| `flywheel run --max-iters N` | drive N headless iterations |
| `flywheel triage [--run \| --apply -]` | an agent re-prioritizes the backlog |
| `flywheel dashboard [--serve] [--watch]` | live status page via stagehand (optional) |
| `flywheel session --idea <id> [--archive DIR]` | record the agent session (provenance) on an idea |

## Triage — judgment, not just FIFO

`select()` pops the highest-priority idea, but priority is a static integer set
when an idea was filed — so the head of the queue drifts out of date as results
come in. **Triage** is the judgment layer: an agent reads the north stars + the
whole backlog + what's already been learned, and **rewrites priorities** (and
drops stale/subsumed ideas) so the next pick reflects current taste. Judgment
(the agent) stays separate from mechanism (`select`, deterministic).

```bash
flywheel triage                 # print the triage prompt (in-harness); the agent
                                # returns {"rankings":[...],"drop":[...]} JSON ...
flywheel triage --apply -       # ... which you pipe back in to apply + log it
flywheel triage --run           # or: run the triage agent headlessly and apply
```

The triage agent is told to reward **replicating a surprising-but-unconfirmed
result** over piling up new hypotheses, and to weigh novelty, info-per-dollar,
and north-star fit. Each pass is logged to `.flywheel/triage.jsonl`. Drive the
loop as **triage → `next` → run** instead of blindly popping the queue.

## Output gate — a run must leave something behind

The loop's *input* is an idea; its *output* should be a durable, reviewable
report. Without enforcement, an idea can be marked `done` with no artifact — the
flywheel turns but leaves nothing behind. The **output gate** closes that gap:
`flywheel update --status done` is refused until the idea has a valid report.

The done transition is the single choke point both run modes pass through (the
headless runner and the in-harness agent both close out via `update`), so the
gate covers both. By default the report is validated against the
[`reportly`](https://github.com/dtch1997/reportly) standard (finding-as-H1,
TL;DR / Setup / Result / Reproduce, figures-exist, provenance footer):

```bash
flywheel update exp --status done --report runs/exp/report.md   # lints first
# refused → prints the reportly issues; the idea stays 'running'
flywheel update exp --status done --report runs/exp/report.md --no-gate  # override
```

Configure it in `[output]` (`flywheel init` scaffolds this):

```toml
[output]
require_report = true
validator      = "reportly"   # "reportly" (lint) | "none" (exists-only)
level          = "error"      # reportly fail threshold: "error" | "warn"
report_link    = "report"
```

`validator = "reportly"` needs reportly installed (`pip install '.[reportly]'`, or
`uv tool install --with reportly`); it degrades to a clear error, not a crash, if
absent. The gate is a swappable seam (`OutputGate` in `flywheel/output.py`) — a
project with a different report standard implements it and wires it in, mirroring
the `Backlog`/`Guardrails`/`Runner` seams. Like everything else: mechanism
(deterministic validation) stays separate from judgment (the agent's write-up).

## Session provenance

The backlog records *what* was decided; the session transcript records *why*. So
each iteration can carry the agent session behind it as a link, and reviewing an
experiment opens its full decision trace.

- **Headless** (`flywheel run`): the `ClaudeCliRunner` runs with
  `--output-format json`, parses `session_id` + `total_cost_usd`, and the engine
  records the `session` link and auto-logs the cost as spend — no extra step.
- **In-harness** (`/loop`): the agent records its own session with
  `flywheel session --idea <id> --archive <run_dir>`, which reads
  `$CLAUDE_CODE_SESSION_ID`, attaches the `session` link, and copies the
  transcript (`~/.claude/projects/**/<id>.jsonl`) next to the experiment for
  durable provenance.

```python
from flywheel import current_session_id, transcript_path, archive_transcript
```

## Guardrails

Even "fully autonomous" keeps a blast-radius bound:

- **Tier gate** — won't pick an idea above `max_tier`.
- **Daily budget** — refuses a pick whose estimate would blow `daily_budget_usd`
  (tracked in `.flywheel/spend.jsonl`; the agent logs spend via `flywheel spend`).
- **3 strikes** — three uninformative runs on one hypothesis auto-drops it
  (escalate or drop), instead of grinding a dead end.

## License

MIT
