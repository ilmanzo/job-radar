"""Profile-driven skill matching and tech-stack tagging must follow the candidate profile."""

import os
import unittest
from unittest.mock import patch

from radar.config import BASE_DIR, _env_path
from radar.models import CompanyTarget, Job, PipelineContext, RawJob
from radar.pipeline.profile import (
    evaluate_profile,
    get_active_skill_matrix,
    find_profile_tech_matches,
    get_active_tech_stack,
)
from radar.pipeline.role import RoleSeniorityStage
from radar.config import get_compiled_tech_stack
from radar.pipeline.title import keywords_to_pattern

DOMAIN_PROFILE = {
    "candidate": {"name": "Test"},
    "deep_domain_expertise": [
        {"category": "Cloud Architecture", "description": "AWS infra.", "keywords": ["aws", "cloud"]},
        {"category": "Scripting Languages", "description": "Tools.", "keywords": ["python", "bash"]},
        {"category": "Packaging", "description": "Distros.", "keywords": ["c++", "rpm"]},
    ],
}

MATRIX_PROFILE = {
    "skill_matrix": [
        {"pattern": r"\bpython\b", "name": "Python", "weight": 40, "pitch": "py"},
        {"pattern": r"\blinux\b", "name": "Linux", "weight": 40},
        {"pattern": r"([unclosed", "name": "Broken"},
    ],
}

RUST_JOB = ("Staff Software Engineer, Tools & Systems", "We write C, Rust and Python on the cloud.")


def use_profile(prof):
    """Patch every module that reads the candidate profile."""
    from contextlib import ExitStack

    stack = ExitStack()
    for target in ("radar.pipeline.profile.load_profile", "radar.pipeline.role.load_profile"):
        stack.enter_context(patch(target, return_value=prof))
    return stack


def _role_tags(title, content):
    raw = RawJob(id="1", company_id="t", title=title, location="Remote", url="", content=content)
    job = Job(id="1", company_id="t", title=title, location="Remote", url="")
    return RoleSeniorityStage().process(raw, job, PipelineContext(target=CompanyTarget(id="t", name="T"))).tags


class TestSkillMatrixSelection(unittest.TestCase):
    def test_no_profile_has_empty_matrix(self):
        self.assertEqual(get_active_skill_matrix({}), [])

    def test_domain_expertise_is_used_instead_of_default(self):
        matrix = get_active_skill_matrix(DOMAIN_PROFILE)
        self.assertEqual([m[1] for m in matrix], ["Cloud Architecture", "Scripting Languages", "Packaging"])

    def test_explicit_matrix_wins_and_invalid_regex_skipped(self):
        matrix = get_active_skill_matrix(MATRIX_PROFILE)
        self.assertEqual([m[1] for m in matrix], ["Python", "Linux"])

    def test_rust_not_matched_when_profile_lacks_it(self):
        with use_profile(DOMAIN_PROFILE):
            res = evaluate_profile(*RUST_JOB)
        self.assertNotIn("Rust", res.matched_skills)
        self.assertEqual(res.matched_skills, ["Cloud Architecture", "Scripting Languages"])
        self.assertEqual(res.match_pct, 50)


class TestTechStackTag(unittest.TestCase):
    def test_tech_tag_excludes_technologies_outside_profile(self):
        with use_profile(DOMAIN_PROFILE):
            tags = _role_tags(*RUST_JOB)
        tech = [t for t in tags if t.startswith("tech:")]
        self.assertEqual(tech, ["tech:cloud,python"])

    def test_explicit_tech_stack(self):
        prof = dict(MATRIX_PROFILE, tech_stack=["rust", "c++"])
        with use_profile(prof):
            tags = _role_tags("Engineer", "Modern C++ and Rust services, some Python")
        self.assertIn("tech:c++,rust", tags)

    def test_no_matching_tech_means_no_tag(self):
        prof = {"skill_matrix": [{"pattern": r"\bproduct owner\b", "name": "PO"}]}
        self.assertEqual(get_active_tech_stack(prof), [])
        with use_profile(prof):
            tags = _role_tags(*RUST_JOB)
        self.assertFalse([t for t in tags if t.startswith("tech:")])

    def test_without_profile_generic_vocabulary(self):
        self.assertEqual(get_active_tech_stack({}), get_compiled_tech_stack())

    def test_profile_tech_stack_accepts_name_pattern_entries(self):
        prof = dict(MATRIX_PROFILE, tech_stack=["cloud-init", {"name": "golang", "pattern": r"\b(golang|go)\b"}])
        self.assertEqual(
            find_profile_tech_matches("Go services configured with cloud-init", prof),
            ["cloud-init", "golang"],
        )

    def test_skill_matrix_narrows_configured_tech_stack(self):
        prof = {"skill_matrix": [{"pattern": r"\bpython\b|\bkubernetes\b", "name": "Py"}]}
        vocabulary = [
            {"name": n, "pattern": rf"\b{n}\b"} for n in ("python", "rust", "kubernetes", "cloud")
        ]
        with patch("radar.pipeline.profile.load_tech_stack", return_value=vocabulary):
            names = [name for name, _rx in get_active_tech_stack(prof)]
        self.assertEqual(sorted(names), ["kubernetes", "python"])

    def test_keywords_pattern_handles_symbols(self):
        import re
        pat = re.compile(keywords_to_pattern(["c", "c++", "ci/cd"]), re.IGNORECASE)
        self.assertEqual(pat.findall("C++ and C with CI/CD, not abc"), ["C++", "C", "CI/CD"])


class TestEnvPathResolution(unittest.TestCase):
    def test_relative_env_path_resolves_against_project_root(self):
        cwd = os.getcwd()
        try:
            os.chdir("/")
            with patch.dict(os.environ, {"JOB_RADAR_PROFILE": "data/profile.example.yaml"}):
                self.assertEqual(_env_path("JOB_RADAR_PROFILE"), os.path.join(BASE_DIR, "data/profile.example.yaml"))
        finally:
            os.chdir(cwd)

    def test_unset_env_path(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(_env_path("JOB_RADAR_PROFILE"))


if __name__ == "__main__":
    unittest.main()
