#!/usr/bin/env python3
"""
Keyword tailoring, measured rather than guessed.

    python tailor.py --jd jd.txt --resume "path/to/resume.docx"

Reads the job description, works out which terms actually matter, checks which
of them the resume already carries, and reports the gap split into:

  PLACEABLE   terms Joaquin can legitimately carry, because they name a skill,
              tool or course from his own pools in BULLETS.json
  REPHRASE    terms already covered by a synonym he uses, worth matching exactly
  IGNORE      company boilerplate, benefits language and HTML noise

Nothing here invents experience. It changes wording and ordering so that true
experience is found by the filter.
"""
import argparse, json, os, re
from collections import Counter

import docx

HERE = os.path.dirname(os.path.abspath(__file__))

STOP = set("""a an the and or but if of to in on for with at by from as is are was were be
been being this that these those it its their his her our your my we i you they he she not
no than then so such over under into out up down more most less least very can will would
could should may might must have has had do does did about across after all also any
because before both during each few how just like new now only other own same some through
too what when where which while who why will able across within per via etc""".split())

# words that look important but are boilerplate, benefits or HTML leftovers
NOISE = set("""nbsp data section start end strong href http https www com class span div amp
quot equal opportunity employer diversity inclusion inclusive belonging veteran disability
race gender religion sexual orientation gender identity national origin applicants
reasonable accommodation background check compensation benefits salary range bonus
retirement medical dental vision paid time off holiday wellness culture people team
company companies role roles position candidate candidates apply application applicants
join joining looking seeking ideal successful qualified preferred required requirements
responsibilities qualifications about work working world year years time full based
opportunity opportunities""".split())

SYNONYMS = {
    "experimentation": ["a/b testing", "a/b", "experiment", "experiments"],
    "analytics": ["analytics", "analysis", "analytical"],
    "sql": ["sql", "bigquery"],
    "stakeholder": ["cross-functional", "stakeholders"],
    "roadmap": ["roadmap", "roadmaps"],
    "go-to-market": ["gtm", "go to market"],
    "kpi": ["kpis", "metrics", "success metrics"],
    "p&l": ["ebitda", "unit economics"],
    "operating model": ["operating model", "shared services"],
    "econometrics": ["econometrics", "economics"],
    "workstream": ["workstreams", "workstream"],
}


def words(t):
    return re.findall(r"[a-zA-Z][a-zA-Z0-9\-\+/&]*", t.lower())


def phrases(t):
    """Two-word phrases matter more than single words for JD matching."""
    w = [x for x in words(t) if x not in STOP]
    return [f"{w[i]} {w[i+1]}" for i in range(len(w) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True)
    ap.add_argument("--resume", required=True)
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()

    bullets = json.load(open(os.path.join(HERE, "BULLETS.json"), encoding="utf-8"))
    pools = bullets["tailorable_lines"]
    skill_pool = [s.lower() for s in pools["skills"]["pool"]]
    cp = pools["coursework"]["pool"]
    course_pool = []
    if isinstance(cp, dict):
        for v in cp.values():
            course_pool += [x.lower() for x in v]
    else:
        course_pool = [x.lower() for x in cp]
    vocab = []
    for v in bullets.get("vocabulary_he_has_earned", {}).values():
        if isinstance(v, list):
            vocab += [x.lower() for x in v]

    jd_raw = open(a.jd, encoding="utf-8").read()
    jd_raw = re.sub(r"<[^>]+>", " ", jd_raw)
    resume = " ".join(p.text for p in docx.Document(a.resume).paragraphs).lower()
    have = set(words(resume)) | set(phrases(resume))

    c = Counter(w for w in words(jd_raw)
                if w not in STOP and w not in NOISE and len(w) > 3)
    c.update(p for p in phrases(jd_raw)
             if not any(x in NOISE for x in p.split()))
    top = [w for w, n in c.most_common(a.top * 3)][:a.top]

    covered, placeable, rephrase, missing = [], [], [], []
    for t in top:
        if t in have:
            covered.append(t)
        elif any(t in s or s in t for s in skill_pool):
            placeable.append((t, "skills line"))
        elif any(t in s or s in t for s in course_pool):
            placeable.append((t, "coursework line"))
        elif any(t == v or t in v or v in t for v in vocab):
            placeable.append((t, "bullet wording, he has earned this word"))
        elif any(alt in have for alt in SYNONYMS.get(t, [])):
            rephrase.append((t, [alt for alt in SYNONYMS.get(t, []) if alt in have][0]))
        else:
            missing.append(t)

    pct = round(100 * len(covered) / max(1, len(top)))
    print(f"JD terms considered: {len(top)}")
    print(f"ALREADY COVERED: {len(covered)}  ({pct}%)")
    print("   ", ", ".join(covered[:22]))
    print()
    if placeable:
        print(f"PLACEABLE, true and in his pools, add these ({len(placeable)}):")
        for t, where in placeable:
            print(f"    {t:<28} -> {where}")
        print()
    if rephrase:
        print(f"REPHRASE, he says it a different way, match the JD wording ({len(rephrase)}):")
        for t, cur in rephrase:
            print(f"    {t:<28} he currently writes {cur!r}")
        print()
    print(f"NOT AVAILABLE, do not fake these ({len(missing)}):")
    print("   ", ", ".join(missing[:25]))
    print()
    potential = round(100 * (len(covered) + len(placeable) + len(rephrase)) / max(1, len(top)))
    print(f"Coverage now {pct}%, achievable honestly {potential}%")


if __name__ == "__main__":
    main()
