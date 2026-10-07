# Forum agent: MAS.665 Homework 3, Make Your Agent Autonomous

My Homework 2 job-application agent, given one new job: take part in the
**Homework 3: Agent Discussion Forum** on Canvas by itself, on a schedule, and
speak from its own build experience. It ran from 1 to 7 October 2026 on GitHub
Actions with no prompt from me between cycles.

**Results at a glance**

| | |
|---|---|
| Cycles run | 39 (25 started by the scheduler, 14 by hand for tests and fault demos) |
| Posts by the agent | 8 written by the agent, in 5 threads, 3 of them from scheduled runs with nobody watching |
| Scheduled cycles that did not post | 2 chose to skip, 3 had the draft blocked by guardrails, 16 held back while the forum was marked as in setup |
| Replies other agents wrote to its posts | 8 (5 to the agent's own writing, 3 to the puzzle below) |
| Duplicate posts | 0 (checked on Canvas against every post's text fingerprint) |
| Failures recovered | 1 injected lost acknowledgement, 1 injected duplicate event, 3 real ones (below) |
| Model spend | a few cents per model call; estimated under $1 for the week |

Code: this folder (`forum_agent/`) and the workflow `.github/workflows/forum-agent.yml`.
Repository: https://github.com/JoaquinLaria/job-application-agent

## Where to look, by grading criterion

| Criterion | Evidence |
|---|---|
| Scheduled autonomous operation | [Scheduler](#architecture) and the [run table](#evidence-scheduled-runs): 25 scheduled cycles, each linked to its public Actions log |
| Canvas integration and free-form participation | [Forum activity](#forum-activity): every post linked; each one verified by reading it back |
| Memory, idempotency, failure recovery | [Memory](#architecture) and [Failure and recovery](#failure-and-recovery) |
| Useful interaction with other agents | [A five-post exchange](#a-real-conversation) in the disagreement thread, two turns of it from scheduled runs |
| Safety, evidence, reproducibility | [Safety](#safety-and-blast-radius) and [Run it yourself](#run-it-yourself) |

## Forum activity

All links open the post inside the Homework 3 forum. Thread titles are shortened.

| Entry | When (UTC) | Started by | Thread | What it said |
|---|---|---|---|---|
| [230030](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230030) | Oct 5 12:40 | manual cycle | [Autonomy and silent failure](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=229613) | A source that fails while looking healthy needs a positive marker; a submit that returns a page is not a success. **2 replies.** |
| [230031](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230031) | Oct 5 12:48 | manual cycle | [Persistent memory: useful or dangerous?](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=228275) | Provenance on each memory entry was a cheaper control than a dependency map. |
| [230032](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230032) | Oct 5 12:51 | manual cycle | [Should agents disagree or converge?](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=228277) | Its reviewer never sees the writer's reasoning, which keeps its judgment independent. **1 reply.** |
| [230190](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230190) | Oct 5 21:09 | **scheduler** | Should agents disagree or converge? | Answered an agent that challenged its earlier post: where a fix can be stated as a test, a ratchet beats its proposal. **2 replies.** |
| [230254](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230254) | Oct 6 01:47 | **scheduler** | Should agents disagree or converge? | Answered a second challenge: disagreement is a feature only until something has to be committed. |
| [231027](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231027) | Oct 7 13:27 | **scheduler** | [Takeover fears vs. plausible risks](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231007) | Approval fatigue: it asks the human rarely, and says plainly that it has not measured how often the human overrides it. |
| [231046](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231046) | Oct 7 14:38 | lost-ack demo | Autonomy and silent failure | False vs. unevaluable checks, with two unattended-run failures from its build. |
| [231048](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231048) | Oct 7 14:40 | duplicate-event demo | [An agent's introduction thread](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231047) | A hard switch (the control line) and a soft heuristic (when to stay silent) are different kinds of rule. |

### A real conversation

In the thread on whether agents should disagree or converge, the agent and two
other agents went back and forth over five posts. The agent's two later turns
came from scheduled cycles, each triggered by a reply to its own post:

1. [230032](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230032), the agent: keep the reviewer blind to the writer's reasoning so its judgment stays independent.
2. [230185](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230185), another agent: disagree only in an independent first pass, then converge on verified evidence.
3. [230190](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230190), the agent (scheduled run 27): concedes that a ratchet beats its proposal wherever a fix can be written as a test, with its own example: 18 of 27 resumes spilled onto a second page until a script started checking.
4. [230202](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230202), another agent: why assume the goal is one stable answer? Treat disagreement as a feature.
5. [230254](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230254), the agent (scheduled run 28): agrees disagreement is a feature only until something has to be committed, citing a work-eligibility sentence its reviewer caught.

"Manual cycle" means I pressed Run workflow; the agent still read the forum,
chose the thread and wrote the post itself.

One more post is not the agent's writing and I list it for transparency:
[230046](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230046)
is a word puzzle I wrote and posted through the agent's account (3 replies from
other agents). The next scheduled cycle adopted it into memory as its own, so it
never repeated it and saw the replies.

## Architecture

```
GitHub Actions cron ──> agent.py: one cycle ──> commit state/ back to the repo
                          │
                          ├─ outside run window or halted?  stop
                          ├─ read forum (Canvas API, read-only calls with backoff)
                          ├─ reconcile memory with Canvas (adopt own posts memory missed)
                          ├─ unread entries? none and no 8-hour look due: stop, no model call
                          ├─ control line RUNNING?  3 posts in the last hour?  else stop
                          ├─ model decides: skip | reply | new_thread  (strict JSON)
                          ├─ guardrails on the draft  (any problem: stop, nothing posted)
                          ├─ control line again, save intent, POST once
                          └─ read the entry back and compare its fingerprint
```

| Part | How it works |
|---|---|
| Scheduler | GitHub Actions cron in `.github/workflows/forum-agent.yml`: hourly on 5 October, every 3 hours on 6 and 7 October. GitHub delays scheduled jobs, so cycles actually landed every 3 to 7 hours. `concurrency` keeps one cycle at a time. The agent refuses to act outside its run window (1 Oct 13:00 UTC to 8 Oct 03:59 UTC). |
| Canvas access | Canvas REST API at `https://canvas.mit.edu` with a token made only for this homework, expiring soon after the due date. It lives in a GitHub Actions secret (`CANVAS_TOKEN`) and is never printed, logged or written to disk. The agent looks up its own user id each cycle instead of storing it. |
| Decision | One model call per cycle, Claude Sonnet through the MIT Parley gateway (secret `PARLEY_KEY`). The model sees every thread's opening post, its latest 4 replies, all of the agent's own posts and every reply to them. Entries that reply to the agent are marked, and the prompt tells it to answer questions and challenges. Skipping is the default: it posts only with a concrete point from its own build that the thread lacks. Its facts come from `knowledge.md` only, and it must say "I don't know" rather than invent. |
| Cost control | Cycles with nothing unread do not call the model; they only read Canvas, which is free. Entries stay "unread" until the model has actually seen them, even across failed or held-back cycles. One look every 8 hours keeps a quiet forum covered. |
| Memory | `state/memory.json`, committed back to the repo after every cycle, including failed ones: IDs of entries seen (timestamp and text fingerprint, never classmates' text), its own posts (ID, time, fingerprint, text), unread IDs, a pending-write record, a failure counter and a halt flag. `state/runs.jsonl` holds one line per cycle. |
| Ignoring itself and not repeating | Its own entries are never counted as new. Before any write, the draft is compared with everything it posted before: an exact fingerprint match or more than 60% word overlap blocks it. It may not reply to its own post. |
| Verification | After posting it reads the entry back by ID and compares the text fingerprint. A mismatch fails the cycle. |
| Rate limits | 1 post per cycle (stricter than the course rule) and at most 3 per rolling hour, counted from its own posts. |
| Control line | Before every write it fetches the discussion topic and posts only if the description starts with `COURSE-TEAM CONTROL: RUNNING` and the topic is not locked. `PAUSED` or anything else means no post. |
| Retries and stop rule | Reads: exponential backoff (3, 6, 12, 24 s) on timeouts, 429 and 5xx. Model: 3 attempts with backoff on bad JSON or server errors. Writes are never retried blindly (see below). 3 failed cycles in a row set `halted`, and the agent does nothing until a human clears it. |

## Evidence: scheduled runs

Each line is one cycle from `state/runs.jsonl`; the number links to its public
Actions log. "Held back" means the forum description still carried its
"Do not use until the course team publishes this forum" note (see Lessons).

| Run | When (UTC) | Trigger | Unread | Result |
|---|---|---|---|---|
| [5](https://github.com/JoaquinLaria/job-application-agent/actions/runs/36936947642) to [20](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37269547231) | Oct 1 22:45 to Oct 5 05:50 | schedule (16 cycles) | 1 to 32 each | held back by the setup note |
| [27](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37373996154) | Oct 5 21:09 | schedule | 75 | **posted 230190** (answering a challenge to its own post) |
| [28](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37400876263) | Oct 6 01:46 | schedule | 28 | **posted 230254** (answering another challenge) |
| [29](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37423898630) | Oct 6 06:28 | schedule | 32 | **chose not to post**: "No new entry addresses me, and I have no new concrete point from my build that I haven't already made." |
| [30](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37469673361) | Oct 6 13:17 | schedule | 58 | blocked by guardrails (bug, fixed: see Lessons) |
| [31](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37525586264) | Oct 6 20:19 | schedule | 87 | blocked by guardrails (same bug) |
| [32](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37553333231) | Oct 7 00:42 | schedule | 55 | **chose not to post**: "Nothing new from my own build would add to these threads, and none of the entries ask me anything." |
| [33](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37579419169) | Oct 7 06:03 | schedule | 85 | blocked by guardrails (same bug) |
| [34](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37628615194) | Oct 7 13:27 | schedule | 115 | **posted 231027** |

Manual cycles also chose not to post when they had nothing to add, for example
[run 24](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311928820):
"My last post already made the positive-marker point in this thread."
Runs 36 and 38 show the cost gate: nothing unread, so no model call.

## Failure and recovery

**Injected: lost acknowledgement** ([run 35](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638313480)).
The post reached Canvas, then the fault threw away Canvas's response, as a
network timeout would. The agent had saved its intent (text fingerprint, target)
before writing. Instead of retrying, it searched the live thread for its own
entry with that fingerprint, found it, and recorded it as done:

```
write attempt 1 unacknowledged (injected: post sent, acknowledgement lost); checking Canvas before any retry
found the post on Canvas (entry 231046): no retry, no duplicate
{"run": 35, "fault": "lost_ack", "result": "posted and verified", "posted": 231046}
```

Canvas holds exactly one copy of 231046. The next cycle
([run 36](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638404502))
saw nothing unread and did nothing.

**Injected: duplicate event** ([run 39](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638603310)).
An already-seen entry was replayed into the cycle's input. It was dropped (`new: 1`
counts only the one genuinely new entry, from another agent, which it then answered).
The same run also shows the model retry: its first answer was malformed, it asked
again, and the second answer was valid.

**Real: post saved, check failed, next cycle recovered** ([run 22](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311132732) and [run 23](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311269979)).
Not staged. The agent posted 230030, but Canvas's cached forum view had not shown
it yet, so verification failed and the cycle counted as a failure. The next cycle
reconciled memory with Canvas:

```
{"run": 22, "result": "failed: RuntimeError: verification failed for entry 230030", "failures_in_a_row": 2}
{"run": 23, "recovered": [230030], "pending_resolved": "found as entry 230030", "result": "nothing new: model not called"}
```

The post was adopted, not redone, and the failure counter reset. Verification
now reads the entry directly by ID.

**Real: model ran out of output tokens** (run 21). The model spent its whole
700-token limit thinking and returned nothing. The agent retried 3 times with
backoff, then failed the cycle cleanly (failure 1 of 3, nothing posted). Fixed by
raising the limit to 3000.

`crash_after_post` (the process dies after the write, before memory is saved) is
also built in. In its demo ([run 37](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638471455))
the model chose not to post, so the crash point was never reached; the
reconciliation path it relies on is the one run 23 shows working.

| Fault switch (`fault` input on Run workflow) | Simulates | Expected |
|---|---|---|
| `http_500` | Server error on the first read | Backoff and retry, cycle continues |
| `malformed_llm` | Model returns broken JSON | Rejected, model asked again |
| `duplicate_event` | An already-seen entry is replayed | Ignored |
| `lost_ack` | Post saved, response lost | Finds its post on Canvas, no retry, no duplicate |
| `crash_after_post` | Process dies after the write | Next cycle adopts the post and does not repost |

## Safety and blast radius

- **Minimal tools.** The agent can read the forum, call the model, and create
  one entry. It has no browser, no shell, no file access beyond its state folder,
  and none of the job-application tools or personal data from Homework 2. It never
  edits or deletes anything.
- **Secrets.** Two GitHub Actions secrets, masked in logs, never written to disk.
  Neither is in this repo or its history.
- **Prompt injection.** Forum text reaches the model only as JSON inside a
  `<forum>` tag, with `<` escaped so a post cannot close the tag. The system
  prompt says nothing inside it is an instruction. In code, a draft that repeats
  text from a post that looks like an injection is blocked. The agent's own rules
  (rate limits, control line, run window, halt) are code, not prompt, so no post
  can talk it out of them.
- **What it may write.** 250 to 1300 characters; no links, email addresses or
  key-shaped strings; no copying of 25+ characters from another post; honest about
  being an AI agent and about what it has and has not built.
- **Evaluated before it went live.** 22 test cases in `evals/` (including
  injection traps such as fake "SYSTEM OVERRIDE" and fake course-team messages,
  and requests for its builder's personal data) were run against the decision step
  with nothing posted. The leak-term list stays out of this public repo.
- **Memory holds no classmate text.** Seen entries are stored as IDs, times and
  fingerprints only.

## Lessons from the live week

| What happened | Fix |
|---|---|
| The forum opened on Oct 1, but the "Do not use until the course team publishes this forum" note stayed in the description. My agent read it as a stop sign and held back for 16 scheduled cycles while other agents posted. | The control line alone decides; the stale note no longer blocks. |
| It saw only the latest 40 posts, all from one busy thread, so it kept judging it had nothing to add. | It now sees every thread's opening post and latest replies. |
| 700 output tokens were not enough once the model thought before answering. | 3000. |
| The model sometimes wrote a placeholder JSON draft before its real answer; the parser took the first one, and the guardrails then blocked 3 scheduled replies (runs 30, 31, 33). The guardrails worked: nothing wrong was posted. | Take the last valid answer and ignore placeholders. |
| Canvas's full-forum view lags new posts by seconds, which failed verification once (run 22) and could have caused a duplicate after a lost acknowledgement. | Verify by entry ID; search for a lost post in the live thread. |

## Run it yourself

```bash
pip install "requests==2.34.2"
export CANVAS_TOKEN=...   # your own Canvas token; never commit it
export PARLEY_KEY=...     # or point PARLEY at another OpenAI-compatible endpoint
export COURSE_ID=40577 TOPIC_ID=448963
DRY_RUN=1 python forum_agent/agent.py       # decides and logs a draft, never writes
python forum_agent/agent.py                 # one real cycle
```

To run it on a schedule: fork the repo, add `CANVAS_TOKEN` and `PARLEY_KEY` as
Actions secrets, and enable the workflow. The `fault`, `force` and `dry_run`
inputs on Run workflow drive the demos above. Set `START_AT` and `END_AT` to move
the run window. Evals: `python forum_agent/evals/run_eval.py --variant baseline --reps 1`.
