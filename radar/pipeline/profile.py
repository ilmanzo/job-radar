"""Candidate profile & domain matching stage."""

import re
import sys
from typing import Dict, List, Optional, Pattern, Tuple

from radar.config import get_compiled_tech_stack, load_profile, load_tech_stack
from radar.models import Job, PipelineContext, ProfileMatch, RawJob
from radar.pipeline.base import PipelineStage, StageResult
from radar.pipeline.title import keywords_to_pattern


SkillMatrix = List[Tuple[str, str, int, str]]


_WARNED_PATTERNS = set()


def _is_valid_regex(pattern: str, name: str) -> bool:
    """Check a profile regex; warn once per invalid pattern instead of once per job."""
    try:
        re.compile(pattern)
        return True
    except re.error as e:
        if (name, pattern) not in _WARNED_PATTERNS:
            _WARNED_PATTERNS.add((name, pattern))
            print(f"Warning: ignoring profile entry '{name}' with invalid regex {pattern!r}: {e}", file=sys.stderr)
        return False


def _parse_skill_matrix(items) -> SkillMatrix:
    """Parse an explicit ``skill_matrix`` list from the profile."""
    parsed = []
    for item in items or []:
        if not (isinstance(item, dict) and item.get("pattern") and item.get("name")):
            continue
        pattern, name = str(item["pattern"]), str(item["name"])
        if _is_valid_regex(pattern, name):
            parsed.append((pattern, name, int(item.get("weight", 20)), item.get("pitch", "") or ""))
    return parsed


def _matrix_from_domain_expertise(items) -> SkillMatrix:
    """Derive a skill matrix from ``deep_domain_expertise`` keyword pillars."""
    parsed = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("category")
        keywords = item.get("keywords")
        if not name or not isinstance(keywords, list):
            continue
        pattern = keywords_to_pattern(keywords)
        if not pattern:
            continue
        pitch = item.get("pitch")
        if not pitch and item.get("description"):
            pitch = f"Highlight {name}: {str(item['description']).strip()}"
        parsed.append((pattern, str(name), int(item.get("weight", 20)), pitch or ""))
    return parsed


def get_active_skill_matrix(prof: Optional[Dict] = None) -> SkillMatrix:
    """Retrieve the skill matrix for the candidate profile.

    Precedence:
      1. explicit ``skill_matrix`` in the profile
      2. matrix derived from the profile's ``deep_domain_expertise`` keywords

    Returns an empty matrix when the profile defines neither; there is no
    built-in candidate default.
    """
    if prof is None:
        prof = load_profile()
    parsed = _parse_skill_matrix(prof.get("skill_matrix"))
    if parsed:
        return parsed
    return _matrix_from_domain_expertise(prof.get("deep_domain_expertise"))


def _profile_tech_item(item) -> Optional[Tuple[str, str]]:
    """Normalize a profile ``tech_stack`` entry into (name, regex pattern).

    Accepts plain strings (``"c++"``, ``"cloud-init"``) or the
    ``{name, pattern}`` mappings used by tech_stack.yaml.
    """
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip().lower()
        pattern = item.get("pattern")
        if name and pattern:
            return (name, str(pattern)) if _is_valid_regex(str(pattern), name) else None
        item = name
    name = str(item or "").strip().lower()
    if not name:
        return None
    return (name, keywords_to_pattern([name]))


def get_active_tech_stack(prof: Optional[Dict] = None) -> List[Tuple[str, Pattern]]:
    """Technologies worth reporting in the ``tech:`` tag, as (name, regex) pairs.

    Uses the profile's explicit ``tech_stack`` list when present. Otherwise the
    configured tech_stack.yaml vocabulary is narrowed to technologies covered
    by the active skill matrix, so technologies the candidate does not list are
    never reported. Without any profile the configured vocabulary is used
    unchanged. Returns an empty list when no technology applies.
    """
    if prof is None:
        prof = load_profile()
    if not prof:
        return get_compiled_tech_stack()
    explicit = prof.get("tech_stack")
    if isinstance(explicit, list) and explicit:
        items = [t for t in (_profile_tech_item(i) for i in explicit) if t]
    else:
        patterns = [p for p, _name, _w, _pitch in get_active_skill_matrix(prof)]
        items = [
            (t["name"], t["pattern"])
            for t in load_tech_stack()
            if any(re.search(p, t["name"], re.IGNORECASE) for p in patterns)
        ]
    compiled, seen = [], set()
    for name, pattern in items:
        if name in seen:
            continue
        seen.add(name)
        try:
            compiled.append((name, re.compile(pattern, re.IGNORECASE)))
        except re.error:
            compiled.append((name, re.compile(keywords_to_pattern([name]), re.IGNORECASE)))
    return compiled


def find_profile_tech_matches(text: str, prof: Optional[Dict] = None) -> List[str]:
    """Sorted unique names of the candidate's technologies mentioned in text."""
    if not text:
        return []
    return sorted({name for name, rx in get_active_tech_stack(prof) if rx.search(text)})


def evaluate_profile(title: str, content: str) -> ProfileMatch:
    """Evaluate candidate profile match percentage, matched skills, and tailored pitch bullets."""
    text = f"{title} {content}".lower()

    matched_skills = []
    matched_weights = 0
    pitch_bullets = []

    matrix = get_active_skill_matrix()
    for pattern, name, weight, pitch in matrix:
        if re.search(pattern, text, re.IGNORECASE):
            matched_skills.append(name)
            matched_weights += weight
            if pitch and len(pitch_bullets) < 3:
                pitch_bullets.append(pitch)

    match_pct = min(100, int((matched_weights / 80) * 100))

    if not pitch_bullets:
        pitch_bullets = [str(p) for p in (load_profile().get("fallback_pitch") or [])]

    return ProfileMatch(
        match_pct=match_pct,
        matched_skills=matched_skills,
        pitch_bullets=pitch_bullets,
    )


class ProfileMatchStage(PipelineStage):
    """Computes candidate skill alignment based on profile research and adds pitch bullets."""

    @property
    def name(self) -> str:
        return "profile_match"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        eval_result = evaluate_profile(raw_job.title, raw_job.content)
        job.profile = eval_result

        score_delta = 0
        tags = []
        match_pct = eval_result.match_pct

        if match_pct >= 80:
            score_delta += 15
            tags.append(f"match:{match_pct}%")
        elif match_pct >= 50:
            score_delta += 5
            tags.append(f"match:{match_pct}%")

        return StageResult(should_continue=True, score_delta=score_delta, tags=tags)
