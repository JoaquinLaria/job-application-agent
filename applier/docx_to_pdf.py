#!/usr/bin/env python3
"""
Convert one or more .docx files to PDF via Word, in one deterministic call,
with a real OS-level timeout instead of trusting Word to behave.

    python docx_to_pdf.py <out_dir> <docx1> [docx2 ...]

Prints each output PDF path on success. Exit code 1 means at least one file
did not produce a PDF; stderr says which and why.

Why this exists, and why it works the way it does:
- Converting a .docx straight from its OneDrive-synced path can put Word into
  a locked Protected View state that hangs indefinitely with no dialog an
  unattended agent can see or dismiss. Fix: always copy to a local temp
  folder first, convert there, copy the PDF back.
- A PowerShell-side timeout (Start-Job + Wait-Job) was tried and proved
  unreliable here: the job can still be stuck inside Word after the wait
  returns. Python's subprocess timeout is a hard, OS-level kill and is the
  one enforced here.
- After a timeout, the PDF file on disk is the source of truth, not the
  process's exit code. If Word finished the actual conversion and only hung
  afterward on cleanup, the PDF already exists and that counts as success.
"""
import os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERT_ONE = os.path.join(HERE, "_convert_one.ps1")
TIMEOUT_S = 40


def winword_pids():
    """Measured: $word.Quit() in _convert_one.ps1 does not always unload the
    WINWORD.EXE process, even on a clean, fast conversion. Two stray processes
    survived two successful back-to-back conversions. Rather than trust Quit,
    track exactly which process this call spawns and kill that one PID after
    -- never a blind killall, so a Word window Joaquin has open himself is
    never touched."""
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    pids = set()
    for line in r.stdout.strip().splitlines():
        parts = [p.strip('"') for p in line.strip().split('","')]
        if len(parts) > 1 and parts[0] == "WINWORD.EXE":
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    return pids


def convert_one(src, out_dir, tmp):
    name = os.path.splitext(os.path.basename(src))[0]
    local_docx = os.path.join(tmp, name + ".docx")
    local_pdf = os.path.join(tmp, name + ".pdf")
    shutil.copy(src, local_docx)

    cmd = ["powershell", "-NoProfile", "-File", CONVERT_ONE,
           "-InDocx", local_docx, "-OutPdf", local_pdf]
    before = winword_pids()
    timed_out = False
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
        ok_exit = r.returncode == 0
        stderr = r.stderr
    except subprocess.TimeoutExpired:
        timed_out = True
        ok_exit = False
        stderr = f"powershell did not return within {TIMEOUT_S}s, killed"
    finally:
        time.sleep(0.5)  # give Quit() its best chance before we check
        for pid in winword_pids() - before:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)

    # The file on disk is ground truth, not the exit code: Word can finish the
    # real conversion and only hang afterward on Quit().
    for _ in range(10 if timed_out else 1):
        if os.path.exists(local_pdf) and os.path.getsize(local_pdf) > 0:
            dest = os.path.join(out_dir, name + ".pdf")
            shutil.copy(local_pdf, dest)
            return dest, None
        if timed_out:
            time.sleep(0.5)  # SaveAs may still be flushing to disk

    return None, (stderr if not ok_exit else "conversion reported success but no PDF file appeared")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir, docs = sys.argv[1], sys.argv[2:]
    os.makedirs(out_dir, exist_ok=True)
    ok, bad = [], []
    with tempfile.TemporaryDirectory(prefix="docx2pdf_") as tmp:
        for src in docs:
            dest, err = convert_one(src, out_dir, tmp)
            (ok if dest else bad).append(dest or f"{src}: {err}")
    for p in ok:
        print(p)
    if bad:
        for b in bad:
            print(b, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
