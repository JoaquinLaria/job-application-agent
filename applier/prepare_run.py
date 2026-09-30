#!/usr/bin/env python3
"""
Assemble one job.json for fill.py, in one call, instead of the applier reading
recipes/, runs/, and ANSWERS.json separately across several tool calls.

    python prepare_run.py <url> <resume_pdf> <cover_pdf> <run_key> [--no-submit]

Prints the job.json path on success. Exit code 2 means the platform has no
saved recipe: the applier should stop and return unknown_platform rather than
improvise on a live application. Exit code 1 is any other setup error.

Both resume_pdf and cover_pdf must be Linux-visible paths already
(/mnt/c/...), since fill.py runs inside WSL.
"""
import argparse, json, os, re, sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPES = os.path.join(HERE, "recipes")
ANSWERS = os.path.join(HERE, "ANSWERS.json")
if not os.path.exists(ANSWERS):  # public repo: only the redacted example ships
    ANSWERS = os.path.join(HERE, "ANSWERS.example.json")
RUNS = os.path.join(HERE, "runs")


def to_wsl(path):
    """fill.py runs inside WSL, so every path in job.json must be /mnt/c/...
    A Windows path like C:\\Users\\... is meaningless there: fill.py would
    create a stray folder and poll a CODE.txt nobody else can see."""
    # Git Bash rewrites a /mnt/c/... argument into C:/Program Files/Git/mnt/c/...
    # before Python sees it. Undo that, or fill.py looks for a file that is not there.
    p0 = path.replace("\\", "/")
    i = p0.find("/Git/mnt/")
    if i >= 0:
        return "/mnt/" + p0[i + len("/Git/mnt/"):]
    if path.startswith("/mnt/"):
        return path  # already a WSL path; abspath would mangle it on Windows
    p = os.path.abspath(path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def detect_recipe(url):
    """Same idea as the platform table in the Instinct Agent Brief, but as one
    lookup instead of the applier re-deriving it from the URL by eye each
    time. Matches a recipe file's own "match" list against the URL."""
    for fname in sorted(os.listdir(RECIPES)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(RECIPES, fname)
        try:
            with open(path, encoding="utf-8") as f:
                recipe = json.load(f)
        except (OSError, ValueError):
            continue
        for needle in recipe.get("match", []):
            if needle.lower() in url.lower():
                return fname, recipe
    return None, None


def rewrite_url(url, recipe):
    """Apply the recipe's url_rewrite, then its gh_jid_rewrite.

    A company-site link such as companyc.com/careers/job/?gh_jid=123 embeds the
    Greenhouse form in an iframe, and fill.py timed out on every field. The
    board slug is taken from the site's domain (www.companyc.com -> companyc)."""
    rw = recipe.get("url_rewrite")
    if rw:
        m = re.search(rw["from"], url)
        if m:
            return rw["to"].format(**m.groupdict())
    gj = recipe.get("gh_jid_rewrite")
    if gj:
        m = re.search(r"[?&]gh_jid=(\d+)", url)
        host = urlparse(url).hostname or ""
        if m and "greenhouse.io" not in host:
            labels = host.split(".")
            company = labels[-2] if len(labels) >= 2 else host
            return gj["to"].format(company=company, jobid=m.group(1))
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("resume_pdf")
    ap.add_argument("cover_pdf")
    ap.add_argument("run_key")
    ap.add_argument("--no-submit", action="store_true")
    ap.add_argument("--company", help="as it appears in the Greenhouse email subject, e.g. 'Company A'")
    a = ap.parse_args()

    fname, recipe = detect_recipe(a.url)
    if recipe is None:
        print(f"no saved recipe matches {a.url}", file=sys.stderr)
        sys.exit(2)

    answers = json.load(open(ANSWERS, encoding="utf-8"))
    out_dir = os.path.join(RUNS, a.run_key)
    os.makedirs(out_dir, exist_ok=True)

    files = {"resume_pdf": to_wsl(a.resume_pdf), "cover_pdf": to_wsl(a.cover_pdf)}
    # Recipes ask for the transcript under these keys ("upload": "transcript_undergrad").
    # It used to be missing here, so any form requiring a transcript blocked
    # and the run stopped to ask Joaquin for a file that already existed.
    transcript = answers.get("education", {}).get("transcript_pdf_wsl")
    if transcript:
        files["transcript_undergrad"] = transcript
        files["transcript"] = transcript

    # Nothing else applies the recipe's url_rewrite. A my.greenhouse.io link
    # once went to fill.py as-is and landed on a candidate login page.
    url = rewrite_url(a.url, recipe)
    if url != a.url:
        print(f"url rewritten: {url}", file=sys.stderr)

    job = {
        "url": url,
        "recipe": recipe,
        "answers": answers,
        "files": files,
        "submit": not a.no_submit,
        "out_dir": to_wsl(out_dir),
        "code_file": to_wsl(os.path.join(out_dir, "CODE.txt")),
        "company": a.company,
    }
    job_path = os.path.join(out_dir, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=1)

    print(job_path)
    print(f"platform: {fname}", file=sys.stderr)


if __name__ == "__main__":
    main()
