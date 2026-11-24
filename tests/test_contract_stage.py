"""Tests for the profile-driven B2B / contractor policy in ContractStage."""

import unittest
from unittest.mock import patch

from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.contract import ContractStage, get_contract_policy


def _run(profile, title, content="", **target_kwargs):
    target = CompanyTarget(id="t", name="T", tier="scaleup", eor_supported=False, **target_kwargs)
    raw = RawJob(id="1", company_id="t", title=title, location="Remote", url="", content=content)
    job = Job(id="1", company_id="t", title=title, location="Remote", url="")
    with patch("radar.pipeline.contract.load_profile", return_value=profile):
        return ContractStage().process(raw, job, PipelineContext(target=target))


class TestContractPolicy(unittest.TestCase):
    def test_defaults_drop_b2b(self):
        policy = get_contract_policy({})
        self.assertFalse(policy["accept_b2b"])
        self.assertEqual(policy["b2b_bonus"], 0)
        self.assertFalse(_run({}, "Release Manager (Freelance)").should_continue)

    def test_accept_keeps_b2b_with_bonus_and_tag(self):
        prof = {"contract": {"b2b": "accept", "b2b_bonus": 15}}
        res = _run(prof, "Release Manager (Freelance)")
        self.assertTrue(res.should_continue)
        self.assertIn("contract:b2b", res.tags)
        self.assertEqual(res.score_delta, 15 + 15)  # b2b bonus + scaleup tier

    def test_accept_does_not_touch_employee_postings(self):
        prof = {"contract": {"b2b": "accept", "b2b_bonus": 15}}
        res = _run(prof, "Release Manager", "Permanent full-time role")
        self.assertTrue(res.should_continue)
        self.assertNotIn("contract:b2b", res.tags)
        self.assertEqual(res.score_delta, 15)

    def test_extra_patterns(self):
        prof = {"contract": {"b2b_patterns": [r"\bsole\s+trader\b"]}}
        self.assertFalse(_run(prof, "Consultant", "Invoice us as a sole trader").should_continue)
        prof["contract"]["b2b"] = "accept"
        res = _run(prof, "Consultant", "Invoice us as a sole trader")
        self.assertIn("contract:b2b", res.tags)

    def test_market_and_audience_mentions_are_not_b2b(self):
        for title, content in [
            ("Senior Product Manager", "5+ years of experience in a B2B SaaS product"),
            ("Senior Product Manager B2B (VPN)", "Grow B2B conversion"),
            ("Ubuntu Software Engineer", "from students, hobbyists and freelancers to engineers"),
            ("Executive Communications Lead", "Coordinate with agencies and freelance writers"),
            ("Product Manager - AI Inference", "Experience working on B2B products involving complex APIs"),
            ("Demand Generation Specialist", "5+ years of hands-on B2B demand generation"),
            ("Senior Product Designer", "design experience working on B2B/enterprise software products"),
            ("Senior SRE", "Permanent salaried full-time employee role (Not a contract or freelance position)."),
        ]:
            res = _run({}, title, content)
            self.assertTrue(res.should_continue, title)
            self.assertNotIn("contract:b2b", res.tags, title)

    def test_contract_terms_are_b2b(self):
        for title, content in [
            ("Staff Engineer (Freelance / B2B)", "Work with our team"),
            ("Open Source Marketing Specialist - Contractor", ""),
            ("Account Executive", "Contract type: Initial independent contractor engagement."),
            ("Backend Developer", "We offer a B2B contract or UoP"),
            ("Embedded Engineer", "Long-term cooperation on a B2B basis"),
            ("Field Engineer", "Employment type: freelance"),
            ("Designer", "This is a freelance position for 6 months"),
            ("Engineer [Contract]", ""),
        ]:
            self.assertFalse(_run({}, title, content).should_continue, title)

    def test_invalid_pattern_ignored(self):
        policy = get_contract_policy({"contract": {"b2b_patterns": ["(unclosed"], "b2b_bonus": "x"}})
        self.assertEqual(policy["b2b_patterns"], [])
        self.assertEqual(policy["b2b_bonus"], 0)


if __name__ == "__main__":
    unittest.main()
