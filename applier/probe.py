#!/usr/bin/env python3
"""
Discovery step. Runs in WSL2. Given a job URL it answers three questions:

  1. Is this reachable at all, or is it dead / captcha'd / login-walled?
  2. Which application platform is it, and what is the real apply URL?
  3. What controls does the application form have?

    python probe.py <url> [--out /path/dir] [--follow-apply]

Prints one JSON object on stdout. Progress goes to stderr.
This is what gets handed to the model when a platform has no recipe yet.
"""
import sys, os, json, re

from playwright.sync_api import sync_playwright


def note(*a):
    print(*a, file=sys.stderr, flush=True)


PLATFORMS = [
    ("greenhouse",   r"greenhouse\.io"),
    ("lever",        r"jobs\.lever\.co"),
    ("ashby",        r"jobs\.ashbyhq\.com|ashbyhq\.com"),
    ("workday",      r"myworkdayjobs\.com|workday\.com"),
    ("icims",        r"icims\.com"),
    ("successfactors", r"successfactors\.|sapsf\.com|jobs\.sap\.com"),
    ("smartrecruiters", r"smartrecruiters\.com"),
    ("taleo",        r"taleo\.net"),
    ("oracle_hcm",   r"oraclecloud\.com/hcmUI|/hcmUI/CandidateExperience"),
    ("phenom",       r"careers\.[a-z0-9-]+\.com/.*/job/"),
    ("teamtailor",   r"teamtailor\.com"),
    ("tal_net",      r"tal\.net"),
    ("eightfold",    r"eightfold\.ai|\.eightfold\."),
    ("jobvite",      r"jobvite\.com"),
]

BLOCKERS = [
    ("captcha",       r"recaptcha|hcaptcha|cf-turnstile|are you a robot|verify you are human"),
    ("cloudflare",    r"cloudflare|checking your browser|ray id"),
    ("login_wall",    r"sign in to continue|please log in to apply|create an account to apply"),
    ("dead",          r"no longer accepting|position (has been )?(filled|closed)|job (is )?no longer available|"
                      r"we can.t find that page|posting (has )?expired|404"),
]

ALL_CONTROLS = """() => {
  const out = [];
  const labelFor = el => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return l.innerText.trim();
    }
    const w = el.closest('label');
    if (w) return w.innerText.trim();
    const c = el.closest('[class*=field],[class*=question],fieldset,div');
    if (c) { const l2 = c.querySelector('label,legend'); if (l2) return l2.innerText.trim(); }
    return '';
  };
  document.querySelectorAll('input,select,textarea,[role=combobox]').forEach(el => {
    if (el.type === 'hidden') return;
    if (!el.offsetParent && el.type !== 'file') return;
    let options = [];
    if (el.tagName === 'SELECT') {
      options = Array.from(el.options).map(o => o.text.trim()).filter(Boolean).slice(0, 40);
    }
    out.push({
      id: el.id || '',
      name: el.name || '',
      kind: el.tagName.toLowerCase() + ':' + (el.type || el.getAttribute('role') || ''),
      label: (labelFor(el) || '').replace(/\\s+/g, ' ').slice(0, 130),
      placeholder: el.placeholder || '',
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      combobox: el.getAttribute('role') === 'combobox' || !!el.getAttribute('aria-autocomplete'),
      ariaControls: el.getAttribute('aria-controls') || '',
      options: options
    });
  });
  return out;
}"""

APPLY_LINKS = """() => Array.from(document.querySelectorAll('a,button'))
  .filter(e => /apply/i.test(e.innerText || e.getAttribute('aria-label') || ''))
  .slice(0, 12)
  .map(e => ({text: (e.innerText || '').trim().slice(0, 50),
              href: e.tagName === 'A' ? (e.href || '') : '',
              tag: e.tagName}))"""

CHECKBOXES = """() => Array.from(document.querySelectorAll('input[type=checkbox],input[type=radio]'))
  .filter(e => e.offsetParent !== null)
  .slice(0, 60)
  .map(e => {
    const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
    const t = ((l ? l.innerText : '') || (e.closest('label') || {}).innerText || '').trim();
    return {type: e.type, id: e.id || '', name: e.name || '', label: t.replace(/\\s+/g, ' ').slice(0, 110)};
  })"""


def detect_platform(url, html):
    for name, pat in PLATFORMS:
        if re.search(pat, url, re.I):
            return name
    for name, pat in PLATFORMS:
        if re.search(pat, html[:400000], re.I):
            return name + "?"
    return "unknown"


def detect_blockers(text, html):
    hits = []
    blob = (text + " " + html[:200000]).lower()
    for name, pat in BLOCKERS:
        if re.search(pat, blob, re.I):
            hits.append(name)
    return hits


def snapshot(pg, tag, out_dir):
    html = pg.content()
    text = pg.inner_text("body")
    controls = pg.evaluate(ALL_CONTROLS)
    data = {
        "tag": tag,
        "url": pg.url,
        "title": pg.title(),
        "platform": detect_platform(pg.url, html),
        "blockers": detect_blockers(text, html),
        "controls": controls,
        "checkboxes": pg.evaluate(CHECKBOXES),
        "apply_links": pg.evaluate(APPLY_LINKS),
        "submit_buttons": pg.evaluate(
            """() => Array.from(document.querySelectorAll('button,input[type=submit]'))
                 .filter(e => e.offsetParent !== null)
                 .map(e => ((e.innerText || e.value || '').trim() + ' [' + (e.type || '') + ']'))
                 .filter(s => s.length > 3).slice(0, 25)"""),
        "text_head": text[:3000],
    }
    if out_dir:
        pg.screenshot(path=os.path.join(out_dir, f"probe_{tag}.png"), full_page=True)
        open(os.path.join(out_dir, f"probe_{tag}.html"), "w", encoding="utf-8").write(html)
    note(f"[{tag}] {data['platform']:<16} controls={len(controls)} "
         f"blockers={data['blockers'] or 'none'}  {pg.url[:90]}")
    return data


def main():
    url = sys.argv[1]
    out_dir = ""
    if "--out" in sys.argv:
        out_dir = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out_dir, exist_ok=True)
    follow = "--follow-apply" in sys.argv

    result = {"input_url": url, "steps": [], "error": ""}

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1400, "height": 1300},
                            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"))
        pg = ctx.new_page()
        pg.set_default_timeout(45000)
        try:
            r = pg.goto(url, wait_until="domcontentloaded")
            result["http_status"] = r.status if r else None
            pg.wait_for_timeout(6000)
            first = snapshot(pg, "landing", out_dir)
            result["steps"].append(first)

            if follow and len(first["controls"]) < 6:
                target = None
                for a in first["apply_links"]:
                    if a["href"] and "mailto" not in a["href"]:
                        target = a["href"]
                        break
                if target:
                    note("following apply link ->", target[:110])
                    pg.goto(target, wait_until="domcontentloaded")
                    pg.wait_for_timeout(7000)
                    result["steps"].append(snapshot(pg, "apply", out_dir))
                else:
                    for a in first["apply_links"]:
                        if a["tag"] == "BUTTON":
                            try:
                                pg.get_by_role("button", name=re.compile("apply", re.I)).first.click(timeout=12000)
                                pg.wait_for_timeout(8000)
                                result["steps"].append(snapshot(pg, "apply_click", out_dir))
                            except Exception as e:
                                note("apply click failed:", type(e).__name__)
                            break
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            note("ERROR", result["error"])
        finally:
            ctx.close()
            b.close()

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
