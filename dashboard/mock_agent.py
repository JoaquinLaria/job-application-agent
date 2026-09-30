#!/usr/bin/env python3
"""
Stand-in for the main agent, for testing the dashboard without applying anywhere.
Reads the prompt from stdin like `claude -p`, walks the stages, prints stream-json.

The outcome depends on the link, so every path can be tested:
    link contains "stop"     -> stopped at screening
    link contains "captcha"  -> needs_you while submitting
    link contains "workday"  -> handoff_muse
    link contains "fail"     -> reviewer fails once, then passes
    anything else            -> submitted

A reply resume (prompt starts "Resuming job ...") is answered by picking up at
needs_you and reporting submitted, so the resume path can be tested too.
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
prompt = sys.stdin.read()
job_id = re.search(r"Job id: (\S+)", prompt).group(1)
m = re.search(r"(?:Apply to|Resuming job \S+ for) (\S+)", prompt)
url = m.group(1).lower() if m else ""
is_resume = prompt.startswith("Resuming job")


def say(text):
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}), flush=True)


def tool(name):
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": {}}]}}), flush=True)


def stage(s, note=""):
    subprocess.run([sys.executable, os.path.join(HERE, "stage.py"), job_id, s, note], check=True,
                   stdout=subprocess.DEVNULL)


if is_resume:
    say("Resuming with the reply. Continuing from where the run stopped.")
    time.sleep(1)
    stage("submitting", "resubmitting the form with the reply applied")
    time.sleep(1)
    stage("submitted", '"Thank you for applying. Your application has been received."')
    say("Done.")
    print(json.dumps({"type": "result", "subtype": "success", "result": "Done."}), flush=True)
    sys.exit(0)

say("Starting. Handing the link to the writer.")
tool("Agent")
stage("screening", "writer is reading the posting")
time.sleep(2)
if "stop" in url:
    stage("stopped", '"will not be providing visa sponsorship"')
    say("Stopped: the posting refuses sponsorship.")
    sys.exit(0)
stage("files_written", "resume and cover letter built")
time.sleep(2)
stage("in_review", "reviewer round 1")
tool("Agent")
time.sleep(2)
if "fail" in url:
    stage("review_failed", "invented number in resume bullet 2")
    say("Reviewer failed round 1. Sending the fix to the writer.")
    time.sleep(2)
    stage("in_review", "reviewer round 2")
    time.sleep(2)
stage("reviewer_approved", "PASS, 0 hard failures")
time.sleep(1)
stage("submitting", "applier filling the Greenhouse form")
tool("Bash")
time.sleep(3)
if "captcha" in url:
    stage("needs_you", "CAPTCHA on the submit page")
elif "workday" in url:
    stage("handoff_muse", "HANDOFF - Muse.md written")
else:
    stage("submitted", '"Thank you for applying. Your application has been received."')
say("Done.")
print(json.dumps({"type": "result", "subtype": "success", "result": "Done."}), flush=True)
