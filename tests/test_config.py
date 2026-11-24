"""Tests for decoupled configuration loaders, environment variable resolution, and bugfixes."""

import os
import unittest
from unittest.mock import patch

from radar.config import (
    find_tech_matches,
    get_candidate_info,
    get_location_config,
    get_obsidian_vault_path,
    get_salary_expectations,
    get_tech_stack_regex,
    get_telegram_config,
    load_dotenv_if_present,
    load_profile,
    load_tech_stack,
)
from radar.db import get_db
from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.contract import ContractStage
from radar.pipeline.freshness import FreshnessStage
from radar.pipeline.location import LocationStage
from radar.pipeline.profile import evaluate_profile
from radar.pipeline.role import RoleSeniorityStage
from radar.pipeline.salary import SalaryStage
from radar.pipeline.title import TitleFilterStage


class TestConfigAndEnvironment(unittest.TestCase):
    def test_telegram_creds_no_hardcoded_chat_id(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("radar.config.load_settings", return_value={}):
                cfg = get_telegram_config()
                self.assertIsNone(cfg.get("chat_id"))

    def test_telegram_creds_from_env(self):
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "TELEGRAM_CHAT_ID": "987654321",
            "JOB_RADAR_NOTIFY_MIN_SCORE": "90",
            "JOB_RADAR_NOTIFY_MIN_SALARY": "140000",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            cfg = get_telegram_config()
            self.assertEqual(cfg["bot_token"], "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
            self.assertEqual(cfg["chat_id"], 987654321)
            self.assertEqual(cfg["min_score"], 90)
            self.assertEqual(cfg["min_salary"], 140000)

    def test_obsidian_vault_path_env_override(self):
        custom_path = "/tmp/my_custom_vault"
        with patch.dict(os.environ, {"OBSIDIAN_VAULT_PATH": custom_path}, clear=True):
            resolved = get_obsidian_vault_path()
            self.assertEqual(resolved, custom_path)

    def test_candidate_info_defaults(self):
        cand = get_candidate_info()
        self.assertIn("name", cand)
        self.assertIn("headline", cand)
        self.assertIn("location", cand)
        self.assertTrue(cand["name"])

    def test_salary_expectations_tiers(self):
        tiers = get_salary_expectations()
        self.assertIn("high", tiers)
        self.assertIn("mid", tiers)
        self.assertIn("low", tiers)
        self.assertGreater(tiers["high"], tiers["low"])

    def test_salary_stage_thresholds(self):
        stage = SalaryStage()
        ctx = PipelineContext(target=CompanyTarget(id="test", name="Test"))

        # Job matching baseline 85k exactly -> should receive positive bonus (+15), not penalty
        raw_85 = RawJob(id="1", company_id="test", title="Dev", location="Remote", url="", content="€85,000 - €95,000")
        job_85 = Job(id="1", company_id="test", title="Dev", location="Remote", url="")
        res_85 = stage.process(raw_85, job_85, ctx)
        self.assertEqual(res_85.score_delta, 15)

        # Job below 85k baseline (e.g. 70k) -> should receive penalty (-10)
        raw_70 = RawJob(id="2", company_id="test", title="Dev", location="Remote", url="", content="€60,000 - €70,000")
        job_70 = Job(id="2", company_id="test", title="Dev", location="Remote", url="")
        res_70 = stage.process(raw_70, job_70, ctx)
        self.assertEqual(res_70.score_delta, -10)

    @patch("radar.pipeline.contract.load_profile", return_value={})
    def test_contract_stage_drops_b2b(self, _mock_profile):
        stage = ContractStage()
        target = CompanyTarget(id="test", name="Test", tier="scaleup")
        ctx = PipelineContext(target=target)

        # Standard role passes
        raw_perm = RawJob(id="p1", company_id="test", title="Staff Engineer", location="Remote", url="", content="Full-time permanent role")
        job_perm = Job(id="p1", company_id="test", title="Staff Engineer", location="Remote", url="")
        res_perm = stage.process(raw_perm, job_perm, ctx)
        self.assertTrue(res_perm.should_continue)

        # B2B in title dropped
        raw_b2b_title = RawJob(id="b1", company_id="test", title="Staff Engineer (Freelance / B2B)", location="Remote", url="", content="Work with our team")
        job_b2b_title = Job(id="b1", company_id="test", title="Staff Engineer (Freelance / B2B)", location="Remote", url="")
        res_b2b_title = stage.process(raw_b2b_title, job_b2b_title, ctx)
        self.assertFalse(res_b2b_title.should_continue)

        # B2B / Partita IVA in content dropped
        raw_b2b_content = RawJob(id="b2", company_id="test", title="Staff Engineer", location="Remote", url="", content="Requires Partita IVA or independent contractor agreement")
        job_b2b_content = Job(id="b2", company_id="test", title="Staff Engineer", location="Remote", url="")
        res_b2b_content = stage.process(raw_b2b_content, job_b2b_content, ctx)
        self.assertFalse(res_b2b_content.should_continue)

    def test_evaluate_profile_pitch_bullets_generic(self):
        res = evaluate_profile("eBPF Kernel Engineer", "Working on Linux kernel tracing and uprobes.")
        self.assertGreater(res.match_pct, 0)
        self.assertTrue(len(res.pitch_bullets) > 0)
        for b in res.pitch_bullets:
            self.assertIsInstance(b, str)

    def test_evaluate_profile_python_and_cloud(self):
        res = evaluate_profile("Cloud Platform Engineer", "Developing distributed cloud infrastructure with Python and AWS.")
        self.assertGreater(res.match_pct, 0)
        matched_str = " ".join(res.matched_skills)
        self.assertIn("Python", matched_str)
        self.assertIn("Cloud", matched_str)

    def test_location_config_from_env(self):
        env_vars = {
            "CANDIDATE_COUNTRY": "Germany",
            "CANDIDATE_ALLOWED_COUNTRIES": "Austria, Switzerland",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            loc_cfg = get_location_config()
            self.assertEqual(loc_cfg["home_country"], "Germany")
            self.assertEqual(loc_cfg["allowed_countries"], ["Austria", "Switzerland"])

    def test_location_stage_with_custom_country(self):
        env_vars = {
            "CANDIDATE_COUNTRY": "Germany",
            "CANDIDATE_ALLOWED_COUNTRIES": "Austria",
            "CANDIDATE_REMOTE_ONLY": "false",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            stage = LocationStage()
            target = CompanyTarget(id="testcomp", name="Test Comp")
            ctx = PipelineContext(target=target)

            raw_de = RawJob(id="1", company_id="testcomp", title="Systems Engineer", location="Berlin, Germany", url="")
            job_de = Job(id="1", company_id="testcomp", title="Systems Engineer", location="Berlin, Germany", url="")
            res_de = stage.process(raw_de, job_de, ctx)
            self.assertTrue(res_de.should_continue)
            self.assertEqual(res_de.score_delta, 25)
            self.assertIn("loc:home_country", res_de.tags)
            self.assertTrue(job_de.is_home_direct)

            raw_uk = RawJob(id="2", company_id="testcomp", title="Systems Engineer (Remote, UK only)", location="London, UK", url="")
            job_uk = Job(id="2", company_id="testcomp", title="Systems Engineer (Remote, UK only)", location="London, UK", url="")
            res_uk = stage.process(raw_uk, job_uk, ctx)
            self.assertTrue(res_uk.should_continue)
            self.assertEqual(res_uk.score_delta, -40)
            self.assertIn("loc:foreign_restriction(-40)", res_uk.tags)

    def test_location_no_false_positive_on_common_words(self):
        stage = LocationStage()
        target = CompanyTarget(id="testcomp", name="Test Comp")
        ctx = PipelineContext(target=target)

        # "status", "focus", "bonus" contain "us" as substring, but must NOT trigger US foreign lock
        raw = RawJob(
            id="status1",
            company_id="testcomp",
            title="Status Monitoring Platform Engineer (EMEA Remote)",
            location="Remote, Europe",
            url="",
        )
        job = Job(id="status1", company_id="testcomp", title=raw.title, location=raw.location, url="")
        res = stage.process(raw, job, ctx)
        self.assertTrue(res.should_continue)
        self.assertNotIn("loc:foreign_restriction(-40)", res.tags)
        self.assertNotIn("loc:foreign_restriction(-40)", res.tags)
        self.assertEqual(res.score_delta, 10)  # emea_remote bonus

    def test_location_stage_remote_only_filters(self):
        stage = LocationStage()
        target = CompanyTarget(id="testcomp", name="Test Comp")
        ctx = PipelineContext(target=target)

        env_strict_remote = {
            "CANDIDATE_COUNTRY": "Italy",
            "CANDIDATE_ALLOWED_COUNTRIES": "Italy",
            "CANDIDATE_REMOTE_ONLY": "true",
            "CANDIDATE_CITY": "",
        }
        with patch.dict(os.environ, env_strict_remote, clear=True):
            # Remote Italy passes
            raw_rem = RawJob(id="r1", company_id="testcomp", title="Systems Dev", location="Remote, Italy", url="")
            job_rem = Job(id="r1", company_id="testcomp", title="Systems Dev", location="Remote, Italy", url="")
            res_rem = stage.process(raw_rem, job_rem, ctx)
            self.assertTrue(res_rem.should_continue)

            # Flexible Italy passes
            raw_flex = RawJob(id="r2", company_id="testcomp", title="Systems Dev", location="Flexible - Italy", url="")
            job_flex = Job(id="r2", company_id="testcomp", title="Systems Dev", location="Flexible - Italy", url="")
            res_flex = stage.process(raw_flex, job_flex, ctx)
            self.assertTrue(res_flex.should_continue)

            # On-site / City-bound in Milan (different city, no remote keyword) dropped
            raw_milan = RawJob(id="r3", company_id="testcomp", title="Data Center Tech", location="IT, Milan, Italy", url="")
            job_milan = Job(id="r3", company_id="testcomp", title="Data Center Tech", location="IT, Milan, Italy", url="")
            res_milan = stage.process(raw_milan, job_milan, ctx)
            self.assertFalse(res_milan.should_continue)

            # Hybrid in Rome dropped
            raw_rome_hybrid = RawJob(id="r4", company_id="testcomp", title="Engineer (Hybrid)", location="Rome, Italy", url="")
            job_rome_hybrid = Job(id="r4", company_id="testcomp", title="Engineer (Hybrid)", location="Rome, Italy", url="")
            res_rome_hybrid = stage.process(raw_rome_hybrid, job_rome_hybrid, ctx)
            self.assertFalse(res_rome_hybrid.should_continue)

        # With specific city allowed:
        env_city_remote = {
            "CANDIDATE_COUNTRY": "Italy",
            "CANDIDATE_ALLOWED_COUNTRIES": "Italy",
            "CANDIDATE_REMOTE_ONLY": "true",
            "CANDIDATE_CITY": "Milan",
        }
        with patch.dict(os.environ, env_city_remote, clear=True):
            # Milan hybrid is accepted because it matches candidate home city
            raw_milan_hyb = RawJob(id="r5", company_id="testcomp", title="Dev (Hybrid)", location="Milan, Italy", url="")
            job_milan_hyb = Job(id="r5", company_id="testcomp", title="Dev (Hybrid)", location="Milan, Italy", url="")
            res_milan_hyb = stage.process(raw_milan_hyb, job_milan_hyb, ctx)
            self.assertTrue(res_milan_hyb.should_continue)

            # Rome hybrid is dropped because it's a different city
            raw_rome_hyb = RawJob(id="r6", company_id="testcomp", title="Dev (Hybrid)", location="Rome, Italy", url="")
            job_rome_hyb = Job(id="r6", company_id="testcomp", title="Dev (Hybrid)", location="Rome, Italy", url="")
            res_rome_hyb = stage.process(raw_rome_hyb, job_rome_hyb, ctx)
            self.assertFalse(res_rome_hyb.should_continue)

    def test_freshness_unparseable_date_is_neutral(self):
        stage = FreshnessStage()
        raw = RawJob(id="f1", company_id="testcomp", title="Systems Engineer", location="Remote", url="", posted_date="invalid-date")
        job = Job(id="f1", company_id="testcomp", title=raw.title, location=raw.location, url="")
        ctx = PipelineContext(target=CompanyTarget(id="testcomp", name="Test Comp"), first_seen=None)
        res = stage.process(raw, job, ctx)
        self.assertTrue(res.should_continue)
        self.assertEqual(res.score_delta, 0)
        self.assertNotIn("age:fresh(<7d)", res.tags)

    def test_db_schema_indexes_exist(self):
        conn = get_db(":memory:")
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        index_names = {r["name"] for r in rows}
        self.assertIn("idx_jobs_active_score", index_names)
        self.assertIn("idx_jobs_company", index_names)
        self.assertIn("idx_jobs_salary", index_names)

    def test_tech_stack_loading_and_matching(self):
        tech_list = load_tech_stack()
        self.assertGreater(len(tech_list), 10)
        matches = find_tech_matches("We build cloud platform systems in C, Python, and Rust.")
        self.assertEqual(matches, ["c", "cloud", "python", "rust"])

    def test_role_seniority_stage_tech_tagging(self):
        stage = RoleSeniorityStage()
        target = CompanyTarget(id="testcomp", name="Test Comp")
        ctx = PipelineContext(target=target)

        raw = RawJob(
            id="t1",
            company_id="testcomp",
            title="Systems Engineer",
            location="Remote",
            url="",
            content="Working on cloud automation with Python, Rust, and low-level C internals.",
        )
        job = Job(id="t1", company_id="testcomp", title=raw.title, location=raw.location, url="")
        # Without a candidate profile the full configured tech stack applies.
        with patch("radar.pipeline.role.load_profile", return_value={}):
            res = stage.process(raw, job, ctx)
        self.assertTrue(res.should_continue)
        self.assertIn("tech:c,cloud,python,rust", res.tags)
        # 30 (systems) + 20 (4 tech matches * 5) = 50
        self.assertEqual(res.score_delta, 50)

    def test_tech_stack_word_boundaries(self):
        matches = find_tech_matches("Monitoring system status and focus with cargo economic tools.")
        self.assertNotIn("c", matches)
        self.assertNotIn("go", matches)

    def test_title_filter_stage_tech_stack_pass(self):
        stage = TitleFilterStage()
        target = CompanyTarget(id="testcomp", name="Test Comp")
        ctx = PipelineContext(target=target)

        raw = RawJob(
            id="tf1",
            company_id="testcomp",
            title="Core Platform Specialist",
            location="Remote",
            url="",
            content="Heavy use of eBPF and Linux kernel tracing.",
        )
        job = Job(id="tf1", company_id="testcomp", title=raw.title, location=raw.location, url="")
        res = stage.process(raw, job, ctx)
        self.assertTrue(res.should_continue)


if __name__ == "__main__":
    unittest.main()
