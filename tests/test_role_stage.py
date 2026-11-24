"""RoleSeniorityStage and TitleFilterStage must follow the profile's target_roles."""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.role import RoleSeniorityStage, match_target_role
from radar.pipeline.title import TitleFilterStage

PO_PROFILE = {
    "skill_matrix": [{"pattern": r"\bproduct owner\b", "name": "PO"}],
    "target_roles": [
        {
            "name": "product_owner",
            "pattern": r"\bproduct\s+owner\b",
            "weight": 40,
            "lead_bonus": 15,
            "senior_bonus": 10,
            "tags": [{"pattern": r"\bsecurity\b", "tag": "domain:security"}],
        },
        {"name": "program_manager", "pattern": r"\bprogram\s+manager\b", "weight": 30},
        {"name": "people_manager", "pattern": r"\bengineering\s+manager\b", "weight": -15},
        {"name": "broken", "pattern": r"([oops"},
    ],
}


def use_profile(prof):
    stack = ExitStack()
    for target in ("radar.pipeline.profile.load_profile", "radar.pipeline.role.load_profile"):
        stack.enter_context(patch(target, return_value=prof))
    return stack


def run(stage, title, content=""):
    raw = RawJob(id="1", company_id="t", title=title, location="Remote", url="", content=content)
    job = Job(id="1", company_id="t", title=title, location="Remote", url="")
    return stage.process(raw, job, PipelineContext(target=CompanyTarget(id="t", name="T")))


class TestRoleStageDefaults(unittest.TestCase):
    def test_default_systems_role_without_target_roles(self):
        with use_profile({}):
            res = run(RoleSeniorityStage(), "Staff Platform Engineer")
        self.assertIn("role:systems_platform", res.tags)
        self.assertIn("domain:devops_platform_sre", res.tags)
        self.assertIn("seniority:staff_principal_lead", res.tags)
        self.assertEqual(res.score_delta, 50)

    def test_default_swe_role(self):
        with use_profile({}):
            res = run(RoleSeniorityStage(), "Senior Software Engineer")
        self.assertIn("role:swe", res.tags)
        self.assertEqual(res.score_delta, 15)


class TestRoleStageProfile(unittest.TestCase):
    def test_profile_role_with_seniority_and_domain(self):
        with use_profile(PO_PROFILE):
            res = run(RoleSeniorityStage(), "Senior Product Owner, Security")
        self.assertEqual(res.tags, ["role:product_owner", "domain:security", "seniority:senior"])
        self.assertEqual(res.score_delta, 50)

    def test_systems_title_gets_no_bonus_for_po_profile(self):
        with use_profile(PO_PROFILE):
            res = run(RoleSeniorityStage(), "Staff Systems Engineer")
        self.assertFalse([t for t in res.tags if t.startswith(("role:", "seniority:"))])
        self.assertEqual(res.score_delta, 0)

    def test_best_weight_wins(self):
        role = match_target_role("Product Owner / Program Manager", PO_PROFILE)
        self.assertEqual(role.name, "product_owner")

    def test_negative_role_without_seniority_bonus(self):
        with use_profile(PO_PROFILE):
            res = run(RoleSeniorityStage(), "Senior Engineering Manager")
        self.assertEqual(res.tags, ["role:people_manager"])
        self.assertEqual(res.score_delta, -15)

    def test_custom_seniority_patterns(self):
        prof = dict(PO_PROFILE, seniority={"lead_pattern": r"\bchief\b"})
        with use_profile(prof):
            res = run(RoleSeniorityStage(), "Chief Product Owner")
        self.assertIn("seniority:staff_principal_lead", res.tags)
        self.assertEqual(res.score_delta, 55)


class TestTitleFilterTargetRoles(unittest.TestCase):
    def test_target_role_passes_without_tech_terms(self):
        with use_profile(PO_PROFILE):
            self.assertTrue(run(TitleFilterStage(), "Product Owner", "Own the backlog.").should_continue)

    def test_non_target_non_technical_role_dropped(self):
        with use_profile(PO_PROFILE):
            self.assertFalse(run(TitleFilterStage(), "Chief of Staff", "Support the CEO.").should_continue)

    def test_negative_role_not_rescued(self):
        prof = {"target_roles": [{"name": "x", "pattern": r"\bbarista\b", "weight": -10}]}
        with use_profile(prof):
            self.assertFalse(run(TitleFilterStage(), "Barista", "Coffee.").should_continue)


if __name__ == "__main__":
    unittest.main()


class TestTitleExclusionOverride(unittest.TestCase):
    PROFILE = {
        "target_roles": [
            {
                "name": "license_compliance",
                "pattern": r"\bopen\s+source\s+(?:counsel|legal)\b|\bcommercial\s+licensing\b",
                "weight": 35,
                "override_title_exclude": True,
            },
            {"name": "product_manager", "pattern": r"\bproduct\s+manager\b", "weight": 40},
            {"name": "legal_demoted", "pattern": r"\bcounsel\b", "weight": -10, "override_title_exclude": True},
        ],
    }

    def test_opted_in_role_bypasses_hard_exclusion(self):
        with use_profile(self.PROFILE):
            self.assertTrue(run(TitleFilterStage(), "Senior Open Source Counsel").should_continue)
            self.assertTrue(run(TitleFilterStage(), "Commercial Licensing Manager").should_continue)

    def test_other_excluded_titles_still_dropped(self):
        with use_profile(self.PROFILE):
            # product_manager matches but did not opt in -> "pricing" exclusion still applies
            self.assertFalse(run(TitleFilterStage(), "Product Manager, Pricing").should_continue)
            # negative-weight roles never bypass the exclusion
            self.assertFalse(run(TitleFilterStage(), "Employment Counsel").should_continue)
            self.assertFalse(run(TitleFilterStage(), "Legal Counsel").should_continue)

    def test_without_profile_behaviour_unchanged(self):
        with use_profile({}):
            self.assertFalse(run(TitleFilterStage(), "Open Source Counsel").should_continue)
