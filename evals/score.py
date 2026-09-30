#!/usr/bin/env python3
"""
Score one agent run from its Claude Code stream-json log, with the same code
for every configuration, so the comparison is not done by eye.

    python score.py <log.jsonl> [<label>]

Metrics (standard agent-eval categories):
  success        reached ready-to-submit (or submitted) per the engine's own status
  interventions  times the run stopped for Joaquin (needs_you stages, or open
                 questions it listed at the end of an unattended run)
  seconds, turns, tool_calls, cost_usd   efficiency, from the log's result event
  unfilled       required fields the engine reported as unknown at the end
  violations     guardrail breaks in what was typed: a visa answer that does
                 not match ANSWERS.json, an em dash, or a mention of AI
"""
import json, os, re, sys

ANSWERS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                      "Application Agent", "applier", "ANSWERS.json"), encoding="utf-8"))
VISA = {str(v).strip().lower() for v in ANSWERS.get("work_authorization", {}).values() if isinstance(v, str)}


def events(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                pass


def fill_results(evs):
    """Every JSON object fill.py / apply.py printed, as seen in tool results."""
    out = []
    for e in evs:
        if e.get("type") != "user":
            continue
        for c in e.get("message", {}).get("content", []):
            if c.get("type") != "tool_result":
                continue
            body = c.get("content")
            text = body if isinstance(body, str) else " ".join(x.get("text", "") for x in body or [] if isinstance(x, dict))
            for m in re.finditer(r"\{\"(url|status)\".*?\}(?=\s*$)", text, re.S):
                try:
                    d = json.loads(m.group(0))
                    if "status" in d:
                        out.append(d)
                except ValueError:
                    pass
    return out


def run_dir_results(run_dir):
    """Engine results an agent saved to files instead of printing (result*.json),
    oldest first, so the last one is the final state."""
    if not run_dir or not os.path.isdir(run_dir):
        return []
    files = sorted((f for f in os.listdir(run_dir) if f.startswith("result") and f.endswith(".json")),
                   key=lambda f: os.path.getmtime(os.path.join(run_dir, f)))
    return [json.load(open(os.path.join(run_dir, f), encoding="utf-8")) for f in files]


def score(path, label="", run_dir=None):
    evs = list(events(path))
    tools = [c for e in evs if e.get("type") == "assistant" for c in e.get("message", {}).get("content", [])
             if c.get("type") == "tool_use"]
    res = next((e for e in reversed(evs) if e.get("type") == "result"), {})
    final = str(res.get("result", ""))
    fills = fill_results(evs) or run_dir_results(run_dir)
    last = fills[-1] if fills else {}
    status = last.get("status", "none")
    required_unfilled = [u.get("label", "")[:60] for u in last.get("unknown_fields", [])
                         if u.get("required") and u.get("kind") != "input:file"]
    stops = [s.get("label", "")[:60] for s in last.get("stops", [])]
    stage_asks = sum(1 for c in tools if "stage.py" in json.dumps(c.get("input", {})) and "needs_you" in json.dumps(c.get("input", {})))
    # an unattended run that ends with questions for Joaquin needed him that many times
    asked = len(re.findall(r"(?im)^\s*(?:\d+[.)]|[-*])\s+.*\?\s*$", final))
    typed = [str(a.get("value", "")) for a in last.get("audit", []) if isinstance(a, dict)]
    violations = []
    for v in typed:
        if re.search(r"\breferral\b", v, re.I) and not ANSWERS.get("how_did_you_hear", {}).get("referrals"):
            violations.append(f"claimed a referral that does not exist: {v[:40]}")
        if "—" in v:
            violations.append(f"em dash: {v[:40]}")
        if re.search(r"\b(chatgpt|claude|an ai|automated tool|agent submitted)\b", v, re.I):
            violations.append(f"AI mention: {v[:40]}")
    for a in last.get("audit", []):
        if isinstance(a, dict) and re.search(r"sponsor|authori[sz]ed to work|citizen", a.get("label", ""), re.I):
            if str(a.get("value", "")).strip().lower() not in VISA and a.get("how") in ("ok", "picked", "matched"):
                violations.append(f"visa answer not from ANSWERS.json: {a.get('label','')[:40]}")
    # The engine only knows the confirmation phrases in its recipe. When it says
    # "submitted_unconfirmed", the agent's quoted confirmation from the page counts.
    quoted = re.search(r"(?i)\"[^\"]*(thank|received|applying)[^\"]*\"", final)
    if status == "submitted_unconfirmed" and quoted:
        status = "submitted (confirmed by the agent from the page)"
    success = (status.startswith("submitted") and "unconfirmed" not in status or status == "filled_not_submitted") \
        and not required_unfilled and not stops
    return {
        "label": label or os.path.basename(path),
        "success": success,
        "engine_status": status,
        "engine_runs": len(fills),
        "interventions": max(stage_asks, asked, len(stops) + (1 if required_unfilled else 0) if not success else 0),
        "seconds": round((res.get("duration_ms") or 0) / 1000),
        "turns": res.get("num_turns"),
        "tool_calls": len(tools),
        "cost_usd": round(res.get("total_cost_usd") or 0, 2),
        "required_unfilled": required_unfilled,
        "stops": stops,
        "violations": violations,
        "final_message": final[:400],
    }


if __name__ == "__main__":
    a = sys.argv[1:] + ["", ""]
    print(json.dumps(score(a[0], a[1], a[2] or None), indent=1, ensure_ascii=False))
