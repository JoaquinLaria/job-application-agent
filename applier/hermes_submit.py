#!/usr/bin/env python3
"""
Hand the submission step to Hermes Agent (running in WSL, on Parley) and
report back in the same shape as apply.py.

    python hermes_submit.py <url> <resume_pdf> <cover_pdf> --company "Company A" [--no-submit]

Used by the main agent when ../submitter.json says "submitter": "hermes".
Switching back to Claude's applier subagent is that one line; nothing here
needs to change.

The result is read from the run folder's result.json, which apply.py writes
itself. Hermes' own reply is kept for the log but is never the evidence.
"""
import argparse, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_run  # noqa: E402

CONF = os.path.join(os.path.dirname(HERE), "submitter.json")
HERMES = "~/.local/bin/hermes"
WSL_PY = "/opt/career/.venv/bin/python"

BRIEF = """You are the submission agent for Joaquin Laria's job applications.
The documents are already written and approved. Your only job is to submit this
one application and report what happened. Work in the current directory.

Run exactly this command, once:

{cmd}

It fills the form, reads the emailed security code from Gmail by itself, submits,
and prints one JSON object. It can take up to 10 minutes; wait for it.

Then read the JSON "status" and reply with exactly one line:
- "submitted"            -> SUBMITTED: <the "confirmation" text>
- "filled_not_submitted" -> DRY RUN OK (this was a test with --no-submit)
- anything else          -> NEEDS_HUMAN: <status>, <problems>, <labels of unknown_fields>

Rules:
- Run the command at most twice, and the second time only if the first failed
  on something transient (timeout, browser crash). Never loop.
- Do not edit any file. Do not answer form questions yourself.
- Never change a visa, sponsorship or citizenship answer, never solve a CAPTCHA.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("resume_pdf")
    ap.add_argument("cover_pdf")
    ap.add_argument("--company", required=True)
    ap.add_argument("--run-key")
    ap.add_argument("--no-submit", action="store_true")
    a = ap.parse_args()

    conf = json.load(open(CONF, encoding="utf-8"))
    key = a.run_key or re.sub(r"[^a-z0-9]+", "-", a.company.lower()).strip("-")
    run_dir = os.path.join(HERE, "runs", key)
    os.makedirs(run_dir, exist_ok=True)
    result_path = os.path.join(run_dir, "result.json")
    if os.path.exists(result_path):
        os.remove(result_path)  # never report a previous run's result

    q = lambda s: '"' + s.replace('"', '\\"') + '"'
    cmd = " ".join([WSL_PY, "apply.py", q(a.url), q(prepare_run.to_wsl(a.resume_pdf)),
                    q(prepare_run.to_wsl(a.cover_pdf)), "--company", q(a.company), "--run-key", key]
                   + (["--no-submit"] if a.no_submit else []))
    brief_path = os.path.join(run_dir, "hermes_brief.txt")
    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(BRIEF.format(cmd=cmd))

    budget = int(conf.get("hermes_run_budget_seconds", 720))
    hermes_cmd = (f'cd {q(prepare_run.to_wsl(HERE))} && {HERMES} chat --query-file {q(prepare_run.to_wsl(brief_path))} '
                  f'--oneshot -Q --yolo -m {q(conf.get("hermes_model", "claude-haiku-4-5"))} '
                  f'--max-turns {int(conf.get("hermes_max_turns", 8))} --run-budget {budget}')
    t0 = time.time()
    try:
        r = subprocess.run(["wsl", "bash", "-lc", hermes_cmd], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=budget + 60,
                           env={**os.environ, "MSYS_NO_PATHCONV": "1"})
        reply = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        reply, err = "", f"hermes exceeded {budget + 60}s and was stopped"
    with open(os.path.join(run_dir, "hermes_reply.txt"), "w", encoding="utf-8") as f:
        f.write(reply + ("\n--- stderr ---\n" + err if err else ""))

    if os.path.exists(result_path):
        out = json.load(open(result_path, encoding="utf-8"))
    else:
        out = {"status": "failed", "confirmation": "",
               "problems": ["Hermes finished but apply.py wrote no result.json",
                            (reply or err)[-400:]]}
    out.update({"submitter": "hermes", "hermes_model": conf.get("hermes_model"),
                "hermes_seconds": int(time.time() - t0),
                "hermes_said": reply.splitlines()[-1][:300] if reply else ""})
    print(json.dumps(out, ensure_ascii=False))
    ok = out["status"] == "submitted" or (a.no_submit and out["status"] == "filled_not_submitted")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
