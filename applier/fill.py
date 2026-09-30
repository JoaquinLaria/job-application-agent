#!/usr/bin/env python3
"""
Recipe-driven form filler. Runs inside WSL2 Ubuntu where Chromium is stable.

    python fill.py job.json

Handles both shapes of application form:

  single page   recipe has "fields" at the top level      (Greenhouse, Lever, Ashby)
  multi step    recipe has "steps": {stepname: {...}}      (Phenom, Workday, iCIMS)

On a multi-step form it walks forward. A step the recipe knows gets filled and
advanced. A step it does not know gets dumped and the run stops with status
"unknown_step". That dump is what the model turns into a new recipe block, and
after that the step is free forever.

job.json is written by apply.py:
{
  "url":     "...",
  "recipe":  {...},
  "answers": {...ANSWERS.json...},
  "files":   {"resume_pdf": "/mnt/c/.../resume.pdf", "cover_pdf": "/mnt/c/.../cover.pdf"},
  "submit":  false,
  "out_dir": "/mnt/c/.../run"
}

One JSON object goes to stdout. Human-readable progress goes to stderr.
"""
import sys, os, json, re, difflib

# APPLIER_BASELINE=1 reproduces the Homework 1 engine for evaluation only:
# no label matcher on single-page forms, GPA is a hard stop, no Gmail read.
# Never set it for a real application.
BASELINE = os.environ.get("APPLIER_BASELINE") == "1"
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

MAX_STEPS = 14


def note(*a):
    print(*a, file=sys.stderr, flush=True)


def css_escape(fid):
    """Ids like question_2874[] or cntryFields.firstName break CSS selectors."""
    out = []
    for ch in fid:
        if ch in "[]().:#$&*+,/;<=>?@^`{|}~!'\"%":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def sel_id(fid):
    """Selector for an element id. NOT '#id': a CSS id cannot start with a digit,
    and Avature numbers its fields (8152, 12917), so '#8152' is invalid and every
    lookup silently fails. The attribute form works for any id."""
    return '[id="' + fid.replace(chr(92), chr(92) * 2).replace('"', chr(92) + '"') + '"]'


def resolve(answers, path):
    """'identity.first_name' -> answers['identity']['first_name']"""
    if not path:
        return None
    # "today.%m/%d/%y" -> today's date in that format. A stored date goes stale.
    if path.startswith("today."):
        import datetime
        return datetime.date.today().strftime(path[len("today."):])
    cur = answers
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# Options belonging to THIS field only, via aria-controls. A global
# [role=option] query picks up the phone country-code list, which sits
# permanently in the DOM and poisons every other field.
SCOPED_OPTIONS = """(fid) => {
  const inp = document.getElementById(fid);
  if (!inp) return {err: 'input not found'};
  if (inp.tagName === 'SELECT') {
    return {native: true, opts: Array.from(inp.options).map(o => o.text.trim()).filter(Boolean)};
  }
  const listId = inp.getAttribute('aria-controls') || inp.getAttribute('aria-owns');
  let box = listId ? document.getElementById(listId) : null;
  if (!box) {
    const c = inp.closest('[class*=select], [class*=combobox], [class*=autocomplete]');
    box = c ? c.querySelector('[role=listbox], ul') : null;
  }
  if (!box) return {err: 'listbox not found', listId: listId};
  const opts = Array.from(box.querySelectorAll('[role=option], li'))
      .map(e => e.innerText.trim()).filter(Boolean);
  return {listId: listId, boxSelector: listId ? ('#' + listId) : null, opts: opts};
}"""

ALL_CONTROLS = """() => {
  const out = [];
  const labelFor = el => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return l.innerText.trim();
    }
    const w = el.closest('label');
    if (w) return w.innerText.trim();
    const c = el.closest('[class*=field],[class*=question],fieldset');
    if (c) { const l2 = c.querySelector('label,legend'); if (l2) return l2.innerText.trim(); }
    return '';
  };
  document.querySelectorAll('input,select,textarea,[role=combobox]').forEach(el => {
    if (el.type === 'hidden') return;
    if (!el.offsetParent && el.type !== 'file') return;
    let options = [];
    if (el.tagName === 'SELECT') {
      options = Array.from(el.options).map(o => o.text.trim()).filter(Boolean).slice(0, 60);
    }
    out.push({
      id: el.id || '', name: el.name || '',
      kind: el.tagName.toLowerCase() + ':' + (el.type || el.getAttribute('role') || ''),
      label: (labelFor(el) || '').replace(/\\s+/g, ' ').slice(0, 130),
      placeholder: el.placeholder || '',
      // Greenhouse marks required with a red asterisk in a SIBLING node, so
      // el.required is false on fields the form will refuse to submit without.
      // Look at the surrounding block for an asterisk or the word required.
      required: (function () {
        if (el.required || el.getAttribute('aria-required') === 'true') return true;
        const box = el.closest('[class*=field],[class*=question],fieldset,div');
        if (!box) return false;
        const t = (box.innerText || '').slice(0, 400);
        return /\\*/.test(t) || /this field is required|required\\s*$/im.test(t);
      })(),
      combobox: el.getAttribute('role') === 'combobox'
                || el.getAttribute('aria-autocomplete') === 'list'
                || !!el.getAttribute('aria-controls')
                || /select__input|react-select/.test(
                     (el.className && el.className.toString) ? el.className.toString() : '')
                || !!el.closest('[class*="select__control"], [class*="react-select"]'),
      options: options,
      value: (el.tagName === 'SELECT'
                ? (el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '')
                : (el.value || '')).slice(0, 160)
    });
  });
  return out;
}"""

CHECKBOX_DUMP = """() => Array.from(document.querySelectorAll('input[type=checkbox],input[type=radio]'))
  .filter(e => e.offsetParent !== null).slice(0, 80)
  .map(e => {
    const l = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
    const t = ((l ? l.innerText : '') || (e.closest('label') || {}).innerText || '').trim();
    return {type: e.type, id: e.id || '', name: e.name || '',
            label: t.replace(/\\s+/g, ' ').slice(0, 130), checked: e.checked};
  })"""

VALIDATION_ERRORS = """() => Array.from(document.querySelectorAll(
    '[class*=error],[class*=Error],[role=alert],[aria-invalid=true]'))
  .filter(e => e.offsetParent !== null)
  .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '))
  .filter(t => t.length > 2 && t.length < 200).slice(0, 15)"""


# Label to answer map. This is what makes an unseen form mostly fill itself:
# the wording of these questions is near-identical across every ATS.
# Order matters, first match wins, so put the specific patterns above the loose ones.
LABEL_MAP = [
    # Screening questions Joaquin answered once (screening_defaults, 2026-09-29).
    # A run stopped to ask him every one of these, so they come first.
    (r"pursuing.{0,60}(mba|master)|(mba|master).{0,60}(2027|graduat)", "screening_defaults.currently_pursuing_mba_graduating_2027"),
    (r"what school|school do you.{0,20}attend|where did you graduate", "screening_defaults.school_info"),
    (r"\bgpa\b|grade point average",                                   "screening_defaults.gpa_text"),
    (r"do you have.{0,40}years",                                        "screening_defaults.has_4_to_7_years_experience"),
    (r"in.?office|on.?site|in.?person|in the office|hybrid role|work (at|from) (our|the) .{0,30}office", "screening_defaults.willing_to_work_in_office"),
    # Company C, 2026-09-29: Joaquin confirmed these; the SMS line must beat "phone number".
    (r"marketing communications|marketing e.?mails",             "screening_defaults.marketing_communications_opt_in"),
    (r"text messages|\bsms\b",                                   "screening_defaults.sms_text_consent"),
    (r"finra",                                                   "screening_defaults.finra_licenses"),
    (r"deloitte|external (financial )?auditor",                  "screening_defaults.auditor_employee_ever"),
    (r"are you currently an? .{0,60}employee\b",                 "screening_defaults.current_employee_of_company"),
    (r"reasonable commute|planning to relocate",                 "screening_defaults.within_commute_or_relocate"),
    (r"today'?s date|date of application",                       "today.%m/%d/%y"),
    (r"two or more races",                                       "eeo.two_or_more_races_detail"),

    (r"legally (authorized|entitled|eligible) to work|authorized to (lawfully )?work|lawfully work|eligible to work legally", "work_authorization.legally_authorized_us"),
    (r"(require|need).{0,25}(visa )?sponsorship",                "work_authorization.require_sponsorship"),
    (r"(now or in the future).{0,30}sponsor",                    "work_authorization.require_sponsorship"),
    (r"permanent.{0,20}work authorization",                      "work_authorization.permanent_us_authorization"),
    (r"security clearance",                                      "work_authorization.security_clearance"),
    (r"(are you|at least).{0,15}18 years",                       "work_authorization.over_18"),
    (r"convicted.{0,25}(felony|crime)",                          "work_authorization.convicted_felony"),
    (r"non.?compete",                                            "work_authorization.non_compete"),

    (r"first name",                                              "identity.first_name"),
    (r"last name|surname|family name",                           "identity.last_name"),
    (r"preferred name",                                          "identity.preferred_name"),
    (r"(e.?mail)",                                               "identity.email"),
    (r"phone number",                                            "identity.phone_digits"),
    (r"linked.?in",                                              "identity.linkedin_full"),
    (r"github",                                                  "identity.github"),
    (r"(personal )?website|portfolio",                           "identity.website"),
    (r"address line 1|street address|^address",                "identity.address_line1"),
    # "Location (City)" autocompletes offer a same-named foreign city first for a plain city name.
    (r"^location\b",                                             "identity.location_city"),
    (r"^city$|city",                                             "identity.city"),
    # country BEFORE state: "Country/Region" contains "Region" and was being
    # read as the state field, which then rejected "Massachusetts".
    (r"country\s*/?\s*region|^country|country of residence|address country", "identity.country"),
    (r"^state|province|^state/|address state",                 "identity.state"),
    (r"(postal|zip) ?code",                                      "identity.zip"),

    (r"(school|university|college|institution) name|^school",    "education.grad_school"),
    (r"^degree|degree (type|level)",                             "education.grad_degree"),
    (r"(field|area) of study|major|discipline",                  "education.grad_discipline"),
    (r"(expected )?graduation (date|term|year)",                 "education.graduation_term"),

    (r"(desired|expected|salary) (salary|compensation)|salary expectation", "compensation.salary_expectation"),
    (r"(available |earliest )?start date|when can you start",    "compensation.start_date_text"),
    (r"willing to relocate|open to relocation",                  "compensation.willing_to_relocate"),
    (r"willing to travel",                                       "compensation.willing_to_travel"),
    (r"notice period",                                           "compensation.notice_period"),

    (r"hispanic|latino",                                         "eeo.hispanic_latino"),
    (r"^gender|gender identity",                                 "eeo.gender"),
    (r"race|ethnicit",                                           "eeo.race_ethnicity"),
    (r"veteran",                                                 "eeo.veteran_status"),
    (r"disab",                                                   "eeo.disability_status"),
    (r"first.?generation",                                       "eeo.first_generation"),

    (r"(previously |ever )?(worked|employed).{0,25}(here|for us|at .{0,25})", "misc.worked_here_before"),
    (r"related to.{0,20}employee|relative.{0,20}employ",         "misc.related_to_employee"),
    (r"how did you hear",                                        "how_did_you_hear.ranked"),
    (r"languages?",                                              "misc.languages"),
]

# Questions we must never answer from a guess, no matter how the label is worded.
NEVER_GUESS = [
    # GPA used to be here. The applicant chose a 4.0-scale figure on 2026-09-29; it now lives
    # in screening_defaults.gpa_text and is answered by LABEL_MAP.
    (r"criminal|conviction record|background check consent",
     "Legal declaration. Joaquin answers this himself."),
    (r"salary history|current (salary|compensation)",
     "Salary history. Illegal to ask in several states and his to disclose, not mine."),
]


def guess_answer_key(label):
    if BASELINE and re.search(r"gpa|grade point average", (label or "").lower()):
        return None, "Joaquin's GPA is <undergrad GPA> on the Argentine scale. He must pick. (HW1 rule)"
    return _guess_answer_key(label)


def _guess_answer_key(label):
    """Which answer does this label want. Returns (key, None) or (None, stop_reason)."""
    t = (label or "").strip().lower()
    if not t:
        return None, None
    for pat, reason in NEVER_GUESS:
        if re.search(pat, t):
            return None, reason
    for pat, key in LABEL_MAP:
        if re.search(pat, t):
            return key, None
    return None, None


# What a control REALLY is, read from the DOM before touching it.
#
# This exists because of a silent failure on the Company I board: nine required
# questions were react-select dropdowns that a plain DOM scan reports as
# input:text. Typing into one fills its search box, selects nothing, and the
# form raises no error. The recipe said "text" and the engine believed it.
# Now the engine checks and overrides.
#
# react-select gives itself away statically: class select__input, role combobox,
# aria-autocomplete list, and an ancestor with class select__control. A genuine
# Greenhouse text input has class "input input__single-line" and no role.
CLASSIFY = """(ids) => {
  const out = {};
  ids.forEach(id => {
    const e = document.getElementById(id);
    if (!e) { out[id] = 'missing'; return; }
    const tag = e.tagName;
    if (tag === 'SELECT')   { out[id] = 'select'; return; }
    if (tag === 'TEXTAREA') { out[id] = 'text'; return; }
    const t = e.type || '';
    if (t === 'file')     { out[id] = 'file'; return; }
    if (t === 'checkbox') { out[id] = 'checkbox'; return; }
    if (t === 'radio')    { out[id] = 'radio'; return; }
    const cls = (e.className && e.className.toString) ? e.className.toString() : '';
    const looksSelect =
        e.getAttribute('role') === 'combobox' ||
        e.getAttribute('aria-autocomplete') === 'list' ||
        !!e.getAttribute('aria-controls') ||
        !!e.getAttribute('aria-owns') ||
        /select__input|react-select/.test(cls) ||
        !!e.closest('[class*="select__control"], [class*="react-select"]');
    out[id] = looksSelect ? 'autocomplete' : 'text';
  });
  return out;
}"""


class Filler:
    """Fills one page or one step of a form from a recipe block."""

    def __init__(self, pg, answers, files):
        self.pg = pg
        self.answers = answers
        self.files = files
        self.audit = []
        self.problems = []
        self.stops = []
        self.touched = set()
        self.intended = {}

    def log(self, field, value, how, label=""):
        if how in ("ok", "picked", "matched"):
            self.intended[field] = str(value)
        self.audit.append({"field": field, "value": str(value)[:90], "how": how, "label": label})
        mark = "  " if how in ("ok", "picked", "matched", "uploaded", "ticked", "skipped") else "!!"
        note(f"   {mark} {field[:34]:<34} = {str(value)[:40]:<40} [{how}]")

    # -- primitives -----------------------------------------------------------
    def do_text(self, fid, spec, value):
        el = self.pg.locator(sel_id(fid))
        el.scroll_into_view_if_needed(timeout=8000)
        el.fill(str(value), timeout=8000)
        self.log(fid, value, "ok", spec.get("label", ""))

    def do_file(self, fid, spec):
        key = spec.get("upload")
        path = self.files.get(key)
        if not path:
            self.problems.append(f"{fid}: no file supplied for '{key}'")
            self.log(fid, key, "FAILED", spec.get("label", ""))
            return
        if not os.path.exists(path):
            self.problems.append(f"{fid}: file missing on disk: {path}")
            self.log(fid, path, "FAILED", spec.get("label", ""))
            return
        sel = spec.get("selector") or (sel_id(fid))
        # Read the page back after every upload. On Company D (2026-09-30) the log said
        # "uploaded" while the page showed "Cannot read properties of undefined
        # (reading 'uploadFile')" under both files: a false success.
        err = ""
        for attempt in (1, 2):
            self.pg.locator(sel).first.set_input_files(path, timeout=25000)
            self.pg.wait_for_timeout(spec.get("wait_ms", 2500) * attempt)
            err = self.upload_error(sel)
            if not err:
                self.log(fid, os.path.basename(path), "uploaded", spec.get("label", ""))
                return
            note(f"   !! upload {fid} rejected by the page ({err[:70]}), attempt {attempt}")
        self.problems.append(f"{fid}: upload rejected by the page: {err[:120]}")
        self.log(fid, os.path.basename(path), "FAILED", spec.get("label", ""))

    def upload_error(self, sel):
        """Error text the page shows next to an upload box, or '' if none."""
        try:
            return self.pg.evaluate("""(sel) => {
              const e = document.querySelector(sel); if (!e) return '';
              const b = e.closest('[class*=field],[class*=question],[class*=upload],fieldset') || e.parentElement;
              const t = ((b && b.innerText) || '');
              const m = t.match(/(cannot read properties[^\\n]*|upload failed[^\\n]*|file (is )?too large[^\\n]*|invalid file[^\\n]*)/i);
              return m ? m[0] : ''; }""", sel)
        except Exception:
            return ""

    def do_react(self, fid, spec, value):
        """Write through React's own value setter. Date pickers and other
        controlled inputs silently discard a plain fill() and snap back."""
        v = str(value)
        ok = self.pg.evaluate("""([fid, v]) => {
          const el = document.getElementById(fid);
          if (!el) return 'missing';
          const proto = el.tagName === 'TEXTAREA'
              ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          el.focus();
          setter.call(el, v);
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          el.blur();
          return el.value === v ? 'ok' : ('got:' + el.value);
        }""", [fid, v])
        if ok == "ok":
            self.log(fid, v, "ok", spec.get("label", ""))
        else:
            self.problems.append(f"{fid}: date write rejected ({ok})")
            self.log(fid, v, "FAILED", spec.get("label", ""))

    # Many modern forms build a dropdown out of a span or div with no id at all.
    # Avature's Area of Interest and Degree Type, BCG's Gender. They can only be
    # addressed by their visible label, so this marks the right node from JS and
    # then drives it like any other combobox.
    MARK_BY_LABEL = """([labelText, idx]) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const want = norm(labelText);
      document.querySelectorAll('[data-applier-target]').forEach(
          e => e.removeAttribute('data-applier-target'));
      const nodes = Array.from(document.querySelectorAll(
          '[role=combobox],[role=listbox],select,input,textarea'));
      let seen = 0;
      for (const e of nodes) {
        if (!e.offsetParent) continue;
        let t = '';
        const w = e.closest('label');
        if (w) t = norm(w.innerText);
        if (!t) {
          // walk up until a container actually holds a label. Stopping at the
          // first ancestor finds an inner wrapper with no label and gives up.
          let n = e.parentElement, hops = 0;
          while (n && hops < 7 && !t) {
            const l = n.querySelector('label, legend, [class*=label]');
            if (l) {
              const cand = norm(l.innerText);
              if (cand) t = cand;
            }
            n = n.parentElement; hops++;
          }
        }
        if (!t) continue;
        if (!(t.startsWith(want) || t.includes(want))) continue;
        if (seen++ < idx) continue;
        e.setAttribute('data-applier-target', '1');
        return {tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', label: t.slice(0, 80)};
      }
      return null;
    }"""

    OPEN_OPTIONS = """() => Array.from(document.querySelectorAll(
        '[role=option], [role=listbox] li, ul[class*=option] li, [class*=dropdown] li'))
      .filter(e => e.offsetParent !== null)
      .map(e => (e.innerText || '').trim())
      .filter(t => t && t.length < 120).slice(0, 200)"""

    def do_label_combobox(self, fid, spec, value):
        """Address a dropdown by its visible label. For widgets with no id."""
        pg = self.pg
        label = spec.get("by_label") or fid.split(":", 1)[-1]
        idx = spec.get("index", 0)
        found = pg.evaluate(self.MARK_BY_LABEL, [label, idx])
        if not found:
            self.problems.append(f"{fid}: no control found under a label starting {label!r}")
            self.log(fid, label, "FAILED", spec.get("label", ""))
            return
        el = pg.locator('[data-applier-target="1"]').first
        el.scroll_into_view_if_needed(timeout=8000)
        if found["tag"] == "select":
            return self.do_select_locator(fid, spec, value, el)
        el.click(timeout=8000)
        pg.wait_for_timeout(spec.get("wait_ms", 1200))
        opts = pg.evaluate(self.OPEN_OPTIONS)
        if not opts:
            try:
                el.type(str(value)[:30], delay=60)
                pg.wait_for_timeout(1400)
                opts = pg.evaluate(self.OPEN_OPTIONS)
            except Exception:
                pass
        if not opts:
            self.problems.append(f"{fid}: opened but no options appeared")
            self.log(fid, value, "FAILED", spec.get("label", ""))
            pg.keyboard.press("Escape")
            return
        candidates = spec.get("accept") or ([str(value)] if value is not None else [])
        chosen = self.pick(fid, spec, value, candidates, opts)
        if chosen is None:
            pg.keyboard.press("Escape")
            return
        try:
            pg.get_by_role("option", name=chosen, exact=True).first.click(timeout=6000)
        except Exception:
            pg.get_by_text(chosen, exact=True).first.click(timeout=8000)
        pg.wait_for_timeout(500)
        self.log(fid, chosen, "picked", spec.get("label", label))

    # select2 (jQuery) renders a span with role=combobox and hides the real
    # <select>. There is no id and no <label>: the only reliable handle is the
    # text immediately before the widget in reading order, which is exactly what
    # a human reads as its label. Avature uses this for University, Degree Type,
    # Major and Area of Interest, twice over for two education rows.
    MARK_SELECT2 = """([labelText, idx]) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const want = norm(labelText).toLowerCase();
      document.querySelectorAll('[data-applier-s2]').forEach(
          e => e.removeAttribute('data-applier-s2'));
      const widgets = Array.from(document.querySelectorAll(
          'span[role=combobox], div[role=combobox]')).filter(e => e.offsetParent);

      // PASS 1: the text immediately before the widget. This is what a person
      // reads as its label and it works for the first of a repeated group.
      let seen = 0;
      for (const e of widgets) {
        let before = '', n = e;
        for (let hops = 0; hops < 6 && !before; hops++) {
          let sib = n.previousElementSibling;
          while (sib && !before) { before = norm(sib.innerText).slice(-90); sib = sib.previousElementSibling; }
          n = n.parentElement; if (!n) break;
        }
        if (!before.toLowerCase().includes(want)) continue;
        if (seen++ < idx) continue;
        e.setAttribute('data-applier-s2', '1');
        return {via: 'before', before: before.slice(0, 90), current: norm(e.innerText).slice(0, 60)};
      }

      // PASS 2, for a second or third repeated row. Once row one is filled, the
      // text before row two's widget is row one's SELECTED VALUE, so pass 1
      // cannot see it. Anchor on the label nodes instead, which do not move.
      const labels = widgets.length ? Array.from(document.querySelectorAll('*'))
        .filter(e => e.offsetParent && e.children.length === 0
                     && norm(e.innerText).toLowerCase().includes(want)) : [];
      seen = 0;
      for (const lab of labels) {
        const w = widgets.find(x =>
          lab.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (!w) continue;
        if (seen++ < idx) continue;
        w.setAttribute('data-applier-s2', '1');
        return {via: 'label', label: norm(lab.innerText).slice(0, 60),
                current: norm(w.innerText).slice(0, 60), labelsFound: labels.length};
      }
      return null;
    }"""

    S2_RESULTS = """() => Array.from(document.querySelectorAll(
        '.select2-results__option, li.select2-results__option'))
      .filter(e => e.offsetParent !== null)
      .map(e => (e.innerText || '').trim())
      .filter(t => t && !/^searching|^no results/i.test(t)).slice(0, 120)"""

    def do_select2(self, fid, spec, value):
        pg = self.pg
        label = spec.get("after_text") or fid.split(":", 1)[-1]
        idx = spec.get("index", 0)
        found = pg.evaluate(self.MARK_SELECT2, [label, idx])
        if not found:
            self.problems.append(f"{fid}: no select2 widget found after text {label!r} (index {idx})")
            self.log(fid, label, "FAILED", spec.get("label", ""))
            return
        el = pg.locator('[data-applier-s2="1"]').first
        el.scroll_into_view_if_needed(timeout=8000)
        el.click(timeout=8000)
        pg.wait_for_timeout(700)

        candidates = spec.get("accept") or ([str(value)] if value is not None else [])
        # select2 opens its own search box at document level
        # scope the search box to the OPEN container. A page with several select2
        # widgets keeps a hidden search input for each one, so .last picks a stale box.
        search = pg.locator(".select2-container--open .select2-search__field").first
        if candidates:
            try:
                if search.count() and search.is_visible(timeout=1200):
                    search.type(str(candidates[0])[:28], delay=55)
                    pg.wait_for_timeout(spec.get("wait_ms", 1600))
            except Exception:
                pass
        opts = pg.evaluate(self.S2_RESULTS)
        if not opts:
            pg.wait_for_timeout(1800)
            opts = pg.evaluate(self.S2_RESULTS)
        if not opts and candidates:
            # remote-loaded lists need a shorter query before they return anything
            try:
                search.fill("", timeout=2000)
                search.type(str(candidates[0])[:6], delay=90)
                pg.wait_for_timeout(2200)
                opts = pg.evaluate(self.S2_RESULTS)
            except Exception:
                pass
        if not opts:
            self.problems.append(f"{fid}: select2 opened but offered nothing")
            self.log(fid, value, "FAILED", spec.get("label", ""))
            pg.keyboard.press("Escape")
            return
        chosen = self.pick(fid, spec, value, candidates, opts)
        if chosen is None:
            pg.keyboard.press("Escape")
            return
        try:
            pg.locator(".select2-results__option", has_text=re.compile(
                "^" + re.escape(chosen) + "$")).first.click(timeout=6000)
        except Exception:
            pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        self.log(fid, chosen, "picked", spec.get("label", label))

    def do_select_locator(self, fid, spec, value, el):
        opts = el.evaluate("e => Array.from(e.options).map(o => o.text.trim())")
        candidates = spec.get("accept") or ([str(value)] if value is not None else [])
        chosen = self.pick(fid, spec, value, candidates, opts)
        if chosen is None:
            return
        el.select_option(label=chosen, timeout=8000)
        self.pg.wait_for_timeout(400)
        self.log(fid, chosen, "picked", spec.get("label", ""))

    def do_typeahead(self, fid, spec, value):
        """Type-to-search field whose real input has no id, located by placeholder.
        The id'd element is a hidden backing field, so writing to it does nothing."""
        pg = self.pg
        if spec.get("placeholder"):
            el = pg.get_by_placeholder(spec["placeholder"]).nth(spec.get("index", 0))
        else:
            el = pg.locator(sel_id(fid))
        el.scroll_into_view_if_needed(timeout=8000)
        el.click(timeout=8000)
        el.fill(str(value), timeout=8000)
        pg.wait_for_timeout(spec.get("wait_ms", 2500))

        opts = pg.evaluate("""() => Array.from(document.querySelectorAll('[role=option], li, [class*=suggestion] div'))
            .filter(e => e.offsetParent !== null)
            .map(e => (e.innerText || '').trim())
            .filter(t => t && t.length < 120).slice(0, 40)""")
        want = str(value)
        chosen = None
        for o in opts:
            if o.strip().lower() == want.strip().lower():
                chosen = o
                break
        if not chosen:
            for o in opts:
                if want.strip().lower() in o.strip().lower() or o.strip().lower() in want.strip().lower():
                    chosen = o
                    break
        if not chosen and spec.get("fallback"):
            for o in opts:
                if o.strip().lower() == spec["fallback"].strip().lower():
                    chosen = o
                    break
        if not chosen:
            self.problems.append(f"{fid}: typeahead offered nothing matching '{want}'. Saw: {opts[:8]}")
            self.log(fid, want, "FAILED", spec.get("label", ""))
            return
        try:
            pg.get_by_text(chosen, exact=True).first.click(timeout=8000)
        except Exception:
            pg.keyboard.press("ArrowDown")
            pg.keyboard.press("Enter")
        pg.wait_for_timeout(800)
        self.log(fid, chosen, "picked" if chosen.lower() == want.lower() else "matched",
                 spec.get("label", ""))

    def do_select(self, fid, spec, value):
        """Native <select>. Exact label, then containment, then refuse."""
        el = self.pg.locator(sel_id(fid))
        el.scroll_into_view_if_needed(timeout=8000)
        opts = self.pg.evaluate(SCOPED_OPTIONS, fid).get("opts") or []
        candidates = spec.get("accept") or ([str(value)] if value is not None else [])
        chosen = self.pick(fid, spec, value, candidates, opts)
        if chosen is None:
            return
        el.select_option(label=chosen, timeout=8000)
        self.pg.wait_for_timeout(spec.get("wait_ms", 500))
        self.log(fid, chosen, "picked", spec.get("label", ""))

    def do_auto(self, fid, spec, value):
        pg = self.pg
        el = pg.locator(sel_id(fid))
        el.scroll_into_view_if_needed(timeout=8000)
        el.click(timeout=8000)
        pg.wait_for_timeout(700)
        candidates = spec.get("accept") or ([str(value)] if value is not None else [])
        if spec.get("needs_typing") and candidates:
            el.fill(str(candidates[0])[:40], timeout=6000)
            pg.wait_for_timeout(spec.get("wait_ms", 1600))
        r = pg.evaluate(SCOPED_OPTIONS, fid)
        opts = r.get("opts") or []
        if not opts and candidates:
            el.fill(str(candidates[0]), timeout=6000)
            pg.wait_for_timeout(1100)
            r = pg.evaluate(SCOPED_OPTIONS, fid)
            opts = r.get("opts") or []
        if not opts:
            self.problems.append(f"{fid}: no options readable ({r.get('err', 'empty list')})")
            self.log(fid, value, "FAILED", spec.get("label", ""))
            pg.keyboard.press("Escape")
            return
        chosen = self.pick(fid, spec, value, candidates, opts)
        if chosen is None:
            pg.keyboard.press("Escape")
            return
        box_sel = r.get("boxSelector")
        try:
            if box_sel:
                pg.locator(f"{box_sel} [role=option]",
                           has_text=re.compile("^" + re.escape(chosen) + "$")).first.click(timeout=8000)
            else:
                pg.get_by_role("option", name=chosen, exact=True).first.click(timeout=8000)
        except Exception:
            el.fill(chosen, timeout=6000)
            pg.wait_for_timeout(800)
            pg.keyboard.press("Enter")
        pg.wait_for_timeout(400)
        exact = candidates and chosen.strip().lower() == str(candidates[0]).strip().lower()
        self.log(fid, chosen, "picked" if exact else "matched", spec.get("label", ""))

    def pick(self, fid, spec, value, candidates, opts):
        """Choose an option. Refuses to fuzzy-guess anything marked STOP or no_fuzzy."""
        real = [o for o in opts if o.strip().lower() not in ("please select", "select...", "select one", "-")]
        if spec.get("choose"):
            want = spec["choose"]
            for o in real:
                if o.strip().lower() == want.strip().lower():
                    return o
            self.problems.append(
                f"{fid}: recipe says choose '{want}' but the form no longer offers it. Options: {real[:8]}")
            self.log(fid, want, "FAILED", spec.get("label", ""))
            return None
        for w in candidates:
            for o in real:
                if o.strip().lower() == str(w).strip().lower():
                    return o
        for w in candidates:
            for o in real:
                if str(w).strip().lower() in o.strip().lower():
                    return o
        if spec.get("no_fuzzy") or spec.get("STOP"):
            self.stops.append({"field": fid, "label": spec.get("label", ""),
                               "options": real, "reason": spec.get("STOP", "no honest match")})
            self.log(fid, "STOPPED", "STOP", spec.get("label", ""))
            return None
        m = difflib.get_close_matches(str(candidates[0]) if candidates else "", real, n=1, cutoff=0.72)
        if m:
            return m[0]
        self.problems.append(f"{fid}: no option matched {candidates[:2]}. Options: {real[:8]}")
        self.log(fid, candidates[:1], "FAILED", spec.get("label", ""))
        return None

    def do_click_input(self, fid, spec, kind):
        """Checkbox or radio addressed by its own id."""
        want = spec.get("checked", True)
        n = self.pg.evaluate("""([fid, want]) => {
          const e = document.getElementById(fid);
          if (!e) return -1;
          if (!!e.checked !== !!want) { e.click(); }
          return e.checked ? 1 : 0;
        }""", [fid, want])
        if n < 0:
            self.problems.append(f"{fid}: {kind} not found")
            self.log(fid, want, "FAILED", spec.get("label", ""))
        else:
            self.log(fid, "checked" if n else "unchecked", "ticked", spec.get("label", ""))

    def do_radio_group(self, spec):
        """Radio group addressed by name plus the visible label of the option to pick."""
        name, want = spec["radio_name"], spec["choose"]
        n = self.pg.evaluate("""([nm, want]) => {
          let hit = 0;
          document.querySelectorAll('input[type=radio][name="' + CSS.escape(nm) + '"]').forEach(r => {
            const l = r.id ? document.querySelector('label[for="' + CSS.escape(r.id) + '"]') : null;
            const t = ((l ? l.innerText : '') || (r.closest('label') || {}).innerText || '').trim();
            if (t.toLowerCase() === want.toLowerCase() && !hit) { r.click(); hit = 1; }
          });
          return hit;
        }""", [name, want])
        self.log("radio:" + name[:28], want, "ticked" if n else "FAILED", spec.get("label", ""))
        if not n:
            self.problems.append(f"radio {name}: option '{want}' not found")

    # Required consent boxes that only confirm what he already chose to give.
    # Ticked wherever they appear; absent on most forms, so no problem if missing.
    # Company C, 2026-09-29: an unticked demographic-survey consent rejected the submit.
    STANDARD_CONSENTS = [
        r"consent to .{0,40}(collecting|storing|processing).{0,80}demographic",
    ]
    # Checkbox groups whose answer follows from ANSWERS.json: (group question, option).
    # Company C, 2026-09-29: "What FINRA license(s) do you hold?" appears only after
    # FINRA = No, is required, and blocked the submit with nothing ticked.
    STANDARD_GROUPS = [
        (r"finra license\(?s?\)?,? if any", "N/A"),
    ]

    def tick_standard_consents(self):
        for pat in self.STANDARD_CONSENTS:
            n = self.pg.evaluate("""(pat) => {
              const re = new RegExp(pat, 'i');
              let n = 0;
              document.querySelectorAll('input[type=checkbox]').forEach(cb => {
                const l = cb.id ? document.querySelector('label[for="' + CSS.escape(cb.id) + '"]') : null;
                const t = ((l ? l.innerText : '') || (cb.closest('label') || {}).innerText || '').trim();
                if (re.test(t.replace(/\\s+/g, ' ')) && !cb.checked) { cb.click(); n++; }
              });
              return n;
            }""", pat)
            if n:
                self.log("consent: " + pat[:26], f"ticked {n}", "ticked")
        for pat, option in self.STANDARD_GROUPS:
            n = self.pg.evaluate("""([pat, option]) => {
              const re = new RegExp(pat, 'i');
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
              let n = 0;
              document.querySelectorAll('input[type=checkbox]').forEach(cb => {
                const l = cb.id ? document.querySelector('label[for="' + CSS.escape(cb.id) + '"]') : null;
                const t = norm((l ? l.innerText : '') || (cb.closest('label') || {}).innerText);
                if (t.toLowerCase() !== option.toLowerCase() || cb.checked) return;
                // the group question sits a few levels up, in a legend or a label
                let a = cb.parentElement, hit = false;
                for (let i = 0; a && i < 6 && !hit; i++, a = a.parentElement) {
                  hit = re.test(norm((a.innerText || '').slice(0, 300)));
                }
                if (hit) { cb.click(); n++; }
              });
              return n;
            }""", [pat, option])
            if n:
                self.log("group: " + pat[:28], f"{option} ticked", "ticked")

    def do_checkbox_label(self, label_prefix):
        n = self.pg.evaluate("""(lbl) => {
          let n = 0;
          document.querySelectorAll('input[type=checkbox]').forEach(cb => {
            const l = cb.id ? document.querySelector('label[for="' + CSS.escape(cb.id) + '"]') : null;
            const t = ((l ? l.innerText : '') || (cb.closest('label') || {}).innerText || '').trim();
            const clean = t.replace(/^\\*\\s*/, '');
            if (clean.toLowerCase().startsWith(lbl.toLowerCase()) && !cb.checked) { cb.click(); n++; }
          });
          return n;
        }""", label_prefix)
        self.log("checkbox: " + label_prefix[:24], f"ticked {n}", "ticked" if n else "not found")
        if not n:
            self.problems.append(f"checkbox not found: {label_prefix}")

    # -- one recipe block -----------------------------------------------------
    def classify(self, specs):
        """Ask the DOM what each field really is, and correct the recipe."""
        ids = [f for f, s in specs.items()
               if not f.startswith("label:") and not f.startswith("s2:")]
        ids = [f for f in ids if specs[f].get("type", "text") in
               ("text", "autocomplete", "select", "combobox", "react_text", "date")
               and not specs[f].get("force_type")]
        if not ids:
            return {}
        try:
            actual = self.pg.evaluate(CLASSIFY, ids)
        except Exception as e:
            note("  classify failed, trusting the recipe:", type(e).__name__)
            return {}
        fixed = {}
        for fid, real in actual.items():
            if real in ("missing", None):
                continue
            declared = specs[fid].get("type", "text")
            # a date field is a text field we write through React, leave it alone
            if declared in ("date", "react_text") and real == "text":
                continue
            if declared != real:
                fixed[fid] = real
                note(f"   ~~ {fid[:34]:<34} recipe said {declared}, DOM says {real}")
        return fixed

    def run_block(self, block):
        specs = block.get("fields", {})
        # label-addressed fields have no id, so skip DOM classification for them
        specs = dict(specs)
        label_fields = {k: v for k, v in specs.items()
                        if k.startswith("label:") or v.get("by_label")}
        s2_fields = {k: v for k, v in specs.items()
                     if k.startswith("s2:") or v.get("after_text")}
        label_fields = {k: v for k, v in label_fields.items() if k not in s2_fields}
        corrected = self.classify({k: v for k, v in specs.items()
                                   if k not in label_fields and k not in s2_fields})
        if corrected:
            note(f"  corrected {len(corrected)} field type(s) from the DOM")
        for fid in specs:
            spec = specs[fid]
            kind = corrected.get(fid, spec.get("type", "text"))

            if spec.get("STOP") and not spec.get("choose"):
                self.stops.append({"field": fid, "label": spec.get("label", ""),
                                   "options": spec.get("options", []), "reason": spec["STOP"]})
                self.log(fid, "STOPPED", "STOP", spec.get("label", ""))
                self.touched.add(fid)
                continue

            if kind == "radio_group":
                try:
                    self.do_radio_group(spec)
                except Exception as e:
                    self.problems.append(f"{fid}: {type(e).__name__} {str(e)[:110]}")
                self.touched.add(fid)
                continue

            value = resolve(self.answers, spec.get("answer")) if spec.get("answer") else spec.get("choose")
            if value in (None, "") and spec.get("accept"):
                value = spec["accept"][0]          # accept list alone is enough to act on
            if isinstance(value, list):
                value = value[0] if value else None

            if kind not in ("file", "checkbox", "radio") and value in (None, "") and not spec.get("choose"):
                if spec.get("required", True):
                    self.problems.append(f"{fid}: answer '{spec.get('answer')}' is empty in ANSWERS.json")
                    self.log(fid, spec.get("answer"), "FAILED", spec.get("label", ""))
                else:
                    self.log(fid, "(blank, optional)", "skipped", spec.get("label", ""))
                self.touched.add(fid)
                continue

            try:
                if fid in s2_fields:
                    self.do_select2(fid, spec, value)
                elif fid in label_fields:
                    self.do_label_combobox(fid, spec, value)
                elif kind == "file":
                    self.do_file(fid, spec)
                elif kind == "select":
                    self.do_select(fid, spec, value)
                elif kind == "typeahead":
                    self.do_typeahead(fid, spec, value)
                elif kind in ("date", "react_text"):
                    self.do_react(fid, spec, value)
                elif kind in ("autocomplete", "combobox"):
                    self.do_auto(fid, spec, value)
                elif kind in ("checkbox", "radio"):
                    self.do_click_input(fid, spec, kind)
                else:
                    self.do_text(fid, spec, value)
            except Exception as e:
                present = False
                try:
                    present = self.pg.locator(sel_id(fid)).count() > 0
                except Exception:
                    pass
                if not present and not spec.get("required", True):
                    self.log(fid, "(not on this form)", "skipped", spec.get("label", ""))
                else:
                    self.problems.append(f"{fid}: {type(e).__name__} {str(e)[:110]}")
                    self.log(fid, value, "FAILED", spec.get("label", ""))
            self.touched.add(fid)

        for lbl in block.get("checkboxes", []):
            try:
                self.do_checkbox_label(lbl)
            except Exception as e:
                self.problems.append(f"checkbox {lbl}: {type(e).__name__}")
        try:
            self.tick_standard_consents()
        except Exception as e:
            self.problems.append(f"standard consents: {type(e).__name__}")

    def verify(self):
        """Read back everything we wrote. A field that did not take is the most
        dangerous failure there is, because the form looks filled and is wrong."""
        if not self.intended:
            return []
        actual = self.pg.evaluate("""(ids) => {
          const out = {};
          ids.forEach(id => {
            const el = document.getElementById(id);
            if (!el) { out[id] = null; return; }
            out[id] = el.tagName === 'SELECT'
              ? (el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '')
              : (el.type === 'checkbox' ? String(el.checked) : (el.value || ''));
          });
          return out;
        }""", list(self.intended.keys()))
        bad = []
        for fid, want in self.intended.items():
            got = actual.get(fid)
            if got is None:
                continue          # field left the DOM, e.g. a step we moved past
            w, g = want.strip().lower(), str(got).strip().lower()
            if w == g or w in g or g in w:
                continue
            bad.append({"field": fid, "wanted": want[:70], "actual": str(got)[:70]})
        for b in bad:
            self.problems.append(
                f"{b['field']}: did not stick. wanted {b['wanted']!r}, form has {b['actual']!r}")
            note(f"   !! VERIFY {b['field'][:32]:<32} wanted {b['wanted'][:26]!r} got {b['actual'][:26]!r}")
        return bad

    def run_generic(self, controls, skip_ids=()):
        """Fill a step that has no recipe, by reading each field's own label.
        Returns the recipe block it worked out, ready to be saved and reused."""
        learned = {}
        for c in controls:
            fid = c.get("id") or ""
            if not fid or fid in self.touched or fid in skip_ids:
                continue      # the recipe owns this field, never guess over it
            if c["kind"] in ("input:file", "input:submit", "input:button", "input:radio"):
                continue
            text = c["label"] or c.get("placeholder") or c.get("name") or ""
            key, stop = guess_answer_key(text)
            if stop:
                self.stops.append({"field": fid, "label": c["label"],
                                   "options": c.get("options", []), "reason": stop})
                self.log(fid, "STOPPED", "STOP", c["label"])
                self.touched.add(fid)
                continue
            if not key:
                continue
            val = resolve(self.answers, key)
            if isinstance(val, list):
                val = val[0] if val else None
            if val in (None, ""):
                continue
            if c["kind"].startswith("select"):
                kind = "select"
            elif c.get("combobox"):
                kind = "autocomplete"
            elif c["kind"] == "input:checkbox":
                kind = "checkbox"
            else:
                kind = "text"
            # A dropdown wants "Yes", not the full free-text sentence.
            if kind in ("select", "autocomplete"):
                m = re.match(r"\s*(yes|no)\b", str(val), re.I)
                if m:
                    val = m.group(1).capitalize()
            spec = {"type": kind, "answer": key, "label": c["label"][:90],
                    "required": c["required"], "learned_by": "label match"}
            try:
                if kind == "select":
                    self.do_select(fid, spec, val)
                elif kind == "autocomplete":
                    self.do_auto(fid, spec, val)
                elif kind == "checkbox":
                    continue
                else:
                    self.do_text(fid, spec, val)
                learned[fid] = spec
            except Exception as e:
                self.problems.append(f"{fid}: {type(e).__name__} {str(e)[:90]}")
            self.touched.add(fid)
        return learned

    # Upload boxes whose own label is only "Attach": the meaning is in the
    # question text around them. An eval run on 2026-09-30 found Company A's
    # required transcript left empty this way, while every text field passed.
    UPLOAD_CONTEXT = [(r"transcript", "transcript"),
                      (r"\bcover letter\b", "cover_pdf"),
                      (r"\b(resume|cv)\b", "resume_pdf")]

    def run_uploads(self, controls):
        learned = {}
        for c in controls:
            fid = c.get("id") or ""
            if c.get("kind") != "input:file" or not fid or fid in self.touched:
                continue
            ctx = self.pg.evaluate("""(id) => {
              const e = document.getElementById(id); if (!e) return '';
              const b = e.closest('[class*=field],[class*=question],fieldset') || e.parentElement;
              return ((b && b.innerText) || '').replace(/\\s+/g, ' ').slice(0, 300); }""", fid)
            key = next((k for pat, k in self.UPLOAD_CONTEXT if re.search(pat, ctx, re.I) and self.files.get(k)), None)
            if not key:
                continue
            spec = {"type": "file", "upload": key, "label": ctx[:90], "learned_by": "context match"}
            try:
                self.do_file(fid, spec)
                learned[fid] = spec
            except Exception as e:
                self.problems.append(f"{fid}: {type(e).__name__} {str(e)[:90]}")
            self.touched.add(fid)
        return learned

    def unknown_controls(self, block):
        """Visible controls this block does not account for. Required ones matter most."""
        known = set(block.get("fields", {}).keys()) | self.touched | set(block.get("ignore_ids", []))
        ignore_kinds = ("input:checkbox", "input:radio", "input:submit", "input:button")
        out = []
        for c in self.pg.evaluate(ALL_CONTROLS):
            fid = c.get("id") or ""
            if fid in known or c["kind"] in ignore_kinds:
                continue
            if not c["required"] and not c["label"]:
                continue
            out.append(c)
        return out


# --------------------------------------------------------------- step logic --
def control_sig(pg):
    """Fingerprint of the visible controls. Single-page apps change step without
    changing the URL, so the fields on screen are the only reliable signal."""
    ids = pg.evaluate("""() => Array.from(document.querySelectorAll('input,select,textarea,[role=combobox]'))
        .filter(e => e.type !== 'hidden' && (e.offsetParent || e.type === 'file'))
        .map(e => e.id || e.name || e.tagName).sort().join('|')""")
    return ids


def current_step(pg, recipe):
    """Which step are we on. A field unique to a step beats the URL, because the
    URL often lags behind in a single-page flow."""
    steps = recipe.get("steps", {})
    for name, block in steps.items():
        mf = block.get("match_field")
        if mf:
            try:
                # must be VISIBLE. A single-page flow leaves the previous step's
                # nodes in the DOM, so count() alone matches a step we already left.
                loc = pg.locator(sel_id(mf))
                if loc.count() and loc.first.is_visible(timeout=2000):
                    return name
            except Exception:
                pass
    q = parse_qs(urlparse(pg.url).query)
    key = recipe.get("step_param", "stepname")
    if q.get(key):
        return q[key][0]
    sel = recipe.get("step_dom_selector")
    if sel:
        try:
            t = pg.locator(sel).first.inner_text(timeout=3000).strip()
            if t:
                return t
        except Exception:
            pass
    return ""


# overlay nodes that swallow clicks even when nothing is visibly in the way
OVERLAY_NUKE = """() => {
  let n = 0;
  // 1. known banner containers
  ['.truste_overlay', '.truste_box_overlay', '#truste-consent-track',
   '#onetrust-consent-sdk', '.onetrust-pc-dark-filter', '[id^="pop-div"]',
   '.cookie-overlay', '[class*=CookieBanner]'
  ].forEach(s => document.querySelectorAll(s).forEach(e => { e.remove(); n++; }));

  // 2. anything that is geometrically a blocking layer. Judged by behaviour,
  //    not by name, so real consent CHECKBOXES on a form are never touched:
  //    a node only goes if it is fixed or sticky, floats above the page, covers
  //    a big area, and contains no field the applicant has to fill.
  const vw = innerWidth, vh = innerHeight;
  document.querySelectorAll('body *').forEach(e => {
    const cs = getComputedStyle(e);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') return;
    const z = parseInt(cs.zIndex || '0', 10);
    if (!(z > 100)) return;
    const r = e.getBoundingClientRect();
    if (r.width * r.height < 0.18 * vw * vh) return;
    const fields = e.querySelectorAll(
      'input:not([type=button]):not([type=submit]), select, textarea');
    if (fields.length) return;
    e.remove(); n++;
  });
  return n;
}"""

DEFAULT_DISMISS = [
    "#onetrust-accept-btn-handler",
    "#truste-consent-button",
    ".truste-button1",
    "a.call",
    "button#truste-consent-button",
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept Cookies')",
    "button:has-text('I Accept')",
    "button:has-text('Allow')",
    "button:has-text('Got it')",
    "[aria-label='Close'][class*=cookie]",
]


ACCEPT_BY_TEXT = """() => {
  // Click the accept control whatever tag it uses. Cookie tools use <button>,
  // <a> and <div role=button> interchangeably, so match on the visible text.
  const want = ['accept all', 'accept all cookies', 'accept cookies', 'accept',
                'i accept', 'agree', 'agree & continue', 'allow all', 'allow',
                'got it', 'ok', 'continue'];
  const nodes = document.querySelectorAll('button, a, div[role=button], span[role=button], input[type=button]');
  for (const e of nodes) {
    if (!e.offsetParent) continue;
    const t = ((e.innerText || e.value || '').trim()).toLowerCase();
    if (!t || t.length > 24) continue;
    if (!want.includes(t)) continue;
    const box = e.closest('[class*=cookie i], [id*=cookie i], [class*=consent i], [id*=consent i], [class*=privacy i]');
    if (!box) continue;              // only inside a cookie or consent widget
    e.click();
    return t;
  }
  return '';
}"""


def dismiss_overlays(pg, recipe):
    """Cookie banners and consent bars swallow clicks on the real buttons."""
    killed = []
    try:
        hit = pg.evaluate(ACCEPT_BY_TEXT)
        if hit:
            killed.append(f"clicked {hit!r} in a consent widget")
            pg.wait_for_timeout(1500)
    except Exception:
        pass
    for sel in (recipe.get("dismiss") or DEFAULT_DISMISS):
        try:
            loc = pg.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1200):
                loc.click(timeout=4000)
                pg.wait_for_timeout(700)
                killed.append(sel)
        except Exception:
            pass
    try:
        n = pg.evaluate(OVERLAY_NUKE)
        if n:
            killed.append(f"removed {n} overlay node(s)")
    except Exception:
        pass
    if killed:
        note("  dismissed overlay:", ", ".join(killed))
    return killed


SPINNERS = ["[class*=loading]", "[class*=Loading]", "[class*=spinner]", "[class*=Spinner]",
            "[class*=overlay]", "[aria-busy=true]"]


def wait_settle(pg, recipe, extra_ms=2000):
    """Wait for the page to stop working. A fixed sleep after Next is a coin flip:
    these flows show a spinner over a greyed page while the next step loads."""
    pg.wait_for_timeout(1200)
    try:
        pg.wait_for_load_state("networkidle", timeout=25000)
    except Exception:
        pass
    for sel in (recipe.get("spinners") or SPINNERS):
        try:
            loc = pg.locator(sel).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.wait_for(state="hidden", timeout=25000)
        except Exception:
            pass
    pg.wait_for_timeout(extra_ms)


CODE_FIELD = ("input[autocomplete='one-time-code'], input[name*='code' i], "
              "input[id*='code' i], input[aria-label*='code' i], input[placeholder*='code' i]")


def needs_code(pg):
    """Greenhouse and others now email an 8-character code before accepting a submit."""
    try:
        # read the WHOLE page: on a long form the code prompt is the last thing
        # on it, far past any truncation point.
        txt = pg.inner_text("body").lower()
        if "verification code was sent" in txt or "enter the 8-character code" in txt                 or ("security code" in txt and "confirm you" in txt):
            return True
        # "code" alone is not enough: every address block has "Zip Code", and
        # Company C's rejected submit (an unticked consent box) was read as a code
        # prompt and waited 5 minutes for an email that was never sent.
        return pg.locator(CODE_FIELD).first.count() > 0 and bool(re.search(
            r"(security|verification|confirmation|one.?time) code|code (was|has been) sent", txt))
    except Exception:
        return False


def wait_for_code(code_file, timeout_s=300, since=None, company=None):
    """Wait for the emailed code. Two sources, checked in this order:
    1. A code someone writes into code_file (manual override, always wins).
    2. Gmail itself over IMAP (gmail_code.py), if an app password is set up.
       This is what makes an unattended run possible: the claude.ai Gmail
       connector needs org approval in headless mode, IMAP does not.
    Only codes received after `since` count, because each form reload emails
    a new code and invalidates the old ones."""
    import time
    note(f"  waiting for the emailed code, write it to: {code_file}")
    since = since or time.time() - 30
    try:
        import gmail_code
        imap_ok = gmail_code.load_secrets() is not None and not BASELINE
    except Exception as e:
        imap_ok = False
        note("  gmail_code unavailable:", e)
    note("  reading Gmail over IMAP" if imap_ok else "  no Gmail app password, waiting for a manual code")
    deadline = time.time() + timeout_s
    next_imap = time.time() + 8  # give the email a few seconds to arrive
    while time.time() < deadline:
        if os.path.exists(code_file):
            v = open(code_file, encoding="utf-8").read().strip()
            if v:
                note("  got code from file:", v)
                return v
        if imap_ok and time.time() >= next_imap:
            try:
                v = gmail_code.newest_code(since, company)
                if v:
                    note("  got code from Gmail:", v)
                    return v
            except Exception as e:
                note("  IMAP check failed:", e)
            next_imap = time.time() + 10
        time.sleep(3)
    return ""


def enter_code(pg, code):
    """Find the code boxes by shape, not by name. An OTP widget is a run of
    visible inputs with maxlength 1; some sites use one plain field instead."""
    info = pg.evaluate("""() => {
      const vis = Array.from(document.querySelectorAll('input'))
        .filter(e => e.offsetParent && e.type !== 'hidden');
      const otp = vis.filter(e => e.maxLength === 1);
      if (otp.length >= 4) return {mode: 'otp', n: otp.length, first: vis.indexOf(otp[0])};
      const named = vis.filter(e => /code/i.test(
        (e.id || '') + (e.name || '') + (e.getAttribute('aria-label') || '') + (e.placeholder || '')));
      if (named.length) return {mode: 'single', first: vis.indexOf(named[0])};
      return {mode: 'none', tail: vis.slice(-14).map(e => ({
        id: e.id, name: e.name, type: e.type, maxlen: e.maxLength,
        aria: e.getAttribute('aria-label') || '', ph: e.placeholder || ''}))};
    }""")
    note("  code field probe:", json.dumps(info)[:400])
    if info.get("mode") == "none":
        return False
    boxes = pg.locator("input:visible")
    first = boxes.nth(info["first"])
    first.scroll_into_view_if_needed(timeout=8000)
    first.click(timeout=8000)
    if info["mode"] == "single":
        first.fill(code, timeout=8000)
    else:
        pg.keyboard.type(code, delay=110)
    pg.wait_for_timeout(1500)
    return True


def postmortem(pg, filler):
    """Everything needed to fix the form, gathered in ONE run.

    The reason a new platform used to cost six round trips is that a failed
    submit only revealed its first complaint. This walks the whole page instead:
    every error message tied to its own field, every required field still empty,
    and the real option list of every unfilled dropdown, opened one at a time.
    """
    report = {"errors": [], "empty_required": [], "options": {}}

    report["errors"] = pg.evaluate("""() => {
      const out = [];
      document.querySelectorAll('[class*=error],[class*=Error],[role=alert],[aria-invalid=true]')
        .forEach(e => {
          if (!e.offsetParent) return;
          const msg = (e.innerText || '').trim().replace(/\\s+/g, ' ');
          if (!msg || msg.length > 200) return;
          // find the field this message belongs to
          let owner = '', label = '';
          const box = e.closest('[class*=field],[class*=question],fieldset,div');
          if (box) {
            const f = box.querySelector('input,select,textarea,[role=combobox]');
            if (f) { owner = f.id || f.name || ''; }
            const l = box.querySelector('label,legend');
            if (l) label = (l.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
          }
          out.push({message: msg, field: owner, label: label});
        });
      return out.slice(0, 40);
    }""")

    report["empty_required"] = pg.evaluate("""() => {
      const out = [];
      document.querySelectorAll('input,select,textarea,[role=combobox]').forEach(el => {
        if (el.type === 'hidden' || (!el.offsetParent && el.type !== 'file')) return;
        const box = el.closest('[class*=field],[class*=question],fieldset,div');
        const boxText = box ? (box.innerText || '').slice(0, 300) : '';
        const req = el.required || el.getAttribute('aria-required') === 'true'
                    || /\\*/.test(boxText) || /required/i.test(boxText);
        if (!req) return;
        let val = '';
        if (el.tagName === 'SELECT') {
          val = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '';
          if (/^(select an option|please select|select\\.\\.\\.|-)$/i.test(val)) val = '';
        } else if (el.type === 'checkbox' || el.type === 'radio') {
          val = el.checked ? 'checked' : '';
        } else {
          val = (el.value || '').trim();
        }
        if (val) return;
        let label = '';
        const w = el.closest('label');
        if (w) label = (w.innerText || '').trim();
        if (!label && box) { const l = box.querySelector('label,legend'); if (l) label = (l.innerText || '').trim(); }
        out.push({id: el.id || '', name: el.name || '',
                  kind: el.tagName.toLowerCase() + ':' + (el.type || el.getAttribute('role') || ''),
                  label: label.replace(/\\s+/g, ' ').slice(0, 90)});
      });
      return out.slice(0, 40);
    }""")

    # open each unfilled dropdown and record what it actually offers
    for f in report["empty_required"]:
        kind, fid = f["kind"], f["id"]
        if "select" not in kind and "combobox" not in kind:
            continue
        key = fid or f["label"][:40]
        if not key or key in report["options"]:
            continue
        try:
            if kind.startswith("select:") and fid:
                report["options"][key] = pg.evaluate(
                    "(id) => {const e=document.getElementById(id);"
                    "return e ? Array.from(e.options).map(o=>o.text.trim()) : []}", fid)
                continue
            loc = pg.locator(sel_id(fid)).first if fid else None
            if loc is None or not loc.count():
                marked = pg.evaluate(Filler.MARK_BY_LABEL, [f["label"].lower()[:30], 0])
                if not marked:
                    continue
                loc = pg.locator('[data-applier-target="1"]').first
            loc.scroll_into_view_if_needed(timeout=4000)
            loc.click(timeout=5000)
            pg.wait_for_timeout(900)
            report["options"][key] = pg.evaluate(Filler.OPEN_OPTIONS)[:60]
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
        except Exception:
            continue

    note("\n--- POST MORTEM ---")
    for e in report["errors"][:12]:
        note(f"   error  {e['field'] or e['label'][:30]!r}: {e['message'][:100]}")
    for f in report["empty_required"][:20]:
        note(f"   empty  {f['kind']:<18} {f['id'][:22]:<22} | {f['label'][:60]}")
    for k, v in list(report["options"].items())[:12]:
        note(f"   opts   {k[:28]:<28} {v[:10]}")
    return report


def dump_step(pg, name):
    return {
        "step": name,
        "url": pg.url,
        "controls": pg.evaluate(ALL_CONTROLS),
        "checkboxes": pg.evaluate(CHECKBOX_DUMP),
        "buttons": pg.evaluate(
            """() => Array.from(document.querySelectorAll('button,input[type=submit]'))
                 .filter(e => e.offsetParent !== null)
                 .map(e => ((e.innerText || e.value || '').trim()))
                 .filter(s => s.length > 1).slice(0, 25)"""),
        "text_head": pg.inner_text("body")[:2500],
    }


# -------------------------------------------------------------------- main ---
def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    recipe = job["recipe"]
    out_dir = job.get("out_dir", ".")
    os.makedirs(out_dir, exist_ok=True)
    submit_ok = bool(job.get("submit"))
    # Hard stop for evaluations: with APPLIER_FORCE_NO_SUBMIT=1 no agent, prompt
    # or job.json can make this engine click submit.
    if os.environ.get("APPLIER_FORCE_NO_SUBMIT") == "1":
        if submit_ok:
            note("APPLIER_FORCE_NO_SUBMIT=1: submit disabled for this run")
        submit_ok = False
    explore = bool(job.get("explore"))

    result = {"url": job["url"], "status": "error", "steps_done": [], "audit": [],
              "problems": [], "stops": [], "unknown_fields": [], "unknown_step": None,
              "unknown_steps": [], "learned": {}, "postmortem": None,
              "screenshots": [], "page_text": ""}

    with sync_playwright() as p:
        UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
        ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]
        profile = job.get("profile")
        if profile:
            # keeps cookies and logins between runs, so an account is created once
            os.makedirs(profile, exist_ok=True)
            ctx = p.chromium.launch_persistent_context(profile, headless=True,
                                                       args=ARGS, user_agent=UA,
                                                       viewport={"width": 1400, "height": 1300})
            b = ctx
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            note("using saved browser profile:", profile)
        else:
            b = p.chromium.launch(headless=True, args=ARGS)
            ctx = b.new_context(viewport={"width": 1400, "height": 1300}, user_agent=UA)
            pg = ctx.new_page()
        pg.set_default_timeout(45000)
        try:
            pg.goto(job["url"], wait_until="domcontentloaded")
            pg.wait_for_timeout(recipe.get("wait_after_load_ms", 5000))
            dismiss_overlays(pg, recipe)

            # Clicks a recipe needs before any field exists: an Apply button, a
            # privacy gate, a consent wall. Each one WAITS for its element,
            # because these gates render after the page shell does.
            for act in recipe.get("pre_actions", []):
                if act.get("upload"):
                    # some flows put the resume upload before any form exists
                    dismiss_overlays(pg, recipe)
                    sel = act.get("selector", "input[type=file]")
                    path = job.get("files", {}).get(act["upload"])
                    try:
                        pg.locator(sel).first.set_input_files(path, timeout=25000)
                        pg.wait_for_timeout(act.get("wait_ms", 18000))
                        note("  pre-action uploaded:", os.path.basename(path))
                    except Exception as e:
                        note("  pre-action upload skipped:", type(e).__name__)
                        if act.get("required"):
                            result["problems"].append(f"pre-action upload failed: {sel}")
                    continue
                sel = act.get("click")
                try:
                    loc = pg.locator(sel).first
                    loc.wait_for(state="visible", timeout=act.get("timeout_ms", 12000))
                    dismiss_overlays(pg, recipe)
                    loc.click(timeout=10000)
                    wait_settle(pg, recipe, act.get("wait_ms", 3000))
                    note("  pre-action clicked:", sel)
                except Exception as e:
                    note("  pre-action skipped:", sel, type(e).__name__)
                    if act.get("required"):
                        result["problems"].append(f"pre-action not found: {sel}")

            note("form:", pg.title()[:90], "\n")

            f = Filler(pg, job["answers"], job.get("files", {}))

            # ---- single page ------------------------------------------------
            if "steps" not in recipe:
                note("[single page]")
                f.run_block(recipe)
                # Answer the company's own questions from the label map. This used
                # to run only on multi-step forms, so every custom Greenhouse
                # question fell to the agent, one tool call at a time.
                learned = {} if BASELINE else f.run_generic(f.unknown_controls(recipe))
                if not BASELINE:
                    learned.update(f.run_uploads(f.unknown_controls(recipe)))
                result["learned"] = learned
                # Answers can reveal new required boxes (FINRA = No shows a
                # licence list), so tick the standard ones again after them.
                f.tick_standard_consents()
                f.verify()
                result["unknown_fields"] = f.unknown_controls(recipe)
                shot = os.path.join(out_dir, "filled.png")
                pg.wait_for_timeout(1200)
                pg.screenshot(path=shot, full_page=True)
                result["screenshots"].append(shot)
                # only a REQUIRED unknown field should stop a submit. Optional
                # extras (a second attachment slot, a website box) are not blockers.
                blocking_unknown = [u for u in result["unknown_fields"] if u.get("required")]
                blockers = f.problems + f.stops + blocking_unknown
                if submit_ok and not blockers:
                    import time as _t
                    clicked_at = _t.time()
                    pg.locator(recipe.get("submit_selector", "button:has-text('Submit')")).first.click(timeout=25000)
                    # Some Greenhouse boards run an invisible reCAPTCHA check before
                    # the redirect, which can leave the submit button spinning past
                    # 9s. Poll instead of a single fixed sleep, up to 25s total.
                    for _ in range(16):
                        pg.wait_for_timeout(1500)
                        spinning = pg.locator(
                            recipe.get("submit_selector", "button:has-text('Submit')")
                        ).first.locator("svg, .spinner, [class*='spinner']").count() > 0
                        if not spinning:
                            break
                    # Company A, 2026-09-29: the invisible reCAPTCHA held the
                    # button for ~60s before the code prompt rendered, so a single
                    # needs_code() check at ~24s missed it and reported
                    # submitted_unconfirmed. Keep polling for the prompt or a
                    # success signal before judging.
                    _sig = [x.lower() for x in recipe.get("success_signals", [])]
                    _end = _t.time() + recipe.get("post_submit_wait_s", 120)
                    while _t.time() < _end:
                        if needs_code(pg):
                            break
                        try:
                            _b = pg.inner_text("body").lower()
                            if any(x in _b for x in _sig):
                                break
                        except Exception:
                            pass
                        pg.wait_for_timeout(2000)
                    s2 = os.path.join(out_dir, "after_submit.png")
                    pg.screenshot(path=s2, full_page=True)
                    result["screenshots"].append(s2)
                    gave_up = False
                    if needs_code(pg):
                        cf = job.get("code_file", os.path.join(out_dir, "CODE.txt"))
                        try:
                            os.remove(cf)
                        except OSError:
                            pass
                        result["awaiting_code"] = cf
                        pg.screenshot(path=os.path.join(out_dir, "code_prompt.png"), full_page=True)
                        # only codes emailed after THIS click; older ones are dead
                        code = wait_for_code(cf, job.get("code_timeout_s", 300),
                                             since=clicked_at - 5, company=job.get("company"))
                        if code and enter_code(pg, code):
                            pg.locator(recipe.get("submit_selector",
                                                  "button:has-text('Submit')")).first.click(timeout=25000)
                            wait_settle(pg, recipe, 6000)
                            _end = _t.time() + 60
                            while _t.time() < _end:
                                try:
                                    _b = pg.inner_text("body").lower()
                                    if any(x in _b for x in _sig) or "incorrect" in _b:
                                        break
                                except Exception:
                                    pass
                                pg.wait_for_timeout(2000)
                            shot = os.path.join(out_dir, "after_code.png")
                            pg.screenshot(path=shot, full_page=True)
                            result["screenshots"].append(shot)
                        else:
                            gave_up = True
                            result["status"] = "awaiting_code"
                            result["page_text"] = pg.inner_text("body")[-2500:]
                            note("  no code supplied in time, stopping before submit")
                    if not gave_up:
                        body = pg.inner_text("body")[-2500:]
                        result["page_text"] = body
                        ok = any(x.lower() in body.lower() for x in recipe.get("success_signals", []))
                        result["status"] = "submitted" if ok else "submitted_unconfirmed"
                elif submit_ok:
                    result["status"] = "needs_brain" if (f.stops or blocking_unknown) else "problems"
                else:
                    result["status"] = "filled_not_submitted"

            # ---- multi step -------------------------------------------------
            else:
                steps = recipe["steps"]
                recipe_ids = set()
                for blk in steps.values():
                    recipe_ids |= set(blk.get("fields", {}).keys())
                    recipe_ids |= set(blk.get("ignore_ids", []))
                seen_sigs = []
                for i in range(MAX_STEPS):
                    name = current_step(pg, recipe)
                    sig = control_sig(pg)
                    note(f"\n[step {i + 1}] {name or '(unnamed)'}  fields={len(sig.split('|'))}")
                    if sig in seen_sigs:
                        result["problems"].append(
                            f"step '{name}' did not advance, the same fields are still on screen")
                        result["unknown_step"] = dump_step(pg, name)
                        try:
                            result["postmortem"] = postmortem(pg, f)
                        except Exception as e:
                            note("  postmortem failed:", type(e).__name__)
                        break
                    seen_sigs.append(sig)

                    # The URL often lags in a single-page flow, so a name we have
                    # already completed means we are really on a step we cannot name.
                    if name in result["steps_done"]:
                        note(f"  '{name}' already done, so this is an unnamed later step")
                        name = ""
                    block = steps.get(name)
                    if block is None:
                        dumped = dump_step(pg, name)
                        result["unknown_steps"].append(dumped)
                        shot = os.path.join(out_dir, f"step_{i + 1}_unknown.png")
                        pg.screenshot(path=shot, full_page=True)
                        result["screenshots"].append(shot)
                        if not explore:
                            note("  UNKNOWN STEP, stopping")
                            result["unknown_step"] = dumped
                            result["status"] = "unknown_step"
                            break
                        # explore mode: fill it from the label map and keep walking,
                        # so one run learns the whole flow instead of one step per run.
                        note("  UNKNOWN STEP, filling from labels and continuing")
                        f.touched = set()
                        learned = f.run_generic(dumped["controls"], skip_ids=recipe_ids)
                        key = name or f"unnamed_step_{i + 1}"
                        result["learned"][key] = {"match_field": next(iter(learned), None),
                                                  "fields": learned}
                        note(f"  learned {len(learned)} of {len(dumped['controls'])} fields by label")
                        # keep what run_generic already filled, otherwise every
                        # field it just handled gets reported as unknown
                        # ignore only what it actually filled, so a field it
                        # failed on still shows up as needing attention
                        block = {"fields": {}, "ignore_ids": list(learned.keys())}
                    else:
                        f.touched = set()
                    f.run_block(block)
                    # The recipe wins, then the label matcher fills whatever the
                    # recipe does not name. Without this, writing a recipe for a
                    # step made it WORSE than leaving the step unknown.
                    if recipe.get("label_fallback", True):
                        rest = [c for c in pg.evaluate(ALL_CONTROLS)
                                if c.get("id") and c["id"] not in f.touched]
                        extra = f.run_generic(rest, skip_ids=recipe_ids)
                        if extra:
                            note(f"  label matcher filled {len(extra)} more field(s)")
                    f.verify()
                    unknown = f.unknown_controls(block)
                    if unknown:
                        result["unknown_fields"].extend([dict(u, step=name) for u in unknown])

                    shot = os.path.join(out_dir, f"step_{i + 1}_{name or 'x'}.png")
                    pg.screenshot(path=shot, full_page=True)
                    result["screenshots"].append(shot)
                    result["steps_done"].append(name)

                    if block.get("final"):
                        blocking_unknown = [u for u in result["unknown_fields"] if u.get("required")]
                        if submit_ok and not (f.problems + f.stops + blocking_unknown):
                            pg.locator(block.get("submit_selector",
                                                 recipe.get("submit_selector", "button:has-text('Submit')"))
                                       ).first.click(timeout=25000)
                            pg.wait_for_timeout(10000)
                            s2 = os.path.join(out_dir, "after_submit.png")
                            pg.screenshot(path=s2, full_page=True)
                            result["screenshots"].append(s2)
                            body = pg.inner_text("body")[-2500:]
                            result["page_text"] = body
                            ok = any(s.lower() in body.lower() for s in recipe.get("success_signals", []))
                            result["status"] = "submitted" if ok else "submitted_unconfirmed"
                        else:
                            result["status"] = ("needs_brain" if (f.stops or blocking_unknown)
                                                else ("problems" if f.problems else "filled_not_submitted"))
                        break

                    if f.stops and not explore:
                        result["status"] = "needs_brain"
                        note("  stopping: a field needs Joaquin")
                        break

                    nxt = block.get("next_selector", recipe.get("next_selector", "button:has-text('Next')"))
                    before = pg.url
                    try:
                        btn = pg.locator(nxt).first
                        btn.scroll_into_view_if_needed(timeout=8000)
                        try:
                            btn.click(timeout=12000)
                        except Exception:
                            # something is sitting on top of it, clear and retry once
                            dismiss_overlays(pg, recipe)
                            btn.click(timeout=12000)
                    except Exception:
                        # the configured selector missed. Try the usual button
                        # names one at a time, which also covers a comma list
                        # that Playwright could not parse.
                        hit = None
                        for nm in ("Continue", "Next", "Save and continue", "Save & Continue",
                                   "Submit", "Apply", "Proceed"):
                            try:
                                b2 = pg.get_by_role("button", name=nm, exact=False).first
                                if b2.count() and b2.is_visible(timeout=1500):
                                    b2.scroll_into_view_if_needed(timeout=5000)
                                    b2.click(timeout=10000)
                                    hit = nm
                                    note("  next via fallback:", nm)
                                    break
                            except Exception:
                                continue
                        if not hit:
                            result["problems"].append(f"step '{name}': no next button found")
                            result["status"] = "problems"
                            break
                    if False:
                        pass
                    wait_settle(pg, recipe, recipe.get("wait_after_next_ms", 4000))
                    errs = pg.evaluate(VALIDATION_ERRORS)
                    if pg.url == before and errs:
                        result["problems"].append(f"step '{name}' rejected: {errs[:5]}")
                        result["status"] = "problems"
                        note("  validation errors:", errs[:5])
                        try:
                            result["postmortem"] = postmortem(pg, f)
                        except Exception as e:
                            note("  postmortem failed:", type(e).__name__)
                        result["blocked_at"] = {"step": name, "errors": errs[:8],
                                                "dump": dump_step(pg, name)}
                        break
                else:
                    result["problems"].append(f"ran out of steps after {MAX_STEPS}")

                if result["status"] == "error":
                    result["status"] = "problems" if result["problems"] else "filled_not_submitted"

            result["audit"] = f.audit
            result["problems"].extend(f.problems)
            result["stops"] = f.stops

        except Exception as e:
            result["problems"].append(f"fatal: {type(e).__name__} {str(e)[:200]}")
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                if b is not ctx:
                    b.close()
            except Exception:
                pass

    note(f"\nSTATUS: {result['status']}  "
         f"problems={len(result['problems'])} stops={len(result['stops'])} "
         f"unknown_fields={len(result['unknown_fields'])}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
