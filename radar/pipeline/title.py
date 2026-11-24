"""Title and Technical Domain filtering stage."""

import re
from radar.config import get_tech_stack_regex
from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage, StageResult

TITLE_EXCLUDE_RE = re.compile(
    r"\b("
    r"sales|pre-?sales|solutions?\s+engineer(?:ing)?|solutions?\s+architect(?:ure)?|"
    r"customer\s+success|customer\s+engineer(?:ing)?|"
    r"technical\s+account\s+manage(?:r|ment|rs)?|\btam\b|"
    r"account\s+executive|\bae\b|account\s+manage(?:r|ment|rs)?|\bam\b|business\s+development|\bbdr\b|\bsdr\b|"
    r"gtm\b|go-to-market|revops\b|revenue\s+operations|renewals?|"
    r"deal\s+pricing|monetization|pricing|"
    r"commercial|partner\s+engineer|partner\s+solutions|partner\s+architect|partner\s+manager|alliances?|"
    r"marketing|recruiter|recruiting|talent|legal|counsel|attorney|"
    r"accountant|accounting|payroll|people\s+partner|hr\b|copywriter|content\s+writer|office\s+manager|"
    r"frontend|front-end|react|angular|ui/ux|product\s+designer|graphic\s+designer|finance\s+director|"
    r"deal\s+desk|sales\s+ops|technical\s+enablement|curriculum\s+developer|"
    r"(?:deal|pricing|monetization|strategy|business|commercial|financial|revenue)\s+analyst|"
    r"junior|entry[\s-]level|"
    r"interns?|internships?|students?|co-ops?|working\s+students?|apprentices?|"
    r"stage\s+(?:curriculare|extracurriculare)|tirocini[oa]|stagist[ae]|loss\s+prevention|"
    r"construction|vendor\s+manager|retail|facility\s+manager|warehouse"
    r")\b",
    re.IGNORECASE,
)

ENGINEERING_TITLE_RE = re.compile(
    r"\b(software|developer|engineer|architect|sre|devops|platform|infrastructure|infra|technician)\b",
    re.IGNORECASE,
)

SYSTEMS_TITLE_RE = re.compile(
    r"\b(systems|platform|platform\s+eng(?:ineer(?:ing)?)?|devops|linux|kernel|ebpf|bpf|"
    r"infrastructure|infra|sre|site\s+reliability|production\s+eng(?:ineer(?:ing)?)?|"
    r"distributed|runtime|virtualization|container|core\s+os|low-level|storage|networking|"
    r"cloud\s+platform|kubernetes|cloud\s+infrastructure|openstack|automation|qe\b|quality\s+eng(?:ineer(?:ing)?)?)\b",
    re.IGNORECASE,
)

DEVOPS_PLATFORM_SRE_RE = re.compile(
    r"\b(devops|platform|site\s+reliability|sre|production\s+eng(?:ineer(?:ing)?)?|infrastructure|cloud\s+platform)\b",
    re.IGNORECASE,
)


def get_tech_stack_re() -> re.Pattern:
    """Return compiled tech stack regex dynamically from configuration."""
    return get_tech_stack_regex()


# Backward-compatibility alias
TECH_STACK_RE = get_tech_stack_regex()


def keywords_to_pattern(keywords) -> str:
    """Build a whole-word alternation regex from plain keywords.

    Handles keywords that start/end with non-word characters (e.g. ``c++``,
    ``ci/cd``) where a plain ``\\b`` anchor would never match. Longer keywords
    come first so ``c++`` wins over ``c``. Returns "" for an empty list.
    """
    terms = sorted(
        {str(k).strip().lower() for k in (keywords or []) if str(k).strip()},
        key=lambda t: (-len(t), t),
    )
    parts = []
    for term in terms:
        left = r"\b" if re.match(r"\w", term[0]) else r"(?<!\w)"
        right = r"\b" if re.match(r"\w", term[-1]) else r"(?!\w)"
        parts.append(f"{left}{re.escape(term)}{right}")
    return "|".join(parts)


class TitleFilterStage(PipelineStage):
    """Filters out non-engineering or hard-excluded business/sales roles."""

    @property
    def name(self) -> str:
        return "title_filter"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        # local import: role imports this module
        from radar.pipeline.role import match_target_role, overrides_title_exclusion

        title = raw_job.title
        content = raw_job.content or ""

        # Hard exclusion, unless the profile explicitly targets the title
        # (target role with override_title_exclude: true), e.g. open source
        # licensing counsel or commercial licensing roles.
        if TITLE_EXCLUDE_RE.search(title) and not overrides_title_exclusion(title):
            return StageResult(should_continue=False)

        # Must be technical or match tech stack
        is_eng = bool(ENGINEERING_TITLE_RE.search(title))
        is_sys = bool(SYSTEMS_TITLE_RE.search(title))
        has_tech = bool(get_tech_stack_regex().search(f"{title} {content}"))

        if is_eng or is_sys or has_tech:
            return StageResult(should_continue=True)

        # Roles the candidate explicitly targets (e.g. Product Owner) pass
        # even when the posting itself names no technology.
        role = match_target_role(title)
        return StageResult(should_continue=bool(role and role.weight > 0))
