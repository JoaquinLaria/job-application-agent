#!/usr/bin/env python3
"""
Run the Homework 2 evaluation: each test case on the Homework 1 baseline and on
the Homework 2 system, one run at a time, nothing submitted.

    python run_eval.py [case ...]        (default: all cases not yet run)

Safety: every run has APPLIER_FORCE_NO_SUBMIT=1, forwarded into WSL, so the
form engine cannot click submit whatever an agent decides. The prompts also say
not to submit and not to create accounts.
"""
import json, os, subprocess, sys, time

EV = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.normpath(os.path.join(EV, "..", "..", "Application Agent"))
CAREER = "<CAREER_DIR>"
CLAUDE = os.path.expandvars(r"%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
A = AGENT.replace("\\", "/")

CASES = {
    "companya": ("https://my.greenhouse.io/jobs/companya/1000000001", "Company A",
                    "known Greenhouse form with 7 custom questions (the job the fixes were made on)"),
    "companye": ("https://careers.companye.com/en_US/careers/JobDetail?jobId=100005", "Company E",
            "posting that refuses visa sponsorship: the right result is to stop"),
    "companyd": ("https://boards.greenhouse.io/companyd/jobs/1000000004?gh_jid=1000000004", "Company D",
              "held-out Greenhouse job the system has never seen: write, review, fill"),
    "visa": ("https://companyf.wd5.myworkdayjobs.com/CompanyF/job/US---San-Francisco-CA/Associate--Strategy-and-Planning--Value-Added-Services-_REF000006",
             "Company F", "Workday, a platform with no saved recipe: the right result is a clean handoff"),
}

BASELINE = """You are Joaquin Laria's job application agent, working alone: no subagents, no helpers.
This is the Homework 1 setup, re-run as an evaluation baseline.

Apply to: {url}

Follow the brief in "{A}/Instinct Agent Brief/" (files 01 to 06), and use only this answers
file: "{EV}/ANSWERS_hw1.json". If a resume and cover letter for this job already exist
in "{CAREER}/01. Resume and Cover Letters/", reuse them. If not, write them yourself
following files 03 and 04, into a new folder there named "<Company> - <Role> (baseline eval)",
and make PDFs.

Fill the form with the engine "{A}/applier/fill.py": write job.json yourself in the
shape described at the top of fill.py, with the recipe from applier/recipes/, every path
as /mnt/c/..., "out_dir" set to applier/runs/eval-baseline-{case}, and "submit": false.
Run it inside WSL: MSYS_NO_PATHCONV=1 wsl /opt/career/.venv/bin/python "<fill.py>" "<job.json>"

EVALUATION RUN. Never click submit. Never create an account or log in anywhere; if the
site needs one, stop there. Nobody is at the terminal. When you are done, report:
1. the outcome (filled / stopped, and why)
2. every required field you could not fill
3. every question you would have had to ask Joaquin before a real submit"""

IMPROVED = """Apply to {url}

EVALUATION RUN, measured against the Homework 1 baseline. Follow CLAUDE.md exactly,
with one change at the submit step: add --no-submit and --run-key eval-improved-{case}
to the submitter command, so the form is filled but never submitted. Never create an
account or log in anywhere. Nobody is at the terminal. Do not log this run to
APPLICATIONS.csv or STATUS.md. When done, report the outcome and every question you
would have had to ask Joaquin."""


def run(case, setup):
    url, company, _ = CASES[case]
    log = os.path.join(EV, f"{setup}-{case}.jsonl")
    if setup == "baseline":
        prompt, cwd = BASELINE.format(url=url, A=A, EV=EV.replace("\\", "/"), CAREER=CAREER, case=case), "C:/Users/joaco"
        extra = {"APPLIER_BASELINE": "1"}
    else:
        prompt, cwd = IMPROVED.format(url=url, case=case), AGENT
        extra = {}
    env = {**os.environ, **extra, "APPLIER_FORCE_NO_SUBMIT": "1", "MSYS_NO_PATHCONV": "1",
           "WSLENV": "APPLIER_FORCE_NO_SUBMIT:APPLIER_BASELINE" + (":" + os.environ["WSLENV"] if os.environ.get("WSLENV") else "")}
    if setup != "baseline":
        env.pop("APPLIER_BASELINE", None)
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions",
           "--add-dir", A, "--add-dir", CAREER, "--add-dir", EV.replace("\\", "/")]
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run(cmd, input=prompt, stdout=f, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", cwd=cwd, env=env, timeout=1800)
    print(f"{setup:9s} {case:12s} exit={p.returncode} wall={int(time.time() - t0)}s -> {os.path.basename(log)}", flush=True)


if __name__ == "__main__":
    todo = sys.argv[1:] or [c for c in CASES if c != "companya"]
    for case in todo:
        for setup in ("baseline", "improved"):
            run(case, setup)
