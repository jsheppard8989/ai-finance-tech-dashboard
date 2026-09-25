"""Backstop: generic reader advice ("Investors should…") never reaches public card fields."""
import unittest

from site_text_sanitize import clean_reader_advice, sanitize_public_text, strip_reader_advice


class ReaderAdviceTest(unittest.TestCase):
    def test_drops_investors_should_sentence(self):
        t = "Baker says capex hits $400B in 2026. Investors should focus on AI leaders."
        self.assertEqual(strip_reader_advice(t), "Baker says capex hits $400B in 2026.")

    def test_all_advice_becomes_empty(self):
        self.assertEqual(strip_reader_advice("Investors should consider diversifying."), "")
        self.assertEqual(strip_reader_advice("Healthcare investors need to watch CMS rules."), "")
        self.assertEqual(strip_reader_advice("It is crucial for investors to stay nimble."), "")
        self.assertEqual(strip_reader_advice("Invest in companies with strong moats."), "")

    def test_keeps_claims(self):
        for t in [
            "Investment in AI data centers reached $200B in Q2, per the guest.",
            "Investors sold $12B of HY bonds last week, the host notes.",
            "The Fed cut 25 bp in September, and the speaker expects one more.",
        ]:
            self.assertEqual(strip_reader_advice(t), t)

    def test_only_card_fields_touched(self):
        data = {
            "key_takeaway": "Investors should focus on AI.",
            "summary": "Investors should focus on AI.",
            "key_takeaways": ["Investors must hedge.", "NVDA guided $54B for Q3."],
            "nested": [{"last_main_idea": "Rates rose 50 bp. Investors should be cautious."}],
        }
        out = sanitize_public_text(data)
        self.assertEqual(out["key_takeaway"], "")
        self.assertEqual(out["summary"], "Investors should focus on AI.")
        self.assertEqual(out["key_takeaways"], ["NVDA guided $54B for Q3."])
        self.assertEqual(out["nested"][0]["last_main_idea"], "Rates rose 50 bp.")

    def test_cuts_trailing_advice_clause(self):
        t = "PE-owned insurers moved $1T of annuity risk offshore; investors should avoid them."
        self.assertEqual(strip_reader_advice(t), "PE-owned insurers moved $1T of annuity risk offshore.")

    def test_drops_conditional_advice_sentence(self):
        t = "Pies puts odds of a September hike at 40%. If he is right, investors should cut equities."
        self.assertEqual(strip_reader_advice(t), "Pies puts odds of a September hike at 40%.")

    def test_non_string_passthrough(self):
        self.assertEqual(clean_reader_advice({"key_takeaway": None, "n": 3}), {"key_takeaway": None, "n": 3})


if __name__ == "__main__":
    unittest.main()
