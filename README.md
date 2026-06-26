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
pip install -e .          # or: pip install git+https://github.com/<you>/flywheel
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
| `flywheel update <id>` | set `--status` / `--strikes` / links (`--spec --postmortem --results --pr`) |
| `flywheel spend <usd>` | log spend against the daily budget |
| `flywheel status` | counts + spend + next pick |
| `flywheel prompt` | print the iteration prompt (in-harness driver) |
| `flywheel run --max-iters N` | drive N headless iterations |

## Guardrails

Even "fully autonomous" keeps a blast-radius bound:

- **Tier gate** — won't pick an idea above `max_tier`.
- **Daily budget** — refuses a pick whose estimate would blow `daily_budget_usd`
  (tracked in `.flywheel/spend.jsonl`; the agent logs spend via `flywheel spend`).
- **3 strikes** — three uninformative runs on one hypothesis auto-drops it
  (escalate or drop), instead of grinding a dead end.

## License

MIT
