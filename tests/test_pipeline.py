#!/usr/bin/env python3
"""
Regression tests for the application pipeline. No network, no browser,
nothing is submitted. Each test pins a bug that broke a real run on
2026-09-29 (see "Lessons from real runs" in CLAUDE.md).

    python -m unittest discover -s tests -v        (from the Application Agent folder)

preflight.py checks the live machine (Gmail, WSL, Word). These tests check
the logic, and run in a few seconds.
"""
import json, os, shutil, subprocess, sys, tempfile, time, types, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLIER = os.path.join(ROOT, "applier")
DASH = os.path.join(ROOT, "dashboard")
sys.path[:0] = [APPLIER, DASH]

# fill.py imports Playwright at module level; Windows Python has none, and these
# tests never open a browser, so give it a stand-in.
if "playwright" not in sys.modules:
    pw = types.ModuleType("playwright"); api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = None
    sys.modules["playwright"], sys.modules["playwright.sync_api"] = pw, api

import prepare_run, gmail_code, fill  # noqa: E402

_real = os.path.join(APPLIER, "ANSWERS.json")
EXAMPLE_ONLY = not os.path.exists(_real)  # public repo ships only ANSWERS.example.json
ANSWERS = json.load(open(_real if not EXAMPLE_ONLY else os.path.join(APPLIER, "ANSWERS.example.json"), encoding="utf-8"))


class PrepareRun(unittest.TestCase):
    def test_windows_paths_become_wsl_paths(self):
        # fill.py runs in Linux; a C:\ path there made it poll a CODE.txt nobody could see
        self.assertEqual(prepare_run.to_wsl("C:\\Users\\joaco\\x y\\job.json"), "/mnt/c/Users/joaco/x y/job.json")
        self.assertEqual(prepare_run.to_wsl("/mnt/c/already/linux.pdf"), "/mnt/c/already/linux.pdf")

    def test_every_greenhouse_url_shape_matches(self):
        # my.greenhouse.io was once misrouted as an unknown platform
        for u in ["https://my.greenhouse.io/jobs/companya/1000000001?query=MBA+",
                  "https://job-boards.greenhouse.io/companyb/jobs/1000000002",
                  "https://boards.greenhouse.io/embed/job_app?for=x&token=1",
                  "https://companya.com/pages/job-openings?gh_jid=1000000001"]:
            self.assertEqual(prepare_run.detect_recipe(u)[0], "greenhouse.json", u)
        self.assertIsNone(prepare_run.detect_recipe("https://unknown-ats.example.com/apply/1")[0])

    def test_company_site_gh_jid_link_goes_to_the_embed_form(self):
        # Company C: companyc.com/careers/job/?gh_jid= embeds the form in an iframe and
        # fill.py timed out on every field.
        recipe = prepare_run.detect_recipe("https://www.companyc.com/careers/job/?gh_jid=1000000003")[1]
        self.assertEqual(prepare_run.rewrite_url("https://www.companyc.com/careers/job/?gh_jid=1000000003", recipe),
                         "https://boards.greenhouse.io/embed/job_app?for=companyc&token=1000000003")

    def test_job_json_is_ready_for_linux(self):
        key = "zz-unittest"
        run = os.path.join(APPLIER, "runs", key)
        try:
            r = subprocess.run([sys.executable, os.path.join(APPLIER, "prepare_run.py"),
                                "https://my.greenhouse.io/jobs/companya/1000000001",
                                "C:/x/resume.pdf", "/mnt/c/x/cover.pdf", key, "--no-submit", "--company", "Company A"],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(run, "job.json"), encoding="utf-8") as f:
                j = json.load(f)
            for k in ("out_dir", "code_file"):
                self.assertTrue(j[k].startswith("/mnt/"), k)
            self.assertTrue(j["files"]["resume_pdf"].startswith("/mnt/c/"))
            self.assertIn("transcript_undergrad", j["files"])  # once missing, form blocked
            self.assertNotIn("my.greenhouse.io", j["url"])      # once hit a login page
            self.assertFalse(j["submit"])
            self.assertEqual(j["company"], "Company A")
        finally:
            shutil.rmtree(run, ignore_errors=True)


class LabelMatcher(unittest.TestCase):
    """The Company A run stopped to ask Joaquin all seven of these."""
    COMPANY_A = {
        "LinkedIn Profile*": "identity.linkedin_full",
        "Do you have a strong academic track record, including currently pursuing a Master of Business Administration (MBA) degree": "screening_defaults.currently_pursuing_mba_graduating_2027",
        "What School do you currently attend? If you graduated, where did you graduate from? *": "screening_defaults.school_info",
        "What is/was your major/concentration?*": "education.grad_discipline",
        "What is your current cumulative GPA?*": "screening_defaults.gpa_text",
        "Do you have 4 to 7 years of related work experience, preferably in fields such as consulting": "screening_defaults.has_4_to_7_years_experience",
        "Our Leadership Development Program is based in-office, and we place a strong emphasis on in-person mentorship": "screening_defaults.willing_to_work_in_office",
    }

    def test_companya_questions_answer_themselves(self):
        for label, want in self.COMPANY_A.items():
            key, stop = fill.guess_answer_key(label)
            self.assertIsNone(stop, label)
            self.assertEqual(key, want, label)
            self.assertTrue(fill.resolve(ANSWERS, key), f"{key} has no value in ANSWERS.json")

    # Company C, 2026-09-29: a run stopped to ask these; Joaquin confirmed each answer.
    COMPANY_C = {
        "Location (City)*": ("identity.location_city", "<home city>"),
        "Would you like to receive marketing communications about careers at Company C and Company C Tech Solutions?*": ("screening_defaults.marketing_communications_opt_in", "No"),
        "I acknowledge that by providing my phone number, I agree to receive text messages from Company C Technologies in relation to this job a": ("screening_defaults.sms_text_consent", "Yes"),
        "Do you currently hold, or intend to hold, any FINRA licenses if employed by Company C?": ("screening_defaults.finra_licenses", "No"),
        "Are you currently employed with or have been employed by Deloitte? Deloitte is our external financial auditor": ("screening_defaults.auditor_employee_ever", "No"),
        "Are you currently a Company C or Company C Tech Solutions (formerly Galileo) employee?*": ("screening_defaults.current_employee_of_company", "No"),
        "Are you authorized to lawfully work in the country where this role is located?*": ("work_authorization.legally_authorized_us", "Yes"),
        "Are you currently located within, or planning to relocate to be within, a reasonable commute of any of this job's listed hiring lo": ("screening_defaults.within_commute_or_relocate", "Yes"),
        "Home Address State*": ("identity.state", "Massachusetts"),
        "Home Address Country*": ("identity.country", "United States"),
    }

    @unittest.skipIf(EXAMPLE_ONLY, "checks real answer values (private repo)")
    def test_companyc_questions_answer_themselves(self):
        for label, (key_want, val_want) in self.COMPANY_C.items():
            key, stop = fill.guess_answer_key(label)
            self.assertIsNone(stop, label)
            self.assertEqual(key, key_want, label)
            self.assertEqual(fill.resolve(ANSWERS, key), val_want, label)
        key, _ = fill.guess_answer_key("Today's Date of Application (MM/DD/YY Format)*")
        self.assertEqual(fill.resolve(ANSWERS, key), time.strftime("%m/%d/%y"))

    def test_visa_questions_map_to_the_exact_answers(self):
        for label, want in {"Will you now or in the future require visa sponsorship?": "work_authorization.require_sponsorship",
                            "Are you legally authorized to work in the United States?": "work_authorization.legally_authorized_us"}.items():
            self.assertEqual(fill.guess_answer_key(label)[0], want, label)

    def test_companyd_wordings_are_recognised(self):
        # held-out eval 2026-09-30: both required dropdowns were left on "Select..."
        self.assertEqual(fill.guess_answer_key("Are you currently eligible to work legally in the United States of America?")[0],
                         "work_authorization.legally_authorized_us")
        self.assertEqual(fill.guess_answer_key("Do you acknowledge that this is a hybrid role based in San Francisco and you will be required to come into the office four days a week?")[0],
                         "screening_defaults.willing_to_work_in_office")

    def test_upload_boxes_are_matched_by_their_question_text(self):
        # Company A's required transcript box is labelled only "Attach";
        # an eval on 2026-09-30 caught it left empty
        pick = lambda ctx: next((k for pat, k in fill.Filler.UPLOAD_CONTEXT if fill.re.search(pat, ctx, fill.re.I)), None)
        self.assertEqual(pick("Please link a copy of your most recent transcript. (Unofficial transcripts are accepted) * Attach"), "transcript")
        self.assertEqual(pick("Cover Letter Attach Dropbox"), "cover_pdf")
        self.assertIsNone(pick("Portfolio or work samples Attach"))

    def test_legal_declarations_still_stop(self):
        key, stop = fill.guess_answer_key("Have you ever had a criminal conviction record?")
        self.assertIsNone(key)
        self.assertTrue(stop)


class GmailCode(unittest.TestCase):
    def test_only_the_newest_code_after_the_run_start_counts(self):
        # entering an older code from the same thread gave "Incorrect security code"
        since = 1000
        msgs = [(900, "Security code for your application to Company A", "application: OLDOLD11"),
                (1100, "Security code for your application to Company A", "application: 2xhjl6Y4"),
                (1300, "Security code for your application to Company A", "application: GJFzqJBr"),
                (1400, "Security code for your application to Company H", "application: CODEH111"),
                (1500, "Your application was received", "application: NOTACODE")]
        self.assertEqual(gmail_code.pick_newest(msgs, since, "Company A"), "GJFzqJBr")
        self.assertEqual(gmail_code.pick_newest(msgs, since), "CODEH111")
        self.assertIsNone(gmail_code.pick_newest(msgs, 2000, "Company A"))


class Answers(unittest.TestCase):
    def test_screening_defaults_are_finished_answers(self):
        # these are typed straight into forms; an instruction here would be sent to an employer
        for k, v in ANSWERS["screening_defaults"].items():
            if k.startswith("_") or k == "rule":
                continue
            for marker in ("use the", "acceptable when", "ask joaquin", "todo", "xxxx"):
                self.assertNotIn(marker, str(v).lower(), f"{k}: {v}")

    def test_never_claims_a_referral_that_does_not_exist(self):
        # held-out eval 2026-09-30: "Employee referral" was typed into Company D's free-text box
        hear = ANSWERS["how_did_you_hear"]
        if not hear.get("referrals"):
            for opt in hear["ranked"]:
                self.assertNotIn("referral", opt.lower(), opt)

    @unittest.skipIf(EXAMPLE_ONLY, "needs the real answers file (private repo)")
    def test_transcript_exists_with_a_plain_name(self):
        t = ANSWERS["education"]["transcript_pdf"]
        self.assertTrue(os.path.exists(t), t)
        self.assertTrue(t.isascii(), "accents or commas break the Linux upload")


class Dashboard(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(app, k) for k in ("JOBS", "STAGES", "LOGS", "DISMISSED", "SUBMITTER_CONF", "QUEUE_TXT")}
        app.JOBS = os.path.join(self.tmp, "jobs.json")
        app.STAGES = os.path.join(self.tmp, "stages"); os.makedirs(app.STAGES)
        app.LOGS = os.path.join(self.tmp, "logs"); os.makedirs(app.LOGS)
        app.DISMISSED = os.path.join(self.tmp, "dismissed.json")
        app.SUBMITTER_CONF = os.path.join(self.tmp, "submitter.json")
        app.QUEUE_TXT = os.path.join(self.tmp, "QUEUE.txt")
        json.dump({"submitter": "hermes", "hermes_model": "claude-haiku-4-5", "hermes_max_turns": 8},
                  open(app.SUBMITTER_CONF, "w"))
        self.c = app.app.test_client()

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(self.app, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, path, body=None):
        return self.c.post(path, json=body or {})

    def test_add_labels_and_skips_duplicates(self):
        r = self.post("/api/jobs", {"text": "Stripe - PM https://a.test/1\nhttps://a.test/1\nno link here"}).get_json()
        self.assertEqual(r["added"], 1)
        jobs = self.c.get("/api/jobs").get_json()["jobs"]
        self.assertEqual(jobs[0]["label"], "Stripe - PM")

    def test_removed_jobs_stay_removed_after_a_queue_sync(self):
        # removed jobs used to reappear on every QUEUE.txt sync
        open(self.app.QUEUE_TXT, "w").write("# Acme, Strategy\nhttps://q.test/1\n\n# Beta, PM\nhttps://q.test/2\n")
        self.assertEqual(self.post("/api/sync_queue").get_json()["added"], 2)
        jobs = self.c.get("/api/jobs").get_json()["jobs"]
        self.assertEqual(jobs[0]["label"], "Acme, Strategy")
        self.post(f"/api/jobs/{jobs[0]['id']}/remove")
        self.assertEqual(self.post("/api/sync_queue").get_json()["added"], 0)
        self.assertEqual(len(self.c.get("/api/jobs").get_json()["jobs"]), 1)
        self.assertEqual(self.post("/api/jobs", {"text": "https://q.test/1"}).get_json()["added"], 1)  # by hand still works

    def test_submitter_switch_validates_and_keeps_other_settings(self):
        self.assertEqual(self.c.get("/api/submitter").get_json()["submitter"], "hermes")
        self.assertEqual(self.post("/api/submitter", {"submitter": "claude", "model": "sonnet"}).status_code, 200)
        conf = json.load(open(self.app.SUBMITTER_CONF))
        self.assertEqual((conf["submitter"], conf["claude_model"], conf["hermes_max_turns"]), ("claude", "sonnet", 8))
        self.assertEqual(self.post("/api/submitter", {"submitter": "gpt"}).status_code, 400)
        self.assertEqual(self.post("/api/submitter", {"submitter": "hermes", "model": "sonnet"}).status_code, 400)

    def test_cap_counts_applications_not_retries(self):
        # one job's retries once used all five slots and blocked the next job
        jobs = [{"id": "a", "state": "done"}, {"id": "b", "state": "sent"}, {"id": "c", "state": "sent"}]
        used = {"a", "x1", "x2", "x3", "x4"}
        self.assertIsNone(self.app.pick_next(jobs, used))                     # cap full: new jobs wait
        self.assertEqual(self.app.pick_next(jobs, {"a"})["id"], "b")          # room: queue order
        self.assertEqual(self.app.pick_next(jobs, used | {"c"}, cap=6)["id"], "c")  # full, but c already has a slot
        self.assertEqual(self.app.pick_next([{"id": "a", "state": "sent"}], used)["id"], "a")  # retry allowed

    def test_resume_needs_a_reply(self):
        self.post("/api/jobs", {"text": "https://r.test/1"})
        jid = self.c.get("/api/jobs").get_json()["jobs"][0]["id"]
        jobs = self.app.load(); jobs[0]["state"] = "done"; self.app.save(jobs)
        self.assertEqual(self.post(f"/api/jobs/{jid}/resume", {"reply": "  "}).status_code, 400)
        self.assertEqual(self.post(f"/api/jobs/{jid}/resume", {"reply": "use 3.5"}).status_code, 200)
        self.assertEqual(self.app.load()[0]["pending_reply"], "use 3.5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
