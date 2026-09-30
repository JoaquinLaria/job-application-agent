#!/usr/bin/env python3
"""
Preflight: prove every piece of the application pipeline works before a live
application depends on it. Applies nowhere, submits nothing.

    python preflight.py

Each check exists because that exact thing once broke a real run (see the
"Lessons from real runs" table in CLAUDE.md). Exit code 0 means all checks
passed. Any FAIL means fix it before sending jobs.
"""
import glob, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
APPLIER = os.path.join(HERE, "applier")
CAREER = os.environ.get("CAREER_DIR", "<CAREER_DIR>")
SECRETS = "C:/Users/joaco/.career_secrets/gmail.json"
WSL_PY = "/opt/career/.venv/bin/python"
sys.path.insert(0, APPLIER)

results = []


def check(name, fn):
    t = time.time()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({time.time()-t:.1f}s)  {detail}")


def to_wsl(p):
    p = p.replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:] if p[1:2] == ":" else p


def wsl(cmd, timeout=60):
    return subprocess.run(["wsl", "bash", "-c", cmd], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "MSYS_NO_PATHCONV": "1"})


# ---------------------------------------------------------------- checks ---
def agent_files():
    need = ["CLAUDE.md", ".claude/agents/writer.md", ".claude/agents/reviewer.md", ".claude/agents/applier.md"]
    missing = [n for n in need if not os.path.exists(os.path.join(HERE, n))]
    return not missing, "missing: " + ", ".join(missing) if missing else "main agent + 3 subagents"


def career_files():
    res = os.path.join(CAREER, "01. Resume and Cover Letters")
    need = {"master resume v5": os.path.join(res, "Joaquin Laria - Resume (FT 2027) v5.docx"),
            "QUEUE.txt": os.path.join(CAREER, "QUEUE.txt"),
            "APPLICATIONS.csv": os.path.join(CAREER, "APPLICATIONS.csv")}
    missing = [k for k, p in need.items() if not os.path.exists(p)]
    return not missing, "missing: " + ", ".join(missing) if missing else "resume, queue, tracker found"


def answers_file():
    a = json.load(open(os.path.join(APPLIER, "ANSWERS.json"), encoding="utf-8"))
    problems = []
    if not a.get("screening_defaults"):
        problems.append("no screening_defaults (agent will stop to ask screening questions)")
    ed = a.get("education", {})
    if not ed.get("gpa_scale_4_0") or "ASK" in str(ed.get("gpa_scale_4_0")):
        problems.append("4.0-scale GPA not set")
    t = ed.get("transcript_pdf")
    if not t or not os.path.exists(t):
        problems.append("transcript_pdf missing on disk")
    if t and not t.isascii():
        problems.append("transcript path has non-ASCII characters (breaks uploads)")
    if not a.get("work_authorization"):
        problems.append("no work_authorization block")
    return not problems, "; ".join(problems) or "screening defaults, GPA, transcript, visa answers present"


def email_matches_inbox():
    """The 12-minute lesson: the inbox the agent reads must be the address on the form."""
    a = json.load(open(os.path.join(APPLIER, "ANSWERS.json"), encoding="utf-8"))
    form_email = a["identity"]["email"].lower()
    if not os.path.exists(SECRETS):
        return False, f"no {SECRETS}"
    user = json.load(open(SECRETS, encoding="utf-8")).get("user", "").lower()
    return form_email == user, f"form uses {form_email}, agent reads {user or 'nothing'}"


def gmail_login():
    import gmail_code
    if not gmail_code.load_secrets():
        return False, "no app password saved"
    code = gmail_code.newest_code(time.time() - 7 * 86400)  # logs in and reads; never prints the password
    return True, "IMAP login ok" + (", recent code found" if code else ", no code in last 7 days (fine)")


def wsl_runtime():
    r = wsl(f'cd "{to_wsl(APPLIER)}" && {WSL_PY} -c "import playwright, gmail_code, fill; print(gmail_code.load_secrets() is not None)"')
    ok = r.returncode == 0 and r.stdout.strip().endswith("True")
    return ok, "playwright + fill.py import, Gmail secret visible from Linux" if ok else (r.stderr or r.stdout).strip()[-200:]


def recipes_match():
    import prepare_run
    samples = {"greenhouse.json": ["https://my.greenhouse.io/jobs/companya/1000000001",
                                   "https://job-boards.greenhouse.io/x/jobs/1",
                                   "https://boards.greenhouse.io/embed/job_app?for=x&token=1",
                                   "https://companya.com/pages/job-openings?gh_jid=1000000001"]}
    bad = []
    for want, urls in samples.items():
        for u in urls:
            got, _ = prepare_run.detect_recipe(u)
            if got != want:
                bad.append(f"{u} -> {got}")
    for p in glob.glob(os.path.join(APPLIER, "recipes", "*.json")):
        json.load(open(p, encoding="utf-8"))
    return not bad, "; ".join(bad) or "all recipes parse, every Greenhouse URL shape matches"


def prepare_run_output():
    key = "zz-preflight"
    r = subprocess.run([sys.executable, os.path.join(APPLIER, "prepare_run.py"),
                        "https://my.greenhouse.io/jobs/companya/1000000001",
                        "/mnt/c/x/r.pdf", "/mnt/c/x/c.pdf", key, "--no-submit", "--company", "Test"],
                       capture_output=True, text=True, timeout=30)
    run = os.path.join(APPLIER, "runs", key)
    try:
        if r.returncode != 0:
            return False, r.stderr.strip()[-200:]
        j = json.load(open(os.path.join(run, "job.json"), encoding="utf-8"))
        problems = []
        for k in ("out_dir", "code_file"):
            if not str(j.get(k, "")).startswith("/mnt/"):
                problems.append(f"{k} is not a /mnt/ path")
        if "transcript_undergrad" not in j["files"]:
            problems.append("transcript not attached")
        if "my.greenhouse.io" in j["url"]:
            problems.append("url_rewrite not applied")
        if j.get("submit"):
            problems.append("--no-submit ignored")
        return not problems, "; ".join(problems) or "Linux paths, transcript attached, URL rewritten"
    finally:
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", run.replace("/", "\\")], capture_output=True)


def pdf_conversion():
    src = os.path.join(CAREER, "01. Resume and Cover Letters", "Joaquin Laria - Resume (FT 2027) v5.docx")
    with tempfile.TemporaryDirectory() as out:
        r = subprocess.run([sys.executable, os.path.join(APPLIER, "docx_to_pdf.py"), out, src],
                           capture_output=True, text=True, timeout=90)
        pdfs = glob.glob(os.path.join(out, "*.pdf"))
        ok = r.returncode == 0 and pdfs and os.path.getsize(pdfs[0]) > 10000
    if not ok:
        return False, (r.stderr or r.stdout or "no PDF produced").strip()[-200:]
    stray = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/NH"], capture_output=True, text=True).stdout
    return True, "PDF made from the OneDrive path" + ("" if "WINWORD" not in stray else " (a Word window is open, fine if it is yours)")


def unit_tests():
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=HERE,
                       capture_output=True, text=True, timeout=120, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    tail = (r.stderr or "").strip().splitlines()
    summary = next((l for l in reversed(tail) if l.startswith("Ran ")), "")
    return r.returncode == 0, f"{summary}, all passed" if r.returncode == 0 else (tail[-1] if tail else "tests failed")


def submitter_ready():
    conf = json.load(open(os.path.join(HERE, "submitter.json"), encoding="utf-8"))
    who = conf.get("submitter")
    if who == "claude":
        return os.path.exists(os.path.join(HERE, ".claude/agents/applier.md")), "Claude applier subagent"
    if who != "hermes":
        return False, f"submitter.json says {who!r}; use 'claude' or 'hermes'"
    r = wsl('test -x ~/.local/bin/hermes && python3 -c "'
            'v=[l.split(\'=\',1)[1].strip() for l in open(\'/home/joaco/.hermes/.env\') if l.startswith(\'OPENAI_API_KEY=\')];'
            'print(bool(v) and v[0].startswith(\'sk-parley-v1-\'))"')
    ok = r.returncode == 0 and r.stdout.strip() == "True"
    return ok, f"Hermes installed, Parley key stored, model {conf.get('hermes_model')}" if ok else "Hermes or its Parley key missing in WSL"


def dashboard_up():
    import urllib.request
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:5057/api/jobs", timeout=3))
        return True, f"running, {len(d['jobs'])} jobs, {'MOCK' if d['mock'] else 'real'} mode"
    except Exception:
        return True, "not running (start it with Start Application Dashboard.bat)"


if __name__ == "__main__":
    print("Preflight: nothing is submitted.\n")
    check("agent instruction files", agent_files)
    check("career folder files", career_files)
    check("answers file", answers_file)
    check("form email == inbox the agent reads", email_matches_inbox)
    check("Gmail IMAP login", gmail_login)
    check("Linux runtime for fill.py", wsl_runtime)
    check("recipe URL matching", recipes_match)
    check("prepare_run.py output", prepare_run_output)
    check("docx -> PDF conversion", pdf_conversion)
    check("regression tests (tests/)", unit_tests)
    check("submitter (submitter.json)", submitter_ready)
    check("dashboard", dashboard_up)
    n_fail = results.count(False)
    print(f"\n{len(results) - n_fail} of {len(results)} passed." + (" Fix the FAILs before sending jobs." if n_fail else " Ready."))
    sys.exit(1 if n_fail else 0)
