"""Work mode stage: remote / hybrid / on-site preference from the candidate profile.

Profile format (the stage does nothing without a ``work_mode`` section)::

    work_mode:
      remote_bonus: 30       # fully remote / home based
      hybrid_bonus: 20       # partly remote, "etätyömahdollisuus"
      onsite_penalty: -35    # explicitly on-site / in-office
      unknown_penalty: -15   # no work-mode signal at all (usually on-site in practice)
      drop_onsite: false     # true removes explicitly on-site postings
      remote_patterns: []    # extra regexes, added to the built-in ones
      hybrid_patterns: []
      onsite_patterns: []
      onsite_title_patterns: []  # titles that imply on-site work (e.g. school teacher)
      ignore_patterns: []    # boilerplate removed before detection ("supports remote
                             # work where possible" in every municipal ad)

The location field is checked first (ATS feeds often say "Remote" or "Hybrid"
there), then the title and description. In the description a hybrid signal
wins over a remote one ("possibility for remote work" usually means some
office days), and remote plus on-site mentions count as hybrid. Negated
mentions ("not remote", "etätyö ei ole mahdollista") are ignored. The result
is tagged ``mode:remote|hybrid|onsite|unknown``. Postings without a
description (e.g. Workday listings) get no unknown penalty: there is nothing
to judge.
"""

import re
import sys
from typing import Any, Dict, List, Optional, Pattern

from radar.config import load_profile
from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage, StageResult

REMOTE_RE = (
    r"\b(?:fully[\s-]remote|remote[\s-]first|100\s*%\s*remote"
    r"|remote(?![\s-]+(?:sensing|control|access|monitoring|desktop|management|devices?))"
    r"|work(?:ing)?\s+from\s+(?:home|anywhere)|home[\s-]based|wfh"
    r"|etätyö\w*|etänä|täysin\s+etä\w*|etäpaik\w*|etätehtäv\w*)\b"
)
HYBRID_RE = (
    r"\b(?:hybrid\w*|hybridi\w*|remote[\s-]friendly|partly\s+remote|partially\s+remote"
    r"|flexible\s+(?:working\s+)?(?:location|arrangements?|work(?:ing)?\s+model)"
    r"|etätyömahdollisuu\w*|mahdollisuus\s+(?:osittaise\w*\s+|osittain\s+)?etätyö\w*"
    r"|osittai\w*\s+etä\w*|etäpäiv\w*|monipaikka\w*|joustava\w*\s+työskentelypaik\w*)\b"
)
ONSITE_RE = (
    r"\b(?:on[\s-]?site|in[\s-]office|office[\s-]based|in[\s-]person|not\s+remote|no\s+remote"
    r"|lähityö\w*|paikan\s+päällä|läsnäolo\w*|työ\s+tehdään\s+(?:pääosin\s+)?(?:toimistolla|koululla|paikan\s+päällä))\b"
)
NEG_BEFORE = re.compile(r"\b(?:not|no|non|never|without|ei|eikä)\b[^.;:!?]{0,20}$", re.IGNORECASE)
NEG_AFTER = re.compile(r"^\W*(?:\w+\W+){0,2}?(?:ei\b|is\s+not\b|isn't\b|not\s+(?:possible|available)\b)", re.IGNORECASE)
_WARNED = set()


def _compile(builtin: str, extra: List[Any], label: str) -> List[Pattern]:
    patterns = [re.compile(builtin, re.IGNORECASE)]
    for raw in extra or []:
        try:
            patterns.append(re.compile(str(raw), re.IGNORECASE))
        except re.error as e:
            if raw not in _WARNED:
                _WARNED.add(raw)
                print(f"[-] Warning: invalid work_mode {label} pattern {raw!r}: {e}", file=sys.stderr)
    return patterns


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_work_mode_policy(prof: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if prof is None:
        prof = load_profile()
    section = (prof or {}).get("work_mode")
    if not isinstance(section, dict):
        return None
    return {
        "remote_bonus": _int(section.get("remote_bonus"), 0),
        "hybrid_bonus": _int(section.get("hybrid_bonus"), 0),
        "onsite_penalty": _int(section.get("onsite_penalty"), 0),
        "unknown_penalty": _int(section.get("unknown_penalty"), 0),
        "drop_onsite": bool(section.get("drop_onsite", False)),
        "remote": _compile(REMOTE_RE, section.get("remote_patterns"), "remote"),
        "hybrid": _compile(HYBRID_RE, section.get("hybrid_patterns"), "hybrid"),
        "onsite": _compile(ONSITE_RE, section.get("onsite_patterns"), "onsite"),
        "onsite_title": _compile(r"(?!x)x", section.get("onsite_title_patterns"), "onsite_title"),
        "ignore": _compile(r"(?!x)x", section.get("ignore_patterns"), "ignore"),
    }


def _hit(patterns: List[Pattern], text: str, check_negation: bool = True) -> bool:
    for pattern in patterns:
        for m in pattern.finditer(text or ""):
            if not check_negation:
                return True
            before = text[max(0, m.start() - 30):m.start()]
            after = text[m.end():m.end() + 30]
            if not NEG_BEFORE.search(before) and not NEG_AFTER.search(after):
                return True
    return False


def detect_work_mode(location: str, title: str, content: str, policy: Dict[str, Any]) -> str:
    # Explicit location / title labels first ("Remote - Europe", "Helsinki (Hybrid)").
    for field in (location, title):
        if _hit(policy["hybrid"], field):
            return "hybrid"
        if _hit(policy["remote"], field):
            return "remote"
        if _hit(policy["onsite"], field):
            return "onsite"
    if _hit(policy.get("onsite_title", []), title, check_negation=False):
        return "onsite"
    for pattern in policy.get("ignore", []):
        content = pattern.sub(" ", content or "")
    remote = _hit(policy["remote"], content)
    hybrid = _hit(policy["hybrid"], content)
    # On-site patterns already encode negation ("not remote"), so skip the check.
    onsite = _hit(policy["onsite"], content, check_negation=False)
    if hybrid or (remote and onsite):
        return "hybrid"
    if remote:
        return "remote"
    if onsite:
        return "onsite"
    return "unknown"


class WorkModeStage(PipelineStage):
    """Scores remote / hybrid / on-site postings per the profile ``work_mode`` section."""

    @property
    def name(self) -> str:
        return "work_mode_stage"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        policy = get_work_mode_policy()
        if not policy:
            return StageResult(should_continue=True)
        mode = detect_work_mode(raw_job.location or "", raw_job.title or "", raw_job.content or "", policy)
        if mode == "onsite" and policy["drop_onsite"]:
            return StageResult(should_continue=False)
        if mode == "unknown" and len((raw_job.content or "").strip()) < 200:
            return StageResult(should_continue=True, tags=["mode:unknown"])
        delta = {
            "remote": policy["remote_bonus"],
            "hybrid": policy["hybrid_bonus"],
            "onsite": policy["onsite_penalty"],
            "unknown": policy["unknown_penalty"],
        }[mode]
        return StageResult(should_continue=True, score_delta=delta, tags=[f"mode:{mode}"])
