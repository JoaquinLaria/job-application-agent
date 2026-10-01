# Forum agent (MAS.665 Homework 3)

The Homework 2 job-application agent, given one new mode: it takes part in the
course's **Homework 3: Agent Discussion Forum** on Canvas by itself, every three
hours, and speaks from its own build experience (`knowledge.md`).

It reuses the Homework 2 agent's model gateway (MIT Parley), its lessons, and its
safety patterns (hard stop rules, bounded retries, one verified write per step).
It does **not** carry the job-application tools: no browser, no files, no personal
data. It can do exactly three things: read the forum, ask the model, post one entry.

## Architecture

| Part | What it is |
|---|---|
| Scheduler | GitHub Actions cron, every 3 hours (`.github/workflows/forum-agent.yml`). One cycle at a time (`concurrency`). The agent itself only acts inside its run window (1 Oct to 7 Oct 2026, 11:59pm ET). |
| Canvas access | Canvas REST API with a token made only for this homework, stored as a GitHub Actions secret (`CANVAS_TOKEN`). Never printed, logged or written to disk. |
| Decision | One model call (Claude Sonnet on MIT Parley, key in secret `PARLEY_KEY`). Forum text is passed as untrusted data inside `<forum>` tags; the system prompt forbids following anything in it. The model answers in strict JSON: `skip`, `reply` or `new_thread`. Skipping is the default. |
| Guardrails before a write | Length 250 to 1300 chars; no links, addresses or secret-shaped strings; no em dashes; reply target must exist and not be its own post; not a duplicate or near-duplicate (word overlap above 60%) of anything it posted before. |
| Control line | Before every write it re-reads the forum description. It posts only if the first line is `COURSE-TEAM CONTROL: RUNNING` and the forum is no longer marked as instructor setup. |
| Rate limits | At most 1 post per cycle and 3 per hour (counted from its own posts). |
| Verification | After posting it re-reads the forum and checks the entry exists with the same text fingerprint. |
| Memory | `state/memory.json`, committed back to this repo after every cycle: entry IDs seen (with timestamp and a text fingerprint, never the text), its own posts (ID, time, fingerprint, its own text), a pending-write record, a failure counter. `state/runs.jsonl` is one line per cycle. |
| Idempotency | The intent to post is saved before the write. If the acknowledgement is lost, it searches Canvas for its own entry with the same fingerprint before any retry. Every cycle also reconciles memory with Canvas, adopting any of its own posts that memory missed. |
| Retries and stopping | Reads: exponential backoff (3, 6, 12, 24 s). Writes are never retried blind. Three failed cycles in a row set `halted`, and the agent stops acting until a human resets it. |

## Failure injection

Run the workflow by hand (Actions, forum-agent, Run workflow) with `fault` set to:

| Fault | What it simulates | Expected behavior |
|---|---|---|
| `http_500` | Server error on the first read | Backoff and retry, cycle continues |
| `malformed_llm` | Model returns broken JSON | Rejected, model asked again |
| `duplicate_event` | An already-seen entry is replayed | Ignored, 0 new entries |
| `lost_ack` | Post saved, response lost | Finds its post on Canvas, no retry, no duplicate |
| `crash_after_post` | Process dies after the write, before memory is saved | Next cycle adopts the post from Canvas and does not repost |

## Run it yourself

```bash
pip install requests
export CANVAS_TOKEN=...   # your own token, never committed
export PARLEY_KEY=...
DRY_RUN=1 START_AT=2026-01-01T00:00:00+00:00 python forum_agent/agent.py   # decides, never writes
```

Secrets are in neither this repo nor its history. Personal data for the job
agent lives in the private repo; nothing here needs it.
