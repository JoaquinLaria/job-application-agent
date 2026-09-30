#!/usr/bin/env python3
"""
Read an application security code straight from Gmail over IMAP, so fill.py
can finish a Greenhouse submission with nobody watching.

Why this exists: the dashboard runs the agent unattended, and the claude.ai
Gmail connector needs organization approval in that mode ("Your organization
requires approval for this tool"). IMAP with a Gmail app password needs no
Claude tool at all.

One-time setup, done by Joaquin, never by the agent:
  1. <applicant email> must have 2-Step Verification on.
  2. https://myaccount.google.com/apppasswords -> create one named "career agent".
  3. Put it in C:\\Users\\joaco\\.career_secrets\\gmail.json:
       {"user": "<applicant email>", "app_password": "xxxx xxxx xxxx xxxx"}
Never print, log or copy the password anywhere else.

Manual test:
    python gmail_code.py --since-minutes 60 [--company "Company A"]
"""
import argparse, email, email.header, imaplib, json, os, re, sys, time
from email.utils import parsedate_to_datetime

SECRET_PATHS = [
    os.environ.get("CAREER_GMAIL_SECRETS", ""),
    "/mnt/c/Users/joaco/.career_secrets/gmail.json",   # from WSL, where fill.py runs
    "C:/Users/joaco/.career_secrets/gmail.json",       # from Windows
]
SENDER = "greenhouse-mail.io"
CODE_RE = re.compile(r"application:\s*([A-Za-z0-9]{8})\b")


def load_secrets():
    for p in SECRET_PATHS:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                s = json.load(f)
            if s.get("user") and s.get("app_password") and "xxxx" not in s["app_password"]:
                return s
    return None


def _body_text(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    out = []
    for part in parts:
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                out.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
    return re.sub(r"<[^>]+>", " ", "\n".join(out))


def pick_newest(messages, since_epoch, company=None):
    """messages: iterable of (timestamp, subject, body). Returns the code from
    the newest security-code email at or after since_epoch, or None.
    Only the newest counts: every form reload emails a new code and kills the
    previous one, and entering an older code from the same thread is exactly
    how a correct form once got "Incorrect security code"."""
    best = None
    for ts, subj, body in messages:
        s = (subj or "").lower()
        if "security code" not in s or (company and company.lower() not in s) or ts < since_epoch:
            continue
        mt = CODE_RE.search(body or "")
        if mt and (best is None or ts > best[0]):
            best = (ts, mt.group(1))
    return best[1] if best else None


def newest_code(since_epoch, company=None):
    """Newest Greenhouse security code in the inbox received after since_epoch."""
    s = load_secrets()
    if not s:
        return None
    # A timeout, because this runs inside fill.py's wait loop with a live form
    # open; a hung connection must not stall the whole run.
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=20)
    try:
        m.login(s["user"], s["app_password"].replace(" ", ""))
        m.select("INBOX", readonly=True)
        day = time.strftime("%d-%b-%Y", time.gmtime(since_epoch - 86400))
        typ, data = m.search(None, f'(FROM "{SENDER}" SINCE {day})')
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        messages = []
        for mid in ids[-15:]:
            typ, raw = m.fetch(mid, "(RFC822)")
            if typ != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            subj = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
            try:
                ts = parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:
                continue
            messages.append((ts, subj, _body_text(msg)))
        return pick_newest(messages, since_epoch, company)
    finally:
        try:
            m.logout()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-minutes", type=float, default=15)
    ap.add_argument("--company")
    a = ap.parse_args()
    if not load_secrets():
        sys.exit("no Gmail app password set up, see the docstring")
    code = newest_code(time.time() - a.since_minutes * 60, a.company)
    print(code or "no code found")
    sys.exit(0 if code else 1)


if __name__ == "__main__":
    main()
