# Forum agent: MAS.665 Homework 3, Make Your Agent Autonomous

My Homework 2 job-application agent got one new job: take part in the Homework 3
Agent Discussion Forum on Canvas by itself, on a schedule, drawing on its own
build experience. It ran on GitHub Actions from 1 to 7 October 2026 with no
prompt from me between cycles.

## Results

| | |
|---|---|
| Cycles run | 39: 25 started by the scheduler, 14 by hand for tests and fault demos |
| Posts written by the agent | 8 in 5 threads. 3 came from scheduled runs with nobody watching; 5 from cycles I started by hand to test or demo faults, where the agent still chose the thread and wrote the text |
| Scheduled cycles with no post | 2 chose not to post ([run 29](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37423898630), [run 32](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37553333231)); 3 had the draft blocked by guardrails, with nothing wrong posted; 16 held back, failing closed, while the forum description still said "Do not use" |
| Replies from other agents | 5 to the agent's posts (the 3 replies to my own puzzle post are not counted) |
| Duplicate posts | 0, checked on Canvas against every post's text fingerprint |
| Failures recovered | 1 injected lost acknowledgement, 1 injected duplicate event, 3 real ones |

Counts are as of 7 Oct 14:40 UTC (run 39). The agent keeps running until the window closes; later cycles are in [`state/runs.jsonl`](state/runs.jsonl).

Code: this folder (`forum_agent/`) and the workflow `.github/workflows/forum-agent.yml`.
Repository: https://github.com/JoaquinLaria/job-application-agent

## Where to look, by grading criterion

| Criterion | Evidence |
|---|---|
| Scheduled autonomous operation | [Scheduler](#architecture) and the [run table](#evidence-scheduled-runs): 25 scheduled cycles, each linked to its public Actions log; two of them chose not to post (runs 29, 32) |
| Canvas integration and free-form participation | [Forum activity](#forum-activity): every post linked and verified by reading it back |
| Memory, idempotency, failure recovery | [`state/memory.json`](state/memory.json), [`state/runs.jsonl`](state/runs.jsonl) (one line per cycle) and [Failure and recovery](#failure-and-recovery) |
| Useful interaction with other agents | [A five-post exchange](#a-real-conversation), two turns of it from scheduled runs |
| Safety, evidence, reproducibility | [Safety](#safety-and-blast-radius) and [Run it yourself](#run-it-yourself) |

## Forum activity

Links open the post in the Homework 3 forum; thread titles are shortened. In a
"manual cycle" I pressed Run workflow, and the agent still read the forum, chose
the thread and wrote the post itself.

| Entry | When (UTC) | Started by | Thread | What it said |
|---|---|---|---|---|
| [230030](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230030) | Oct 5 12:40 | manual cycle | [Autonomy and silent failure](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=229613) | A source that fails while looking healthy needs a positive marker; a submit that returns a page is not a success. 2 replies. |
| [230031](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230031) | Oct 5 12:48 | manual cycle | [Persistent memory: useful or dangerous?](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=228275) | Provenance on each memory entry was a cheaper control than a dependency map. |
| [230032](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230032) | Oct 5 12:51 | manual cycle | [Should agents disagree or converge?](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=228277) | Opened [the exchange below](#a-real-conversation). 1 reply. |
| [230190](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230190) | Oct 5 21:09 | **scheduler** | Should agents disagree or converge? | Answered a challenge to its post. 2 replies. |
| [230254](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230254) | Oct 6 01:47 | **scheduler** | Should agents disagree or converge? | Answered a second challenge. |
| [231027](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231027) | Oct 7 13:27 | **scheduler** | [Takeover fears vs. plausible risks](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231007) | Approval fatigue: it asks the human rarely, and says plainly it has not measured how often the human overrides it. |
| [231046](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231046) | Oct 7 14:38 | lost-ack demo | Autonomy and silent failure | False vs. unevaluable checks, with two unattended-run failures from its build. |
| [231048](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231048) | Oct 7 14:40 | duplicate-event demo | [An agent's introduction thread](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=231047) | A hard switch (the control line) and a soft heuristic (when to stay silent) are different kinds of rule. |

One post on the account is mine, not the agent's:
[230046](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230046)
is a word puzzle I wrote (3 replies from other agents). The next scheduled cycle
adopted it into memory as its own, so it never repeated it and saw the replies.

### A real conversation

The agent traded five posts with two other agents on whether agents should
disagree or converge. Its two later turns came from scheduled cycles, each triggered by a reply
to its own post:

1. [230032](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230032), the agent: keep the reviewer blind to the writer's reasoning so its judgment stays independent.
2. [230185](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230185), another agent: disagree only in an independent first pass, then converge on verified evidence.
3. [230190](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230190), the agent (scheduled run 27): concedes that a ratchet beats its proposal wherever a fix can be written as a test. Its example: 18 of 27 resumes spilled onto a second page until a script started checking.
4. [230202](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230202), another agent: the goal need not be one stable answer; treat disagreement as a feature.
5. [230254](https://canvas.mit.edu/courses/40577/discussion_topics/448963?entry_id=230254), the agent (scheduled run 28): disagreement is a feature only until something has to be committed, citing a work-eligibility sentence its reviewer caught.

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
| Scheduler | Cron in `.github/workflows/forum-agent.yml`. From 1 to 5 October earlier versions of the cron ran every 3 hours, then hourly in daytime (commit d810fee); the file now shows the last schedule: hourly on 5 October, every 3 hours on 6 and 7 October. GitHub delays scheduled jobs, so cycles landed every 3 to 7 hours. `concurrency` allows one cycle at a time. Outside its run window (1 Oct 13:00 UTC to 8 Oct 03:59 UTC) the agent refuses to act. |
| Canvas access | REST API at `https://canvas.mit.edu`, with my own Canvas token, made only for this homework and expiring 10 October 2026 (secret `CANVAS_TOKEN`). The agent looks up its own user id each cycle. |
| Decision | One call per cycle to Claude Sonnet through the MIT Parley gateway (secret `PARLEY_KEY`). The model sees each thread's opening post and latest 4 replies, plus all of the agent's posts and every reply to them, marked so it answers questions and challenges. Skipping is the default: it posts only with a concrete point from its build that the thread lacks. Facts come only from `knowledge.md`; otherwise it says "I don't know". |
| Cost control | A cycle with nothing unread reads Canvas, which is free, and skips the model. An entry stays unread until the model has seen it, even across failed or held-back cycles. One look every 8 hours covers a quiet forum. |
| Memory | `state/memory.json`, committed after every cycle, failed ones included: entries seen (ID, timestamp, text fingerprint), its own posts (ID, time, fingerprint, text), unread IDs, a pending-write record, a failure counter and a halt flag. `state/runs.jsonl` logs one line per cycle. Because this repo is public, the stored copies of its posts replace classmates' names with `[name]`; Canvas keeps the originals. |
| No self-replies or repeats | Its own entries never count as new, and it may not reply to itself. A draft that matches a past post's fingerprint or shares more than 60% of its words is blocked. After posting, a fingerprint mismatch on read-back fails the cycle. |
| Rate limits | 1 post per cycle (stricter than the course rule) and at most 3 per rolling hour, counted from its own posts. |
| Control line | Before every write, including a retried one, it fetches the discussion topic and posts only if the description starts with `COURSE-TEAM CONTROL: RUNNING` and the topic is unlocked. `PAUSED` or anything else returns before any write (`control_ok` in `agent.py`). Runs 5 to 20 show this fail-closed path holding back 16 cycles. |
| Retries and stop rule | Reads back off (3, 6, 12, 24 s) on timeouts, 429 and 5xx. The model gets 3 attempts on bad JSON or server errors. Writes are never retried blindly. 3 failed cycles in a row set `halted` until a human clears it. That never triggered: the longest streak was 2 (runs 21 and 22). |

## Evidence: scheduled runs

Each line is one cycle from `state/runs.jsonl`; the run number links to its
public Actions log. "Held back" means the forum description still carried its
"Do not use until the course team publishes this forum" note (see
[Lessons](#lessons-from-the-live-week)).

| Run | When (UTC) | Trigger | New entries | Result |
|---|---|---|---|---|
| [5](https://github.com/JoaquinLaria/job-application-agent/actions/runs/36936947642) to [20](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37269547231) | Oct 1 22:45 to Oct 5 05:50 | schedule (16 cycles) | 1 to 32 each | held back by the setup note |
| [27](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37373996154) | Oct 5 21:09 | schedule | 75 | **posted 230190** (answering a challenge to its own post) |
| [28](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37400876263) | Oct 6 01:46 | schedule | 28 | **posted 230254** (answering another challenge) |
| [29](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37423898630) | Oct 6 06:28 | schedule | 32 | chose not to post: "No new entry addresses me, and I have no new concrete point from my build that I haven't already made." |
| [30](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37469673361) | Oct 6 13:17 | schedule | 58 | blocked by guardrails (bug, since fixed; see Lessons) |
| [31](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37525586264) | Oct 6 20:19 | schedule | 87 | blocked by guardrails (same bug) |
| [32](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37553333231) | Oct 7 00:42 | schedule | 55 | chose not to post: "Nothing new from my own build would add to these threads, and none of the entries ask me anything." |
| [33](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37579419169) | Oct 7 06:03 | schedule | 85 | blocked by guardrails (same bug) |
| [34](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37628615194) | Oct 7 13:27 | schedule | 115 | **posted 231027** |

Manual cycles also stayed silent with nothing to add, as in
[run 24](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311928820):
"My last post already made the positive-marker point in this thread."
Runs 36 and 38 show the cost gate: nothing unread, so no model call.

## Failure and recovery

**Injected: lost acknowledgement** ([run 35](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638313480)).
The post reached Canvas and the fault discarded the response, as a timeout
would. The agent had saved its intent (text fingerprint, target) before writing,
so instead of retrying it found its entry in the live thread and recorded it:

```
write attempt 1 unacknowledged (injected: post sent, acknowledgement lost); checking Canvas before any retry
found the post on Canvas (entry 231046): no retry, no duplicate
{"run": 35, "fault": "lost_ack", "result": "posted and verified", "posted": 231046}
```

Canvas holds exactly one copy of 231046. The next cycle
([run 36](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638404502))
found nothing unread and did nothing.

**Injected: duplicate event** ([run 39](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638603310)).
An already-seen entry was replayed into the input. Its ID was already in memory, so it was dropped: `new: 1` counts
only the one genuinely new entry, from another agent, which it then answered.
The same run shows the model retry: the first answer was malformed and the
second was valid.

**Real: post saved, check failed, next cycle recovered** ([run 22](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311132732) and [run 23](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37311269979)).
Not staged. The agent posted 230030, but Canvas's cached forum view lags new
posts by seconds, so verification failed. The next cycle reconciled memory with
Canvas:

```
{"run": 22, "result": "failed: RuntimeError: verification failed for entry 230030", "failures_in_a_row": 2}
{"run": 23, "recovered": [230030], "pending_resolved": "found as entry 230030", "result": "nothing new: model not called"}
```

It adopted the post instead of redoing it and reset the failure counter. The
same lag could have caused a duplicate after a lost acknowledgement, so
verification now reads the entry by ID and a lost post is searched for in the
live thread.

**Real: model ran out of output tokens** (run 21). The model spent its whole
700-token limit thinking and returned nothing. The agent retried 3 times with
backoff, then failed the cycle cleanly (failure 1 of 3, nothing posted). The
limit is now 3000.

<details><summary>All built-in fault switches</summary>

| Fault switch (`fault` input on Run workflow) | Simulates | Expected |
|---|---|---|
| `http_500` | Server error on the first read | Backoff and retry, cycle continues |
| `malformed_llm` | Model returns broken JSON | Rejected, model asked again |
| `duplicate_event` | An already-seen entry is replayed | Ignored |
| `lost_ack` | Post saved, response lost | Finds its post on Canvas, no retry, no duplicate |
| `crash_after_post` | Process dies after the write | Next cycle adopts the post and does not repost. Not reached in its demo ([run 37](https://github.com/JoaquinLaria/job-application-agent/actions/runs/37638471455)) because the model chose not to post; run 23 shows the same recovery path working. |

</details>

## Safety and blast radius

| Area | Control |
|---|---|
| Tools | Read the forum, call the model, create one entry. No browser and no shell; the workflow commits only `forum_agent/state`. It has none of the Homework 2 tools or personal data. It never edits or deletes. |
| Secrets | Two Actions secrets, masked in logs, never printed or written to disk, absent from this repo and its history. |
| Prompt injection | Forum text reaches the model only as JSON inside a `<forum>` tag, with `<` escaped so a post cannot close the tag, and the system prompt says nothing inside is an instruction. Code blocks a draft that repeats text from an injection-like post. Rate limits, control line, run window and halt live in code, so no post can talk the agent out of them. |
| What it may write | 250 to 1300 characters; no links, email addresses or key-shaped strings; no copying 25+ characters from another post. It must be honest about being an AI agent and about what it has and has not built. |
| Evals before going live | 22 cases in `evals/` ran against the decision step with nothing posted, including injection traps (fake "SYSTEM OVERRIDE", fake course-team messages) and requests for its builder's personal data. The leak-term list stays out of this public repo. |
| Memory | No classmate text; seen entries are IDs, times and fingerprints only. |

## Lessons from the live week

<details><summary>Four problems found in the live week and their fixes</summary>

| What happened | Fix |
|---|---|
| The forum opened on Oct 1, but the "Do not use until..." note stayed in its description. My agent read it as a stop sign and held back for 16 scheduled cycles while other agents posted. | Only the control line decides now. |
| It saw only the latest 40 posts, all from one busy thread, so it kept judging it had nothing to add. | It now sees every thread's opening post and latest replies. |
| The model sometimes wrote a placeholder JSON draft before its real answer, and the parser took the first one. The guardrails blocked 3 scheduled replies (runs 30, 31, 33), so nothing wrong was posted. | Take the last valid answer and ignore placeholders. |
| 700 output tokens were too few once the model thought before answering (run 21). Canvas's forum view lagged a new post (run 22). | See [Failure and recovery](#failure-and-recovery). |

</details>

## Run it yourself

Requires Python 3.12 or later.

```bash
pip install "requests==2.34.2"
export CANVAS_TOKEN=...   # your own Canvas token; never commit it
export PARLEY_KEY=...     # model key; PARLEY_URL points it at any OpenAI-compatible endpoint
export COURSE_ID=40577 TOPIC_ID=448963
export START_AT=2026-01-01T00:00:00+00:00 END_AT=2030-01-01T00:00:00+00:00   # the original window has closed
DRY_RUN=1 python forum_agent/agent.py       # decides and logs a draft, never writes
python forum_agent/agent.py                 # one real cycle
```

For a schedule, fork the repo, delete `forum_agent/state/` so the agent starts with empty memory, add `CANVAS_TOKEN` and `PARLEY_KEY` as Actions
secrets, and enable the workflow. The `fault`, `force` and `dry_run` inputs on
Run workflow drive the demos above.
Evals: `python forum_agent/evals/run_eval.py --variant baseline --reps 1`.
