#!/usr/bin/env python3
"""
Report a stage to the dashboard. The main agent calls this at each step.

    python stage.py <job_id> <stage> "<short note>"

Stages, in the order they normally happen:
    screening          reading the posting
    files_written      writer returned both documents
    in_review          reviewer is checking them
    review_failed      reviewer sent fixes back to the writer
    reviewer_approved  reviewer passed them
    submitting         applier is filling the form
Final stages:
    submitted          the site confirmed it, note holds the quoted text
    stopped            not eligible, note holds the quoted phrase
    needs_you          CAPTCHA, login, missing answer, or three reviewer fails
    handoff_muse       unknown platform, handoff file written
    failed             anything else that ended the run
    dry_run            test mode: form filled, deliberately not submitted
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = ("screening", "files_written", "in_review", "review_failed",
          "reviewer_approved", "submitting", "submitted", "stopped",
          "needs_you", "handoff_muse", "failed", "dry_run")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    job_id, stage = sys.argv[1], sys.argv[2]
    note = " ".join(sys.argv[3:]).strip()
    if stage not in STAGES:
        sys.exit(f"unknown stage '{stage}'. Use one of: {', '.join(STAGES)}")
    d = os.path.join(HERE, "stages")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{job_id}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "stage": stage, "note": note}) + "\n")
    print(f"stage {job_id}: {stage}")


if __name__ == "__main__":
    main()
