"""Tests for the profile-driven work mode (remote / hybrid / on-site) stage."""

import unittest
from unittest.mock import patch

from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.workmode import WorkModeStage, detect_work_mode, get_work_mode_policy

PROFILE = {"work_mode": {"remote_bonus": 30, "hybrid_bonus": 20, "onsite_penalty": -35, "unknown_penalty": -15}}


def _mode(location="", title="Manager", content=""):
    return detect_work_mode(location, title, content, get_work_mode_policy(PROFILE))


def _run(profile, location="", title="Manager", content=""):
    raw = RawJob(id="1", company_id="t", title=title, location=location, url="", content=content)
    job = Job(id="1", company_id="t", title=title, location=location, url="")
    with patch("radar.pipeline.workmode.load_profile", return_value=profile):
        return WorkModeStage().process(raw, job, PipelineContext(target=CompanyTarget(id="t", name="T")))


class TestDetectWorkMode(unittest.TestCase):
    def test_location_labels(self):
        self.assertEqual(_mode("Remote - Europe"), "remote")
        self.assertEqual(_mode("Home based - EMEA"), "remote")
        self.assertEqual(_mode("Berlin (Hybrid)"), "hybrid")
        self.assertEqual(_mode("Berlin, Germany (On-site)"), "onsite")

    def test_location_wins_over_content(self):
        self.assertEqual(_mode("Remote", content="Our office in Berlin has on-site events"), "remote")

    def test_finnish_content(self):
        self.assertEqual(_mode("Tampere", content="Tehtävä tehdään etätyönä."), "remote")
        self.assertEqual(_mode("Tampere", content="Tarjoamme etätyömahdollisuuden."), "hybrid")
        self.assertEqual(_mode("Tampere", content="Mahdollisuus osittaiseen etätyöhön."), "hybrid")
        self.assertEqual(_mode("Tampere", content="Työ on lähityötä koululla."), "onsite")
        self.assertEqual(_mode("Tampere", content="Etätyö ei ole mahdollista."), "unknown")

    def test_english_content(self):
        self.assertEqual(_mode("Berlin", content="This is a fully remote role."), "remote")
        self.assertEqual(_mode("Berlin", content="We work in a hybrid model, 2 days in office."), "hybrid")
        self.assertEqual(_mode("Berlin", content="Remote work possible but weekly on-site meetings."), "hybrid")
        self.assertEqual(_mode("Berlin", content="This position is not remote."), "onsite")
        self.assertEqual(_mode("Berlin", content="Experience with remote sensing data."), "unknown")
        self.assertEqual(_mode("Berlin", content="Teach mathematics in our school."), "unknown")


class TestWorkModeStage(unittest.TestCase):
    def test_no_section_is_neutral(self):
        res = _run({}, "Remote")
        self.assertTrue(res.should_continue)
        self.assertEqual(res.score_delta, 0)
        self.assertEqual(res.tags, [])

    def test_scores_and_tags(self):
        self.assertEqual((_run(PROFILE, "Remote").score_delta, _run(PROFILE, "Remote").tags), (30, ["mode:remote"]))
        self.assertEqual(_run(PROFILE, "Lisbon (Hybrid)").score_delta, 20)
        self.assertEqual(_run(PROFILE, "Lisbon", content="Work is on-site.").score_delta, -35)
        long_text = "You will plan releases and work with partners. " * 10
        self.assertEqual(_run(PROFILE, "Lisbon", content=long_text).tags, ["mode:unknown"])
        self.assertEqual(_run(PROFILE, "Lisbon", content=long_text).score_delta, -15)
        # no description at all: nothing to judge, no penalty
        self.assertEqual(_run(PROFILE, "Lisbon").tags, ["mode:unknown"])
        self.assertEqual(_run(PROFILE, "Lisbon").score_delta, 0)

    def test_onsite_title_and_ignore_patterns(self):
        prof = {"work_mode": dict(PROFILE["work_mode"],
                                  onsite_title_patterns=[r"\bstore\s+manager\b"],
                                  remote_patterns=[r"\bvirtual\s+assistant\b"],
                                  ignore_patterns=[r"supports\s+remote\s+work\s+wherever[^.]*"])}
        policy = get_work_mode_policy(prof)
        boiler = "The group supports remote work wherever the role allows."
        self.assertEqual(detect_work_mode("Madrid", "Store Manager", "Remote work. " + boiler, policy), "onsite")
        self.assertEqual(detect_work_mode("Madrid", "Virtual Assistant", "", policy), "remote")
        self.assertEqual(detect_work_mode("Madrid", "Program Manager", boiler, policy), "unknown")
        self.assertEqual(detect_work_mode("Madrid", "Program Manager", boiler + " Fully remote.", policy), "remote")

    def test_drop_onsite_and_extra_patterns(self):
        prof = {"work_mode": {"drop_onsite": True, "onsite_patterns": [r"\bkoululla\b"], "remote_patterns": ["(bad"]}}
        self.assertFalse(_run(prof, "Oslo", content="Työ tehdään koululla.").should_continue)
        self.assertTrue(_run(prof, "Oslo", content="Etätyö").should_continue)


if __name__ == "__main__":
    unittest.main()
