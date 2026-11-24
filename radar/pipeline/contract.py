"""Contract type & company tier scoring stage."""

import re
import sys
from typing import Any, Dict, List, Optional, Pattern

from radar.config import get_location_config, load_profile
from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage, StageResult

# B2B / contracting detection. "B2B" and "freelance" alone are far more often about
# the market ("B2B SaaS") or audience ("hobbyists and freelancers") than about the
# engagement, so the body pattern only matches contract terms; the title pattern
# also takes bare freelance / contractor and B2B in brackets ("(Freelance / B2B)").
B2B_RE = re.compile(
    r"\b(?:"
    r"b2b\s+(?:contract|agreement|cooperation|co-operation|basis|engagement|employment|form|model|terms|rate)"
    r"|b2b\s*(?:/|or|lub)\s*(?:uop|uod|employment\s+contract|permanent)"
    r"|(?:employment|contract)\s+type:?\s*(?:b2b|freelance|contractor|contract)\b"
    r"|contractor\s+only|independent\s+contractor|corp-to-corp|c2c|1099\s+contractor"
    r"|partita\s+iva|vat\s+number"
    r"|freelance\s+(?:contract|position|role|basis|engagement|assignment|opportunity|project|job)s?"
    r"|as\s+an?\s+(?:freelancer|independent\s+contractor)"
    r")\b",
    re.IGNORECASE,
)
B2B_TITLE_RE = re.compile(
    r"\b(?:freelance|freelancers?|contractor|b2b\s+contract)\b|[(\[/]\s*(?:b2b|contract)\s*[)\]/]",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(r"\b(?:not|no|non|never|without)\b[^.;:!?]{0,25}$", re.IGNORECASE)

_INVALID_PATTERNS_WARNED = set()


def get_contract_policy(prof: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read the profile ``contract`` section.

    ``b2b``: ``drop`` (default) removes B2B/freelance/contractor postings;
    ``accept`` keeps them, adds ``b2b_bonus`` (default 0) and tags them
    ``contract:b2b``. ``b2b_patterns`` lists extra regexes that mark a
    posting as B2B (e.g. local terms for sole traders or business ids).
    """
    if prof is None:
        prof = load_profile()
    section = (prof or {}).get("contract") or {}
    mode = str(section.get("b2b", "drop")).strip().lower()
    try:
        bonus = int(section.get("b2b_bonus", 0) or 0)
    except (TypeError, ValueError):
        bonus = 0
    patterns: List[Pattern] = []
    for raw in section.get("b2b_patterns") or []:
        try:
            patterns.append(re.compile(str(raw), re.IGNORECASE))
        except re.error as e:
            if raw not in _INVALID_PATTERNS_WARNED:
                _INVALID_PATTERNS_WARNED.add(raw)
                print(f"[-] Warning: invalid contract b2b_pattern {raw!r}: {e}", file=sys.stderr)
    return {"accept_b2b": mode == "accept", "b2b_bonus": bonus, "b2b_patterns": patterns}


def _affirmative_match(pattern: Pattern, text: str) -> bool:
    """True if ``pattern`` matches somewhere not negated ("not a contract or freelance position")."""
    for m in pattern.finditer(text):
        if not NEGATION_RE.search(text[max(0, m.start() - 40):m.start()]):
            return True
    return False


def is_b2b_posting(title: str, content: str, policy: Dict[str, Any]) -> bool:
    if B2B_TITLE_RE.search(title or ""):
        return True
    text = f"{title or ''} {content or ''}"
    return any(_affirmative_match(p, text) for p in [B2B_RE] + policy["b2b_patterns"])


class ContractStage(PipelineStage):
    """Filters (or, per profile, accepts) B2B roles and computes tier + legal entity bonuses."""

    @property
    def name(self) -> str:
        return "contract_stage"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        company = context.target

        score_delta = 0
        tags = []

        # Contract check: B2B / freelance postings are dropped unless the profile accepts them
        policy = get_contract_policy()
        if is_b2b_posting(raw_job.title, raw_job.content or "", policy):
            if not policy["accept_b2b"]:
                return StageResult(should_continue=False)
            score_delta += policy["b2b_bonus"]
            tags.append("contract:b2b")

        # Company tier
        tier = company.tier
        if tier == "big_tech":
            score_delta += 35
            tags.append("tier:big_tech")
        elif tier == "enterprise_infra":
            score_delta += 30
            tags.append("tier:enterprise_infra")
        elif tier == "scaleup":
            score_delta += 15
            tags.append("tier:scaleup")

        # Legal entity / EOR bonus (only awarded if role is direct home country or broad global remote)
        # Bypassed if single-country foreign restriction is present
        loc_cfg = get_location_config()
        home_country = loc_cfg["home_country"]
        is_foreign_restricted = any("loc:foreign_restriction" in t for t in job.tags)

        if not is_foreign_restricted:
            if company.has_home_entity():
                score_delta += 35
                tags.append(f"legal:{home_country[:2].lower()}_entity")
                tags.append("legal:home_entity")
            elif company.eor_supported:
                score_delta += 25
                tags.append("legal:eor")

        return StageResult(should_continue=True, score_delta=score_delta, tags=tags)
