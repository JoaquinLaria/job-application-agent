"""Offline tests for the Homework 4 agent's own checks (no Canvas, no model)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "forum_agent"))
os.environ.setdefault("CANVAS_TOKEN", "unused"); os.environ.setdefault("PARLEY_KEY", "unused")
import agent, hw4

GOOD = [{"input": i, "expected": o} for i, o in [
    ("<p>a&amp;b</p>", "a&b"), ("<b>x</b>y", "x y"), ("  a \n\t b ", "a b"), ("&lt;i&gt;", "<i>"), ("Hello", "Hello"),
    ("", ""), ("<br>x<br>", "x"), ("<p>One</p><p>Two</p>", "One Two"), ("ABC", "ABC")]]


class Hw4Checks(unittest.TestCase):
    def test_reference_is_the_real_function(self):
        for c in GOOD:
            self.assertEqual(hw4.ref(c["input"]), agent.plain(c["input"]))

    def test_good_cases_pass_and_catch_mutants(self):
        r = hw4.check_cases(GOOD)
        self.assertTrue(r["passed"]); self.assertEqual(r["n_caught"], 6)

    def test_wrong_cases_fail(self):
        bad = [{"input": c["input"], "expected": c["expected"] + "!"} for c in GOOD]
        self.assertFalse(hw4.check_cases(bad)["passed"])

    def test_weak_cases_fail_mutant_bar(self):
        weak = [{"input": "plain", "expected": "plain"}] * 10
        self.assertFalse(hw4.check_cases(weak)["passed"])

    def test_extracted_values_must_appear_in_reply(self):
        self.assertTrue(hw4.appears("a\nb", 'assert plain("a\nb")'))
        self.assertFalse(hw4.appears("invented", "the reply never says this"))

    def test_screen_drops_quotes_not_in_posting(self):
        _, ok, dropped = hw4.render_screen({"verdict": "STOP", "requirements": [
            {"requirement": "Auth", "quote": "must be authorized to work", "meets": "no"},
            {"requirement": "Fake", "quote": "a sentence the posting never had", "meets": "yes"}]}, "You must be authorized to work here.")
        self.assertEqual((ok, dropped), (1, 1))

    def test_last_json_takes_final_answer(self):
        self.assertEqual(hw4.last_json('draft {"action": "x"} final {"action": "y"}')["action"], "y")

    def test_outgoing_guard_blocks_links_and_secrets(self):
        self.assertTrue(hw4.OUTGOING_BAD.search("see https://evil.example"))
        self.assertFalse(hw4.OUTGOING_BAD.search(hw4.OFFER))


if __name__ == "__main__":
    unittest.main()
