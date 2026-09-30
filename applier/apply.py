#!/usr/bin/env python3
"""
Submit one application in one call: build job.json, fill the form, read the
emailed code from Gmail, submit, and print ONE JSON result.

    python apply.py <url> <resume_pdf> <cover_pdf> --company "Company A" [--run-key k] [--no-submit]

Works from Windows (runs fill.py through WSL) or from inside WSL (runs it
directly), so either submitter can call it: the Claude applier subagent or
Hermes. Paths may be Windows or /mnt/c style.

Why this exists: a submission used to cost the applier about 51 tool calls
(assemble job.json, start fill.py, poll it, search Gmail, write CODE.txt,
poll again). All of that is mechanical. Now it is one command, and the agent
only has to read the result and decide.

The result JSON always has: status, confirmation, platform, run_dir, log,
screenshots, problems, unknown_fields, guessed. Exit code 0 only on
status == "submitted" (or "filled_not_submitted" with --no-submit).
"""
import argparse, json, os, platform, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prepare_run  # noqa: E402

IN_WSL = platform.system() == "Linux"
WSL_PY = "/opt/career/.venv/bin/python"


def run_fill(job_path_wsl, log_path, timeout_s):
    fill_wsl = prepare_run.to_wsl(os.path.join(HERE, "fill.py"))
    if IN_WSL:
        cmd = [WSL_PY, fill_wsl, job_path_wsl]
    else:
        cmd = ["wsl", WSL_PY, fill_wsl, job_path_wsl]
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=log, text=True,
                               encoding="utf-8", timeout=timeout_s, env=env)
            out = r.stdout
        except subprocess.TimeoutExpired as e:
            return {"status": "failed", "problems": [f"fill.py exceeded {timeout_s}s"]}
    # fill.py prints exactly one JSON object on stdout
    m = re.search(r"\{.*\}\s*$", out or "", re.S)
    if not m:
        return {"status": "failed", "problems": ["fill.py printed no JSON result", (out or "")[-300:]]}
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("resume_pdf")
    ap.add_argument("cover_pdf")
    ap.add_argument("--company", required=True, help="as in the Greenhouse email subject")
    ap.add_argument("--run-key")
    ap.add_argument("--no-submit", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    key = a.run_key or re.sub(r"[^a-z0-9]+", "-", a.company.lower()).strip("-")
    t0 = time.time()
    fname, recipe = prepare_run.detect_recipe(a.url)
    if recipe is None:
        print(json.dumps({"status": "unknown_platform", "confirmation": "", "platform": None,
                          "problems": [f"no saved recipe matches {a.url}"]}))
        sys.exit(2)

    # Build job.json through prepare_run.py itself, so both paths stay identical.
    args = [sys.executable, os.path.join(HERE, "prepare_run.py"), a.url,
            prepare_run.to_wsl(a.resume_pdf), prepare_run.to_wsl(a.cover_pdf), key, "--company", a.company]
    if a.no_submit:
        args.append("--no-submit")
    r = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    if r.returncode != 0:
        print(json.dumps({"status": "failed", "confirmation": "", "platform": fname,
                          "problems": ["prepare_run failed: " + r.stderr.strip()[-300:]]}))
        sys.exit(1)
    job_path = r.stdout.strip().splitlines()[-1]
    run_dir = os.path.dirname(job_path)
    # A code left from an earlier run is always dead; fill.py fetches a fresh one.
    try:
        os.remove(os.path.join(run_dir, "CODE.txt"))
    except OSError:
        pass

    log_path = os.path.join(run_dir, "fill.log")
    res = run_fill(prepare_run.to_wsl(job_path), log_path, a.timeout)

    status = res.get("status", "failed")
    body = res.get("page_text", "") or ""
    signals = [s for s in recipe.get("success_signals", []) if s.lower() in body.lower()]
    confirmation = ""
    if status == "submitted":
        # quote the sentence around the first success signal
        i = body.lower().find(signals[0].lower()) if signals else -1
        confirmation = body[max(0, i - 80): i + 200].strip() if i >= 0 else body[-200:].strip()
    out = {
        "status": status,
        "confirmation": confirmation,
        "platform": fname,
        "run_dir": run_dir,
        "log": log_path,
        "seconds": int(time.time() - t0),
        "screenshots": res.get("screenshots", []),
        "problems": res.get("problems", []),
        "stops": res.get("stops", []),
        "unknown_fields": res.get("unknown_fields", []),
        # Answers the label matcher chose for the company's own questions, so
        # Joaquin can see what was said in his name. (This used to read an
        # audit flag fill.py never sets, so it was always empty.)
        "guessed": [{"label": spec.get("label", ""), "answer_from": spec.get("answer", ""),
                     "value": next((x.get("value") for x in res.get("audit", [])
                                    if isinstance(x, dict) and x.get("field") == fid), "")}
                    for fid, spec in (res.get("learned") or {}).items()],
    }
    # Also saved as a file: whoever called us (Claude or Hermes) is checked
    # against this, not against its own summary of what happened.
    with open(os.path.join(run_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))
    ok = status == "submitted" or (a.no_submit and status == "filled_not_submitted")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
