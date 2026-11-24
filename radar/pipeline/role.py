"""Role relevance, seniority & tech stack scoring stage.

Which job titles count as a good role fit comes from the candidate profile::

    target_roles:
      - name: product_owner             # -> tag "role:product_owner"
        pattern: '\\bproduct\\s+owner\\b'  # regex matched against the job title
        weight: 35                      # score bonus for the role
        lead_bonus: 15                  # optional, staff/principal/lead/head of/director
        senior_bonus: 10                # optional, senior/sr.
        tags:                           # optional extra tags for sub-domains
          - pattern: '\\bsecurity\\b'
            tag: "domain:security"
      - name: license_compliance
        pattern: '\\bopen\\s+source\\s+counsel\\b'
        weight: 30
        override_title_exclude: true    # optional, keep titles the built-in
                                        # exclusion list would drop (legal, counsel,
                                        # commercial, partner, ...)
      - name: people_manager            # negative weights demote unwanted roles
        pattern: '\\bengineering\\s+manager\\b'
        weight: -15

    seniority:                          # optional, override seniority detection
      lead_pattern: '\\b(staff|principal|lead|head\\s+of|director)\\b'
      senior_pattern: '\\b(senior|sr\\.?)\\b'

The best (highest weight) matching role wins; seniority bonuses only apply to
roles with a positive weight. Without ``target_roles`` the built-in
systems/platform-oriented defaults below are used.
"""

import re
from typing import Dict, List, Optional, Tuple

from radar.config import load_profile
from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage, StageResult
from radar.pipeline.profile import _is_valid_regex, find_profile_tech_matches
from radar.pipeline.title import DEVOPS_PLATFORM_SRE_RE, SYSTEMS_TITLE_RE

DEFAULT_LEAD_PATTERN = r"\b(staff|principal|lead|senior\s+staff|distinguished|head\s+of|director|architect)\b"
DEFAULT_SENIOR_PATTERN = r"\b(senior|sr\.?)\b"

# Backwards compatible defaults (systems/platform engineering candidate).
DEFAULT_TARGET_ROLES: List[Dict] = [
    {
        "name": "systems_platform",
        "pattern": SYSTEMS_TITLE_RE.pattern,
        "weight": 30,
        "lead_bonus": 20,
        "senior_bonus": 10,
        "tags": [{"pattern": DEVOPS_PLATFORM_SRE_RE.pattern, "tag": "domain:devops_platform_sre"}],
    },
    {
        "name": "swe",
        "pattern": r"\b(software engineer|senior engineer|staff engineer|principal engineer)\b",
        "weight": 10,
        "lead_bonus": 15,
        "senior_bonus": 5,
    },
]


class TargetRole:
    __slots__ = ("name", "regex", "weight", "lead_bonus", "senior_bonus", "tags", "override_title_exclude")

    def __init__(self, name, regex, weight, lead_bonus, senior_bonus, tags, override_title_exclude=False):
        self.name = name
        self.regex = regex
        self.weight = weight
        self.lead_bonus = lead_bonus
        self.senior_bonus = senior_bonus
        self.tags = tags
        self.override_title_exclude = override_title_exclude


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_roles(items) -> List[TargetRole]:
    roles = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("pattern") or not item.get("name"):
            continue
        name, pattern = str(item["name"]), str(item["pattern"])
        if not _is_valid_regex(pattern, name):
            continue
        extra = []
        for sub in item.get("tags") or []:
            if isinstance(sub, dict) and sub.get("pattern") and sub.get("tag"):
                if _is_valid_regex(str(sub["pattern"]), str(sub["tag"])):
                    extra.append((re.compile(str(sub["pattern"]), re.IGNORECASE), str(sub["tag"])))
        roles.append(TargetRole(
            name=name,
            regex=re.compile(pattern, re.IGNORECASE),
            weight=_int(item.get("weight"), 20),
            lead_bonus=_int(item.get("lead_bonus"), 20),
            senior_bonus=_int(item.get("senior_bonus"), 10),
            tags=extra,
            override_title_exclude=bool(item.get("override_title_exclude", False)),
        ))
    return roles


def get_target_roles(prof: Optional[dict] = None) -> List[TargetRole]:
    """Target roles from the profile, or the built-in defaults when not configured."""
    if prof is None:
        prof = load_profile()
    roles = _parse_roles(prof.get("target_roles"))
    return roles or _parse_roles(DEFAULT_TARGET_ROLES)


def get_seniority_patterns(prof: Optional[dict] = None) -> Tuple[re.Pattern, re.Pattern]:
    if prof is None:
        prof = load_profile()
    cfg = prof.get("seniority") or {}
    lead = str(cfg.get("lead_pattern") or DEFAULT_LEAD_PATTERN)
    senior = str(cfg.get("senior_pattern") or DEFAULT_SENIOR_PATTERN)
    if not _is_valid_regex(lead, "seniority.lead_pattern"):
        lead = DEFAULT_LEAD_PATTERN
    if not _is_valid_regex(senior, "seniority.senior_pattern"):
        senior = DEFAULT_SENIOR_PATTERN
    return re.compile(lead, re.IGNORECASE), re.compile(senior, re.IGNORECASE)


def match_target_role(title: str, prof: Optional[dict] = None) -> Optional[TargetRole]:
    """Best matching target role for a title (highest weight), or None."""
    matched = [r for r in get_target_roles(prof) if r.regex.search(title or "")]
    if not matched:
        return None
    return max(matched, key=lambda r: r.weight)


def overrides_title_exclusion(title: str, prof: Optional[dict] = None) -> bool:
    """True if a positive-weight target role opted in to bypass the built-in title exclusions."""
    return any(
        r.override_title_exclude and r.weight > 0 and r.regex.search(title or "")
        for r in get_target_roles(prof)
    )


class RoleSeniorityStage(PipelineStage):
    """Evaluates role alignment against the profile's target roles, seniority tier, and tech stack."""

    @property
    def name(self) -> str:
        return "role_seniority"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        title = raw_job.title or ""
        content = raw_job.content or ""
        score_delta = 0
        tags = []

        prof = load_profile()
        role = match_target_role(title, prof)
        if role:
            score_delta += role.weight
            tags.append(f"role:{role.name}")
            tags.extend(tag for rx, tag in role.tags if rx.search(title))
            if role.weight > 0:
                lead_re, senior_re = get_seniority_patterns(prof)
                if lead_re.search(title):
                    score_delta += role.lead_bonus
                    tags.append("seniority:staff_principal_lead")
                elif senior_re.search(title):
                    score_delta += role.senior_bonus
                    tags.append("seniority:senior")

        # Tech stack matches, restricted to technologies in the candidate profile
        unique_matches = find_profile_tech_matches(f"{title} {content}", prof)
        if unique_matches:
            score_delta += min(len(unique_matches) * 5, 25)
            tags.append(f"tech:{','.join(unique_matches[:4])}")

        return StageResult(should_continue=True, score_delta=score_delta, tags=tags)
