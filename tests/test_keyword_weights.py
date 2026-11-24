"""Tests for profile scoring_weights keyword matching and scoring."""

import re
import unittest
from unittest.mock import patch

from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.keywords import KeywordWeightStage, evaluate_keywords, keyword_pattern

PROFILE = {
    "scoring_weights": {
        "title_keywords": {"productowner": 30, "linux": 30, "embedded": 35, "java": -20},
        "body_keywords": {"commoncriteria": 20, "linux": 15, "licenses": 20, "opensource": 15, "php": -15},
    }
}


def _matches(key, text):
    return bool(re.search(keyword_pattern(key), text, re.IGNORECASE))


class TestKeywordPattern(unittest.TestCase):
    def test_compound_keys_match_separated_text(self):
        self.assertTrue(_matches("productowner", "Senior Product Owner"))
        self.assertTrue(_matches("productowner", "product-owner"))
        self.assertTrue(_matches("commoncriteria", "Common Criteria EAL4+"))
        self.assertTrue(_matches("opensource", "open-source"))
        self.assertTrue(_matches("devops", "Dev-Ops"))
        self.assertTrue(_matches("common criteria", "commoncriteria"))

    def test_inflections(self):
        for text in ("release", "releases", "released", "releasing"):
            self.assertTrue(_matches("releasing", text), text)
        for text in ("license", "licenses", "licensing"):
            self.assertTrue(_matches("licenses", text), text)
        self.assertTrue(_matches("embedded", "embedding"))
        self.assertTrue(_matches("strategy", "strategies"))
        self.assertTrue(_matches("containers", "container"))

    def test_whole_word_only(self):
        self.assertFalse(_matches("aws", "laws"))
        self.assertFalse(_matches("qa", "Qatar"))
        self.assertFalse(_matches("deb", "debian"))
        self.assertFalse(_matches("linux", "linuxbrew"))
        self.assertFalse(_matches("management", "manager"))
        self.assertTrue(_matches("c++", "C++ developer"))
        self.assertTrue(_matches("ci/cd", "CI/CD pipelines"))

    def test_trailing_star_is_prefix_match(self):
        for text in ("virtualisation", "Virtualization", "virtualised"):
            self.assertTrue(_matches("virtuali*", text), text)
        self.assertTrue(_matches("certif*", "Certifications lead"))
        self.assertTrue(_matches("open source*", "open-sourced components"))
        self.assertFalse(_matches("certif*", "recertify"))
        self.assertFalse(_matches("kubernet*", "kubectl"))

class TestKeywordScoring(unittest.TestCase):
    def test_no_weights_no_score(self):
        self.assertEqual(evaluate_keywords("Linux Engineer", "linux", {}), (0, []))

    def test_title_and_body_scoring_is_capped(self):
        delta, matched = evaluate_keywords(
            "Product Owner, Embedded Linux",
            "Common Criteria certification, open source licenses, Linux everywhere.",
            PROFILE,
        )
        self.assertEqual(matched[:3], ["embedded", "productowner", "linux"])
        self.assertIn("commoncriteria", matched)
        # linux scored in title must not be scored again from the body
        self.assertEqual(matched.count("linux"), 1)
        self.assertLessEqual(delta, 30 + 20)
        self.assertGreater(delta, 40)

    def test_diminishing_returns(self):
        one, _ = evaluate_keywords("Linux Engineer", "", PROFILE)
        three, _ = evaluate_keywords("Embedded Linux Product Owner", "", PROFILE)
        self.assertGreater(three, one)
        self.assertLess(three, one * 3)

    def test_repetition_does_not_inflate_beyond_emphasis(self):
        once, _ = evaluate_keywords("Engineer", "Common Criteria", PROFILE)
        many, _ = evaluate_keywords("Engineer", "Common Criteria " * 20, PROFILE)
        self.assertGreaterEqual(many, once)
        self.assertLessEqual(many, 20)

    def test_negative_weights_penalise(self):
        delta, _ = evaluate_keywords("Java Engineer", "PHP backend", PROFILE)
        self.assertEqual(delta, -35)

    def test_custom_caps(self):
        prof = {"scoring_weights": dict(PROFILE["scoring_weights"], title_cap=10, body_cap=0)}
        delta, _ = evaluate_keywords("Embedded Linux Product Owner", "Common Criteria", prof)
        self.assertLessEqual(delta, 10)

    def test_stage_tag(self):
        raw = RawJob(id="1", company_id="t", title="Embedded Linux Engineer", location="", url="", content="")
        job = Job(id="1", company_id="t", title=raw.title, location="", url="")
        with patch("radar.pipeline.keywords.load_profile", return_value=PROFILE):
            res = KeywordWeightStage().process(raw, job, PipelineContext(target=CompanyTarget(id="t", name="T")))
        self.assertGreater(res.score_delta, 0)
        self.assertEqual(res.tags, [f"kw:embedded,linux(+{res.score_delta})"])


if __name__ == "__main__":
    unittest.main()
