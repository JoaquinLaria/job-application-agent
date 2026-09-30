#!/usr/bin/env python3
"""
Application queue dashboard. Local only.

    python app.py            real runs: each job starts the main agent (Claude Code)
    python app.py --mock     test runs: mock_agent.py walks the stages, applies nowhere

Open http://127.0.0.1:5057

Jobs run one at a time, in queue order, and at most MAX_RUNS per server session,
matching the five-per-session rule in CLAUDE.md.
"""
import json, os, re, subprocess, sys, threading, time, uuid

from flask import Flask, jsonify, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_ROOT = os.path.dirname(HERE)  # the folder holding CLAUDE.md and .claude/agents
CAREER = os.environ.get("CAREER_DIR", "<CAREER_DIR>")
JOBS = os.path.join(HERE, "jobs.json")
STAGES = os.path.join(HERE, "stages")
LOGS = os.path.join(HERE, "logs")
CLAUDE = os.path.expandvars(r"%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe")
MOCK = "--mock" in sys.argv
NO_SUBMIT = "--no-submit" in sys.argv
NO_SUBMIT_LINE = """

TEST RUN. Run every step, including the submitter, but add --no-submit to the
submitter command so the form is filled and never submitted. The form engine is
also hard-blocked from clicking submit in this mode. Report the final stage as
dry_run with the note "test run: form filled, not submitted". Do not log this run
to APPLICATIONS.csv or STATUS.md."""
MAX_RUNS = 5
PORT = 5057
SUBMITTER_CONF = os.path.join(AGENT_ROOT, "submitter.json")
# Models each submitter may use. Hermes calls Parley (MIT's gateway), so these
# are Parley model ids. Claude's applier subagent takes Claude Code aliases.
SUBMITTER_MODELS = {
    "hermes": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "gpt-5.6-luna"],
    "claude": ["haiku", "sonnet", "opus"],
}
FINAL = {"submitted", "stopped", "needs_you", "handoff_muse", "failed", "dry_run"}

os.makedirs(STAGES, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)

app = Flask(__name__, static_folder=None)
lock = threading.Lock()
state = {"proc": None, "job": None, "runs": 0, "jobs_run": set()}


# ------------------------------------------------------------------ storage ---
def load():
    if not os.path.exists(JOBS):
        return []
    with open(JOBS, encoding="utf-8") as f:
        return json.load(f)


def save(jobs):
    tmp = JOBS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=1)
    os.replace(tmp, JOBS)


def stages_of(job_id):
    p = os.path.join(STAGES, f"{job_id}.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def activity_of(job_id, limit=60):
    """Turn the agent's stream-json log into short readable lines."""
    p = os.path.join(LOGS, f"{job_id}.jsonl")
    if not os.path.exists(p):
        return []
    lines = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") == "text" and c.get("text", "").strip():
                        lines.append({"kind": "say", "text": c["text"].strip()[:400]})
                    elif c.get("type") == "tool_use":
                        inp = c.get("input") or {}
                        hint = inp.get("description") or inp.get("subagent_type") or inp.get("command") or ""
                        lines.append({"kind": "tool", "text": f"{c.get('name')}: {str(hint)[:160]}"})
            elif ev.get("type") == "result":
                lines.append({"kind": "result", "text": str(ev.get("result", ""))[:600]})
    return lines[-limit:]


def load_submitter():
    try:
        with open(SUBMITTER_CONF, encoding="utf-8") as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    who = conf.get("submitter") if conf.get("submitter") in SUBMITTER_MODELS else "claude"
    model = conf.get(f"{who}_model") or SUBMITTER_MODELS[who][0]
    return conf, who, model


def find(jobs, job_id):
    for j in jobs:
        if j["id"] == job_id:
            return j
    return None


# ------------------------------------------------------------------- runner ---
PROMPT = """Apply to {url}
Job id: {id}

This run was started from the application dashboard. Nobody is watching the
terminal. Report every stage with
  python "dashboard/stage.py" {id} <stage> "<note>"
as the Dashboard section of CLAUDE.md describes. Where you would ask Joaquin,
report needs_you with the exact question in the note and end the run."""

RESUME_PROMPT = """Resuming job {id} for {url} after a reply from Joaquin.
Job id: {id}

This is not a fresh start. Work on this job has already reached the stage
below, and the CAREER job folder may already hold a job description, a
resume, and a cover letter. Look at what already exists before redoing any
step: do not re-screen, re-write, or re-review something already finished.

Stage history so far:
{history}

Joaquin's reply to the question that stopped the run:
"{reply}"

Use that reply to unblock whatever was waiting on it, then continue the loop
from there (reviewer, applier, or logging, whichever comes next). Report every
remaining stage with
  python "dashboard/stage.py" {id} <stage> "<note>"
as the Dashboard section of CLAUDE.md describes. If the reply raises a new
question, report needs_you again with that question and end the run."""


def _history_text(job_id):
    return "\n".join(f"{s['stage']}: {s['note']}" if s.get("note") else s["stage"]
                     for s in stages_of(job_id)) or "(no stages recorded)"


def run_job(job_id):
    with lock:
        jobs = load()
        job = find(jobs, job_id)
        job["state"] = "running"
        job["started"] = time.time()
        job.pop("finished", None)
        _, who, model = load_submitter()
        job["submitter"] = f"{who} · {model}"  # what was selected when this run started
        reply = job.pop("pending_reply", None)
        history = _history_text(job_id) if reply else None
        save(jobs)
        url = job["url"]
    if reply:
        with open(os.path.join(STAGES, f"{job_id}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "stage": "human_reply", "note": reply}) + "\n")
        prompt = RESUME_PROMPT.format(url=url, id=job_id, history=history, reply=reply)
    else:
        prompt = PROMPT.format(url=url, id=job_id)
    log_path = os.path.join(LOGS, f"{job_id}.jsonl")
    if MOCK:
        cmd = [sys.executable, os.path.join(HERE, "mock_agent.py")]
    else:
        cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions", "--add-dir", CAREER]
    with open(log_path, "a" if reply else "w", encoding="utf-8") as log:
        env = dict(os.environ)
        if NO_SUBMIT:
            # Hard guard, forwarded into WSL: fill.py cannot click submit.
            env["APPLIER_FORCE_NO_SUBMIT"] = "1"
            env["WSLENV"] = "APPLIER_FORCE_NO_SUBMIT" + (":" + env["WSLENV"] if env.get("WSLENV") else "")
        proc = subprocess.Popen(cmd, cwd=AGENT_ROOT, stdin=subprocess.PIPE, stdout=log,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        state["proc"], state["job"] = proc, job_id
        proc.stdin.write(prompt + (NO_SUBMIT_LINE if NO_SUBMIT else ""))
        proc.stdin.close()
        code = proc.wait()
    with lock:
        state["proc"], state["job"] = None, None
        jobs = load()
        job = find(jobs, job_id)
        if job is None:
            return
        job["state"] = "done"
        job["finished"] = time.time()
        st = stages_of(job_id)
        if not st or st[-1]["stage"] not in FINAL:
            why = "stopped from the dashboard" if job.get("killed") else \
                  f"agent exited (code {code}) without reporting a final stage"
            with open(os.path.join(STAGES, f"{job_id}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "stage": "failed", "note": why}) + "\n")
        save(jobs)


def pick_next(jobs, jobs_run, cap=MAX_RUNS):
    """Next job to run, in queue order. The cap is on distinct APPLICATIONS per
    session, not on runs: counting runs let one job's retries and resumes use
    up all five slots, and the next job sat on "Waiting to run" with no reason."""
    return next((j for j in jobs if j["state"] == "sent"
                 and (j["id"] in jobs_run or len(jobs_run) < cap)), None)


def worker():
    while True:
        time.sleep(1)
        if state["proc"] is not None:
            continue
        with lock:
            nxt = pick_next(load(), state["jobs_run"])
            if nxt:
                state["jobs_run"].add(nxt["id"])
                state["runs"] = len(state["jobs_run"])
        if nxt:
            try:
                run_job(nxt["id"])
            except Exception as e:  # never let one bad run kill the worker
                with open(os.path.join(STAGES, f"{nxt['id']}.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"t": time.time(), "stage": "failed", "note": f"runner error: {e}"}) + "\n")
                with lock:
                    jobs = load()
                    j = find(jobs, nxt["id"])
                    if j:
                        j["state"] = "done"
                        save(jobs)


# ------------------------------------------------------------------ queue.txt ---
QUEUE_TXT = os.path.join(CAREER, "QUEUE.txt")
DISMISSED = os.path.join(HERE, "dismissed.json")  # links removed on the dashboard


def load_dismissed():
    try:
        with open(DISMISSED, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def dismiss(url):
    """Removing a job on the dashboard must stick. Without this, the next
    QUEUE.txt sync re-added every removed link. QUEUE.txt itself is Joaquin's
    tracking file and is never edited from here."""
    d = load_dismissed()
    d.add(url)
    with open(DISMISSED, "w", encoding="utf-8") as f:
        json.dump(sorted(d), f, indent=1)


def sync_from_queue_txt():
    """QUEUE.txt in the career folder is Joaquin's real, durable list of jobs to
    apply to. It survives however many times dashboard test data gets cleared.
    Anything in it that jobs.json does not already know about gets added as a
    pending job, labelled from the comment line above the link. Never removes
    or reorders anything already in jobs.json."""
    if not os.path.exists(QUEUE_TXT):
        return 0
    with lock:
        jobs = load()
        known = {j["url"] for j in jobs} | load_dismissed()
        added = 0
        block_label = None  # the FIRST substantive comment line of the current block
        with open(QUEUE_TXT, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.strip()
                if not stripped:
                    block_label = None  # a blank line starts a new block
                    continue
                if stripped.startswith("#"):
                    text = stripped.lstrip("#").strip()
                    if block_label is None and text and not text.upper().startswith(("BEFORE", "=", "NOTE", "PLATFORM")):
                        block_label = text
                    continue
                m = URL_RE.search(line)
                if not m:
                    continue
                url = m.group(0).rstrip(").,")
                if url in known:
                    continue
                jobs.append({"id": uuid.uuid4().hex[:8], "url": url, "label": block_label or "",
                             "state": "pending", "created": time.time(), "source": "QUEUE.txt"})
                known.add(url)
                added += 1
                block_label = None
        if added:
            save(jobs)
    return added


# ---------------------------------------------------------------------- api ---
URL_RE = re.compile(r"https?://\S+")


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.get("/api/jobs")
def list_jobs():
    with lock:
        jobs = load()
    for j in jobs:
        j["stages"] = stages_of(j["id"])
    return jsonify({"jobs": jobs, "runs": state["runs"], "max_runs": MAX_RUNS,
                    "mock": MOCK, "no_submit": NO_SUBMIT, "running": state["job"]})


@app.post("/api/jobs")
def add_jobs():
    text = (request.json or {}).get("text", "")
    added, skipped = [], []
    with lock:
        jobs = load()
        known = {j["url"] for j in jobs}
        for line in text.splitlines():
            m = URL_RE.search(line)
            if not m:
                continue
            url = m.group(0).rstrip(").,")
            label = (line[:m.start()] + line[m.end():]).strip(" -|:\t")
            if url in known:
                skipped.append(url)
                continue
            jobs.append({"id": uuid.uuid4().hex[:8], "url": url, "label": label,
                         "state": "pending", "created": time.time()})
            known.add(url)
            added.append(url)
        save(jobs)
    return jsonify({"added": len(added), "skipped": skipped})


@app.post("/api/jobs/<job_id>/<action>")
def act(job_id, action):
    with lock:
        jobs = load()
        job = find(jobs, job_id)
        if not job:
            return jsonify({"error": "no such job"}), 404
        i = jobs.index(job)
        if action == "send" and job["state"] == "pending":
            job["state"] = "sent"
        elif action == "unsend" and job["state"] == "sent":
            job["state"] = "pending"
        elif action == "up" and i > 0:
            jobs[i - 1], jobs[i] = jobs[i], jobs[i - 1]
        elif action == "down" and i < len(jobs) - 1:
            jobs[i + 1], jobs[i] = jobs[i], jobs[i + 1]
        elif action == "top":
            jobs.insert(0, jobs.pop(i))
        elif action == "remove" and job["state"] != "running":
            jobs.pop(i)
            dismiss(job["url"])
        elif action == "restart" and job["state"] == "done":
            p = os.path.join(STAGES, f"{job_id}.jsonl")
            if os.path.exists(p):
                os.replace(p, p.replace(".jsonl", f".{int(time.time())}.old"))
            job.update(state="pending", killed=False, pending_reply=None)
        elif action == "resume" and job["state"] == "done":
            reply = (request.json or {}).get("reply", "").strip()
            if not reply:
                return jsonify({"error": "reply text is empty"}), 400
            job.update(state="sent", killed=False, pending_reply=reply)
        elif action == "stop" and job["state"] == "running" and state["job"] == job_id:
            job["killed"] = True
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(state["proc"].pid)],
                           capture_output=True)
            # taskkill ends the Windows side only. Hermes and the Playwright
            # browser run inside WSL and would keep filling the form.
            if not MOCK:
                # [f], [a], [h]: a plain pattern would also match this bash
                # command's own command line and pkill would kill itself.
                subprocess.run(["wsl", "bash", "-c",
                                "pkill -f 'applier/[f]ill.py'; pkill -f '[a]pply.py'; pkill -f '[h]ermes chat'; true"],
                               capture_output=True, timeout=15)
        else:
            return jsonify({"error": f"cannot {action} a job that is {job['state']}"}), 409
        save(jobs)
    return jsonify({"ok": True})


@app.post("/api/send_all")
def send_all():
    with lock:
        jobs = load()
        n = 0
        for j in jobs:
            if j["state"] == "pending":
                j["state"] = "sent"
                n += 1
        save(jobs)
    return jsonify({"sent": n})


@app.get("/api/jobs/<job_id>/activity")
def activity(job_id):
    return jsonify({"lines": activity_of(job_id)})


@app.get("/api/submitter")
def get_submitter():
    _, who, model = load_submitter()
    return jsonify({"submitter": who, "model": model, "options": SUBMITTER_MODELS})


@app.post("/api/submitter")
def set_submitter():
    """Switch who submits (and with which model). Writes submitter.json, which
    the main agent reads at the submit step, so it applies to the next job
    that reaches that step. Every other field in the file is kept."""
    body = request.json or {}
    who = body.get("submitter")
    if who not in SUBMITTER_MODELS:
        return jsonify({"error": f"submitter must be one of {sorted(SUBMITTER_MODELS)}"}), 400
    model = body.get("model") or SUBMITTER_MODELS[who][0]
    if model not in SUBMITTER_MODELS[who]:
        return jsonify({"error": f"{model!r} is not a {who} model"}), 400
    with lock:
        conf, _, _ = load_submitter()
        conf["submitter"] = who
        conf[f"{who}_model"] = model
        tmp = SUBMITTER_CONF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2)
        os.replace(tmp, SUBMITTER_CONF)
    return jsonify({"submitter": who, "model": model})


@app.post("/api/sync_queue")
def sync_queue():
    return jsonify({"added": sync_from_queue_txt()})


def recover():
    """A job left 'running' by a crashed server can never finish. Close it."""
    jobs = load()
    for j in jobs:
        if j["state"] == "running":
            j["state"] = "done"
            with open(os.path.join(STAGES, f"{j['id']}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "stage": "failed",
                                    "note": "dashboard restarted while this was running"}) + "\n")
    save(jobs)


def already_running():
    """Three copies of this server once ran on the same port at the same time,
    each with its own worker, so one job could be picked up twice."""
    import socket
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


if __name__ == "__main__":
    if already_running():
        print(f"The dashboard is already running at http://127.0.0.1:{PORT}. Not starting a second copy.")
        sys.exit(0)
    recover()
    n = sync_from_queue_txt()
    if n:
        print(f"Picked up {n} link(s) from QUEUE.txt that were not already tracked.")
    threading.Thread(target=worker, daemon=True).start()
    print(f"{'MOCK MODE, applies nowhere. ' if MOCK else ''}Open http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
