#!/usr/bin/env python3
"""
Read QUEUE.txt, work out which application platform each link uses, and group
them. Tells you where to spend build time: the platform with the most jobs
behind it, not the next link in the list.

    python triage.py [path/to/QUEUE.txt]
"""
import os, re, sys
from collections import defaultdict
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
FT = os.environ.get("CAREER_DIR", "<CAREER_DIR>")  # documents and trackers live there, code lives here
DEFAULT = os.path.join(FT, "QUEUE.txt")

# how far along each platform is, so triage can say what is actually runnable
STATE = {
    "greenhouse": "READY, proven twice",
    "lever":      "untested, close cousin of Greenhouse",
    "ashby":      "untested, close cousin of Greenhouse",
    "phenom":     "PARTIAL, 4 of 6 steps learned on Company M",
    "eightfold":  "PARTIAL, account creation and opening learned on BCG",
    "workday":    "NOT STARTED",
    "avature":    "NOT STARTED",
    "tal.net":    "BLOCKED, captcha on the BofA flow",
    "icims":      "NOT STARTED",
    "smartrecruiters": "NOT STARTED",
    "custom":     "NOT STARTED, one-off site",
}

RULES = [
    ("workday",        r"myworkdayjobs\.com|\.wd\d+\."),
    ("greenhouse",     r"greenhouse\.io|gh_jid=|gh_src="),
    ("lever",          r"jobs\.lever\.co"),
    ("ashby",          r"ashbyhq\.com"),
    ("eightfold",      r"eightfold\.ai|experiencedtalent\."),
    ("tal.net",        r"tal\.net"),
    ("icims",          r"icims\.com"),
    ("smartrecruiters", r"smartrecruiters\.com"),
    ("avature",        r"/careers/JobDetail\?jobId=|/careers/Login\?jobId=|TGnewUI"),
    ("phenom",         r"careers\.[a-z0-9\-]+\.(com|net)/.*/(job|apply)"),
]


def platform(url):
    for name, pat in RULES:
        if re.search(pat, url, re.I):
            return name
    return "custom"


def company(url):
    h = urlparse(url).netloc.lower().replace("www.", "")
    parts = [p for p in h.split(".") if p not in ("com", "net", "org", "en", "careers", "jobs", "group")]
    for p in parts:
        if p not in ("wd1", "wd2", "wd3", "wd5", "myworkdayjobs", "boards", "job-boards"):
            return p
    return h


def load_blocklist():
    f = os.path.join(HERE, "BLOCKLIST.json")
    if not os.path.exists(f):
        return []
    import json
    return json.load(open(f, encoding="utf-8")).get("blocked_jobs", [])


def blocked_by(url, blocklist):
    """A queued link is refused if every one of an entry's match strings is in it."""
    for b in blocklist:
        pats = b.get("match") or [b.get("url", "")]
        if pats and all(p.lower() in url.lower() for p in pats):
            return b
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    blocklist = load_blocklist()
    seen, notes, blocked = set(), [], []
    groups = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        if not line.lower().startswith("http"):
            if not line.startswith("#"):
                notes.append(line)
            continue
        if line in seen:
            continue
        seen.add(line)
        hit = blocked_by(line, blocklist)
        if hit:
            blocked.append((line, hit))
            continue
        groups[platform(line)].append(line)

    if blocked:
        print("=" * 78)
        print(f"REFUSED, {len(blocked)} link(s) are on the blocklist. Do not apply to these.")
        print("=" * 78)
        for url, b in blocked:
            print(f"  {b['company']} - {b['role']}")
            print(f"     why : {b['reason']}")
            print(f"     said: \"{b['quote'][:120]}\"")
            print(f"     url : {url[:90]}")
        print()

    total = sum(len(v) for v in groups.values())
    print(f"{total} unique links across {len(groups)} platforms\n")
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for plat, urls in order:
        print(f"{plat.upper():<16} {len(urls):>2} job(s)   {STATE.get(plat, '')}")
        for u in urls:
            print(f"    {company(u):<14} {u[:96]}")
        print()
    if notes:
        print("INSTRUCTIONS FOUND IN THE QUEUE, not links:")
        for n in notes:
            print("   *", n)
        print()
    runnable = sum(len(v) for k, v in groups.items() if STATE.get(k, "").startswith("READY"))
    print(f"Runnable right now: {runnable} of {total}")
    build = [(k, len(v)) for k, v in order if STATE.get(k, "").startswith(("NOT", "PARTIAL"))]
    if build:
        print("Build order, by jobs unlocked:")
        for k, n in build:
            print(f"   {k}  unlocks {n}")


if __name__ == "__main__":
    main()
