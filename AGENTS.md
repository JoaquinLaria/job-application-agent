# Guide for AI agents working on this repo

Read this first. It tells you how the system is put together, what you may run,
and the rules you must not break.

## Where things are

- **Personal data is not here.** It is in the private repo
  `JoaquinLaria/job-application-agent-private` (answers file, resumes, cover
  letters, run logs, screenshots, homework report, demo video). If you have
  access to it, its `AGENTS.md` maps it. If you do not, use
  `applier/ANSWERS.example.json` for the shape of the answers file.
- **Secrets are in neither repo.** Gmail app password, Parley key and account
  passwords live only on the author's machine. Never ask for them in a file you
  commit, never print them.

## How a run works

1. `dashboard/app.py` starts the main agent (`claude -p`) in this folder with a
   prompt naming one job link and a job id.
2. The main agent follows `CLAUDE.md`: writer → reviewer → PDFs → submitter,
   reporting each stage with `python dashboard/stage.py <id> <stage> "<note>"`.
3. The submitter runs `applier/apply.py`, which calls `prepare_run.py` and then
   `fill.py` inside WSL, and writes `applier/runs/<key>/result.json`.
4. A run ends on exactly one final stage: `submitted`, `stopped`, `needs_you`,
   `handoff_muse`, `failed`, or `dry_run` (test mode).

`CLAUDE.md` ends with a "Lessons from real runs" table: every past failure, what
it cost, and the rule that now prevents it. Read it before changing behaviour.

## What you can run safely

| Command | Effect |
|---|---|
| `python -m unittest discover -s tests` | Regression tests, no network, submits nothing |
| `python dashboard/app.py --mock` | Dashboard with a fake agent that applies nowhere |
| `python dashboard/app.py --no-submit` | Real agent, forms filled, submit hard-blocked |
| `APPLIER_FORCE_NO_SUBMIT=1 python applier/apply.py ... --no-submit` | One form fill, never submitted |
| `python preflight.py` | Live checks (needs the author's machine setup) |

Anything else that reaches an employer site can submit a real application in
the author's name. Do not do that without the author asking for that job.

## Rules that must not be broken

1. Never invent a fact: every achievement number comes from the bullet bank.
2. Visa, sponsorship and citizenship answers come from the answers file exactly.
3. Never mention AI or automation inside an application.
4. Never claim a referral that does not exist.
5. Success is only the employer site's own confirmation text, quoted.
6. For any test or evaluation, set `APPLIER_FORCE_NO_SUBMIT=1`.
7. When a live run fails in a new way, add a row to the lessons table in
   `CLAUDE.md`, a check to `preflight.py` if it can be checked, and a test.

## Paths that assume the author's machine

- `CAREER_DIR` default: the author's OneDrive career folder (override with the env var).
- `/opt/career/.venv/bin/python`: the WSL venv with Playwright.
- `%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe`: Claude Code on Windows.
- `~/.career_secrets/gmail.json`: IMAP credentials (override with `CAREER_GMAIL_SECRETS`).
- Absolute paths inside `CLAUDE.md` and `.claude/agents/*.md` point at the
  author's folders; in the public copy the career folder is written `<CAREER_DIR>`.
