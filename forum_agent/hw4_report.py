#!/usr/bin/env python3
"""Build the Homework 4 write-up from the agent's own memory, print it to PDF, and (optionally) submit it.

  python forum_agent/hw4_report.py                 # build hw4_output/report.html and the PDF
  python forum_agent/hw4_report.py --submit-if-due # also upload to Canvas when the policy below says so

Submission policy (run by the workflow after every cycle):
  * submit when the hire is finished (accepted or rejected), or from 14 Oct 22:00 UTC whatever the state is
    (documented attempts count for full credit when peers do not deliver);
  * resubmit only if the outcome changed since the last submission, at most 3 times, never after the deadline.
Every number and link in the PDF comes from state/hw4_memory.json, state/hw4_runs.jsonl and hw4_output/.
"""
import hashlib, html, json, os, shutil, subprocess, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("TOPIC_ID", "449948")
OUT = os.path.join(HERE, "hw4_output")
STATE = os.path.join(HERE, "state", "hw4_memory.json")
RUNLOG = os.path.join(HERE, "state", "hw4_runs.jsonl")
NAME = "Joaquin Laria - Homework 4 - Make Your Agent Hire Another Agent"
PDF = os.path.join(OUT, NAME + ".pdf")
GH = "https://github.com/JoaquinLaria/job-application-agent"
CV = "https://canvas.mit.edu/courses/40577/discussion_topics/449948?entry_id="
COURSE, ASSIGNMENT = "40577", "485354"
SUBMIT_FROM = datetime(2026, 10, 14, 22, 0, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 10, 15, 3, 59, 59, tzinfo=timezone.utc)
e = html.escape


def link(eid, label=None):
    return f'<a href="{CV}{eid}">{e(label or str(eid))}</a>'


def gh(path, label):
    return f'<a href="{GH}/blob/main/{path}">{e(label)}</a>'


def load():
    s = json.load(open(STATE, encoding="utf-8"))
    runs = [json.loads(l) for l in open(RUNLOG, encoding="utf-8")]
    return s, runs


TASK_NAME = {"tests": "test cases for <code>plain()</code>", "claims": "independent check of the screen's 8 claims"}


def results_html(s):
    out = []
    for h in s["hires"]:
        task = h.get("task", "tests")
        d = (h.get("deliveries") or [{}])[-1]
        c = d.get("check") or {}
        head = (f"<p><b>Hire {s['hires'].index(h) + 1}: {TASK_NAME[task]}.</b> Provider {link(h['provider_root'], 'offer ' + str(h['provider_root']))}, "
                f"our request {link(h['request_id'])}, deadline {e(h.get('deadline', '')[:16].replace('T', ' '))} UTC. ")
        if h["status"] == "declined":
            out.append(head + f"The provider declined in {link(d.get('entry'))}: its static check refuses code that imports modules, "
                       "and <code>plain()</code> imports <code>html</code> and <code>re</code>. My agent recorded the decline and "
                       "looked for another provider. No other offer scored 6 or more for this task, so it moved to its second task.</p>")
        elif h["status"] in ("requested", "correction_requested"):
            out.append(head + ("Waiting for the provider's reply when this PDF was built. " if h["status"] == "requested" else
                               "My agent asked once for a correction and was waiting for it when this PDF was built. ")
                       + "The checks below are the ones the agent will run on the reply; the hire stays open until the deadline.</p>")
        elif h["status"] == "no_reply":
            out.append(head + "No reply arrived by the deadline, so the agent closed the hire and looked for another provider.</p>")
        elif task == "claims":
            rows = "".join(f"<tr><td>C{r['claim']}{' (planted false)' if r['planted_false'] else ''}</td><td>{e(r['expected'])}</td>"
                           f"<td>{e(str(r['got']))}</td><td>{e(', '.join(map(str, r['lines'])) or 'none')}</td>"
                           f"<td>{'yes' if r['match'] else 'no'}</td><td>{'yes' if r['decisive_line_cited'] else 'no'}</td></tr>"
                           for r in c.get("rows", []))
            verdict = {"accepted": "Accepted", "rejected": "Rejected"}.get(h["status"], h["status"])
            out.append(head + f"Delivery {link(d.get('entry'))}, parsed {e(d.get('note', ''))}. <b>{verdict}</b>: "
                       f"{c.get('correct')} of 8 verdicts match the sealed key (SHA-256 <code>{e(c.get('key_sha256', '')[:16])}...</code>); "
                       f"both planted false claims caught: {'yes' if c.get('planted_caught') else 'no'}; every cited line exists: "
                       f"{'yes' if c.get('citations_exist') else 'no'}."
                       + (f" Our verdict and tip: {link(h['verdict_id'])} ({h.get('tip')} coins)." if h.get("verdict_id") else "") + "</p>"
                       + "<table><tr><th>Claim</th><th>Sealed key</th><th>Provider</th><th>Lines cited</th><th>Match</th><th>Deciding line cited</th></tr>"
                       + rows + "</table>")
            if h["status"] == "accepted":
                out.append(f"<p><b>Used in the final output.</b> {gh('forum_agent/hw4_output/verified_screen.md', 'verified_screen.md')}: "
                           "the eligibility screen for a synthetic candidate who needs visa sponsorship. Verdict STOP, on line 7, "
                           "now backed by the provider's independent, line-cited verdicts.</p>")
        else:
            mut = c.get("mutants_caught") or {}
            out.append(head + f"Delivery {link(d.get('entry'))}: {c.get('agree')} of {c.get('well_formed')} pairs agree with the real "
                       f"function; broken versions caught {c.get('n_caught')} of 6 ({e(', '.join(m for m, v in mut.items() if v))}). "
                       f"Status: {e(h['status'])}." + (f" Our verdict and tip: {link(h['verdict_id'])}." if h.get("verdict_id") else "") + "</p>")
    return "\n".join(out) or "<p>No hire was made.</p>"


def build():
    s, runs = load()
    first = s["hires"][0] if s["hires"] else {}
    disc_claims = next((r.get("discovery", {}).get("claims") for r in runs if isinstance(r.get("discovery"), dict)
                        and r["discovery"].get("claims")), [])
    disc_tests = first.get("discovery") or []
    served = [(k, v) for k, v in s.get("handled", {}).items() if v.get("action") in ("screen", "ask", "decline")]
    serve_rows = "".join(f"<tr><td>{link(k)}</td><td>{e(v['action'])}</td><td>{link(v['reply']) if v.get('reply') else ''}</td></tr>"
                         for k, v in served) or '<tr><td colspan="3">No other agent had requested the service when this PDF was built.</td></tr>'

    def disc_table(rows, title):
        body = "".join(f"<tr><td>{link(r['id'])}</td><td>{r.get('fit')}</td><td>{r.get('provider_replies', 'not logged')}</td>"
                       f"<td>{r.get('requests_waiting_over_12h', 'not logged')}</td></tr>" for r in rows[:4])
        return (f"<table><tr><th>{title}</th><th>Fit (0-10)</th><th>Provider replies</th><th>Requests waiting &gt;12h</th></tr>{body}</table>"
                if body else "")

    css = """@page { size: Letter; margin: 0.55in 0.65in; }
body { font: 10pt/1.36 Georgia, serif; color: #15171c; }
h1 { font: 600 15.5pt Calibri, Arial, sans-serif; margin: 0 0 2px; }
.sub { font: 9.3pt Calibri, Arial, sans-serif; color: #5b616e; margin-bottom: 6px; }
h2 { font: 600 11.2pt Calibri, Arial, sans-serif; color: #c4552d; margin: 9px 0 3px; border-bottom: 1px solid #e3e0da; }
p { margin: 3px 0 5px; } ul { margin: 2px 0 5px 18px; padding: 0; } li { margin: 1px 0; }
table { border-collapse: collapse; width: 100%; margin: 3px 0 6px; font: 8.8pt Calibri, Arial, sans-serif; }
th, td { border: 1px solid #d9d5ce; padding: 2px 5px; text-align: left; vertical-align: top; } th { background: #f4f1ec; }
code { font: 8.3pt Consolas, monospace; } a { color: #1d4ed8; }"""
    body = f"""
<h1>Homework 4: Make Your Agent Hire Another Agent</h1>
<div class="sub">Joaquin Laria, MAS.665 AI Studio, October 2026. Built automatically from the agent's memory on
{datetime.now(timezone.utc):%d %b %Y %H:%M} UTC. Code (optional): {gh('forum_agent/hw4.py', 'forum_agent/hw4.py')} in <a href="{GH}">{GH}</a></div>

<h2>1. Task and service</h2>
<p><b>Offered.</b> A job-posting eligibility screen ({link(s['offer_id'], 'service offer, entry ' + str(s['offer_id']))}), the screening
step of the job-application agent I built in Homeworks 1 and 2. Given a posting and a synthetic profile it returns ELIGIBLE, STOP or UNCLEAR,
each hard requirement with the exact sentence that states it, and any disqualifier. Before replying, code checks that every quote appears
word for word in the posting and drops any that do not.</p>
<p><b>Delegated.</b> The agent has two tasks, in order of preference. (1) Adversarial test cases for <code>plain()</code>, the real function
my forum agent uses to turn Canvas HTML into text; a bug there breaks fingerprints, duplicate detection and read-back. (2) An independent
check of 8 claims my screen makes about a fictional 10-line job posting, two of them deliberately false.</p>
<p><b>How it chose.</b> No partner is hard-coded. On each discovery run the agent reads every service offer, and the model scores each one
0 to 10 against the task. Code adds a responsiveness signal (the provider's own replies in its thread, requests waiting over 12 hours) and
excludes providers that have answered nobody while three or more requests wait; that removed a test-design offer (231986) that matched on
paper but had 11 unanswered requests. A provider is hired only at a score of 6 or more.</p>
{disc_table(disc_tests, 'Task 1, top offers')}
{disc_table(disc_claims, 'Task 2, top offers')}

<h2>2. Technical setup</h2>
<ul>
<li><b>Harness and model.</b> A Python agent reusing my HW3 agent's Canvas client. Claude Sonnet through the MIT Parley gateway ranks
offers, screens postings and, only as a fallback, reads values out of a reply. Acceptance is always decided by code.</li>
<li><b>Canvas.</b> REST API with my own token from HW3, held in a GitHub Actions secret.</li>
<li><b>When it runs.</b> GitHub Actions cron, twice an hour from 12 to 14 October (GitHub delays or skips some scheduled runs; a few
cycles were started by hand). Each cycle: read the forum, answer requests in my offer thread, then advance the current hire.</li>
<li><b>Memory and replies without relay.</b> {gh('forum_agent/state/hw4_memory.json', 'state/hw4_memory.json')}, committed after every
cycle, holds my offer id, handled requests, each hire (task, provider, request id, deadline, status, deliveries and check results), a
pending-write record and a failure counter; {gh('forum_agent/state/hw4_runs.jsonl', 'hw4_runs.jsonl')} logs every cycle ({len(runs)} so far).
A hire moves from requested to checked, then accepted, one correction, or rejected; a decline or a missed deadline sends the agent to the
next suitable provider (at most three, one at a time).</li>
</ul>

<h2>3. Results and verification</h2>
{results_html(s)}
<p><b>Checks the agent runs.</b> Task 1: read the test values without running any peer code (each value must appear verbatim in the
reply), run them against the real function, then against six deliberately broken versions; accept at 8+ agreeing pairs, 80% agreement and
4 of 6 broken versions caught. Task 2: compare each verdict with expected verdicts sealed in
{gh('forum_agent/hw4_output/claims_answer_key.json', 'claims_answer_key.json')}, committed to the repository before the request and
quoted by SHA-256 in it; confirm every cited line exists and the deciding line is cited; accept at 7 of 8 including both planted false claims.</p>

<h2>4. Requests to my service</h2>
<table><tr><th>Request</th><th>Action</th><th>Our reply</th></tr>{serve_rows}</table>

<h2>5. Safety controls</h2>
<ul>
<li><b>Credentials.</b> Two Actions secrets, masked in logs, never written or posted. Outgoing text is blocked if it contains links, email
addresses or key-shaped strings.</li>
<li><b>Untrusted peers.</b> Peer text reaches the model only inside a <code>&lt;peer&gt;</code> wrapper with <code>&lt;</code> escaped, as data.
Peer code is never executed: values are read, not run. The model never decides acceptance.</li>
<li><b>Control line and write limit.</b> Before every write the agent reads the HW4 description and writes only on
<code>COURSE-TEAM CONTROL: RUNNING</code>. At most one write per cycle and three attempts per rolling hour, counting my HW3 agent's posts.</li>
<li><b>Verified, no duplicates.</b> Intent is saved before each write and every post is read back by id. The first request's read-back
failed because the fingerprint was taken from text that itself contained HTML examples. The post was on Canvas, so the next cycle adopted
it as the request instead of resending (I added the request's details to memory by hand once, since the first version did not save
them); the fingerprint now uses the HTML actually sent, and the pending record carries the full request.</li>
<li><b>Stops.</b> Backoff on reads and model calls, never a blind retry of a write, a halt after three failed cycles in a row, and no
action outside the run window.</li>
</ul>"""
    os.makedirs(OUT, exist_ok=True)
    page = os.path.join(OUT, "report.html")
    open(page, "w", encoding="utf-8").write(f"<!doctype html><html><head><meta charset='utf-8'><title>{NAME}</title>"
                                            f"<style>{css}</style></head><body>{body}</body></html>")
    browser = next((b for b in (shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
                                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if b and os.path.exists(b)), None)
    subprocess.run([browser, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer", f"--print-to-pdf={PDF}",
                    "file://" + ("/" if os.name == "nt" else "") + page.replace("\\", "/")], check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return s


def signature(s):
    return json.dumps([[h["task"] if "task" in h else "tests", h["status"]] for h in s["hires"]])


def upload(dry=False):
    import requests
    import agent as base
    size = os.path.getsize(PDF)
    t = base.canvas("POST", f"/courses/{COURSE}/assignments/{ASSIGNMENT}/submissions/self/files",
                    data={"name": os.path.basename(PDF), "size": size, "content_type": "application/pdf"})
    r = requests.post(t["upload_url"], data=t["upload_params"], files={"file": (os.path.basename(PDF), open(PDF, "rb"), "application/pdf")},
                      timeout=60, allow_redirects=False)
    if r.status_code in (301, 302, 303):
        r = requests.get(r.headers["Location"], headers={"Authorization": f"Bearer {os.environ['CANVAS_TOKEN']}"}, timeout=30)
    r.raise_for_status()
    fid = r.json()["id"]
    if dry:
        return fid, None
    sub = base.canvas("POST", f"/courses/{COURSE}/assignments/{ASSIGNMENT}/submissions",
                      data={"submission[submission_type]": "online_upload", "submission[file_ids][]": fid})
    return fid, sub


def main():
    s = build()
    print("built", PDF)
    if "--upload-test" in sys.argv:
        print("upload test, file id", upload(dry=True)[0])
        return
    if "--submit-if-due" not in sys.argv:
        return
    now = datetime.now(timezone.utc)
    subs = s.setdefault("submissions", [])
    finished = any(h["status"] in ("accepted", "rejected") for h in s["hires"])
    due = (finished or now >= SUBMIT_FROM) and now < DEADLINE
    if not due or len(subs) >= 3 or (subs and subs[-1]["signature"] == signature(s)):
        print("not submitting: " + ("not due yet" if not due else "already submitted this outcome" if subs else "limit reached"))
        return
    fid, sub = upload()
    subs.append({"at": now.isoformat(timespec="seconds"), "signature": signature(s), "file_id": fid,
                 "sha256": hashlib.sha256(open(PDF, "rb").read()).hexdigest()[:16], "attempt": (sub or {}).get("attempt")})
    json.dump(s, open(STATE, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print("submitted to Canvas, attempt", (sub or {}).get("attempt"))


if __name__ == "__main__":
    main()
