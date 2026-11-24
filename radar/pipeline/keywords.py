"""Profile keyword weighting stage (``scoring_weights`` in the candidate profile).

Profile format::

    scoring_weights:
      title_cap: 30          # optional, max bonus from title keywords
      body_cap: 20           # optional, max bonus from description keywords
      penalty_cap: 40        # optional, max malus from negative weights
      title_keywords:
        productowner: 30     # matches "Product Owner", "product-owner", "ProductOwner"
        embedded: 35         # matches "embedded", "embedding"
        java: -20            # negative weights penalise unwanted stacks
      body_keywords:
        commoncriteria: 20   # matches "Common Criteria"
        licenses: 20         # matches "license", "licenses", "licensing"

Matching is deliberately forgiving so keys can be written as single tokens:

* case-insensitive, whole-word;
* separators are optional: ``opensource`` matches "open source"/"open-source",
  and a key written with separators ("common criteria") matches the joined form;
* light inflection: plural, -ed/-ing and -y/-ies variants of the key
  (``releasing`` matches "release", "released", "releases");
* a trailing ``*`` makes the last token a prefix, for words with many
  variants: ``virtuali*`` matches "virtualisation", "virtualization",
  "virtualised".

Scoring:

* each keyword counts once per job (no keyword-stuffing inflation);
* a keyword already scored in the title is not scored again in the body;
* body keywords mentioned repeatedly get a modest emphasis boost (max 1.4x);
* positive contributions are summed and passed through a saturating curve
  ``cap * (1 - exp(-raw / cap))``: the first strong hits count most, and the
  total can never exceed the cap, keeping this stage in proportion with the
  other pipeline stages;
* negative weights are summed separately and clamped to ``-penalty_cap``.
"""

import math
import re
from functools import lru_cache
from typing import Dict, List, Optional, Pattern, Tuple

from radar.config import load_profile
from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage, StageResult

DEFAULT_TITLE_CAP = 30
DEFAULT_BODY_CAP = 20
DEFAULT_PENALTY_CAP = 40

# Separators that may appear (or not) between parts of a compound keyword.
_SEP = r"[\s\-_/.]?"
# Single tokens at least this long may be split anywhere ("productowner").
_COMPOUND_MIN_LEN = 6


def _inflect(token: str) -> Tuple[str, str]:
    """Split a token into (stem, suffix-regex) covering common English inflections."""
    n = len(token)
    if n > 5 and token.endswith("ies"):
        return token[:-3], r"(?:y|ies)"
    if n > 4 and token.endswith("y") and token[-2] not in "aeiou":
        return token[:-1], r"(?:y|ies)"
    if n > 6 and token.endswith("ing"):
        return token[:-3], r"(?:e|es|ed|ing|er|ers)?"
    if n > 5 and token.endswith("ed"):
        return token[:-2], r"(?:e|es|ed|ing)?"
    if n > 5 and token.endswith("es"):
        return token[:-2], r"(?:e|es|ed|ing)?"
    if n > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1], r"s?"
    if n > 4 and token.endswith("e"):
        return token[:-1], r"(?:e|es|ed|ing)"
    return token, r"(?:s|es)?"


def _spell(chunk: str, token: Optional[str] = None) -> str:
    """Escape a chunk, allowing optional separators inside long compound tokens."""
    if len(token or chunk) >= _COMPOUND_MIN_LEN and chunk.isalpha():
        return _SEP.join(re.escape(ch) for ch in chunk)
    return re.escape(chunk)


def keyword_pattern(key: str) -> Optional[str]:
    """Build a tolerant whole-word regex for a ``scoring_weights`` key."""
    key = str(key).strip().lower()
    prefix = key.endswith("*")
    tokens = [t for t in re.split(r"[\s\-_/.]+", key.rstrip("*")) if t]
    if not tokens:
        return None
    *head, last = tokens
    if prefix:
        stem, suffix = last, r"\w*"
    else:
        stem, suffix = _inflect(last) if last.isalpha() else (last, "")
    parts = [_spell(t) for t in head] + [_spell(stem, last) + suffix]
    body = _SEP.join(parts)
    left = r"\b" if re.match(r"\w", tokens[0][0]) else r"(?<!\w)"
    right = r"\b" if suffix or re.match(r"\w", last[-1]) else r"(?!\w)"
    return f"{left}{body}{right}"


def _normalize_key(key: str) -> str:
    return re.sub(r"[\s\-_/.]+", "", str(key).strip().lower())


def _parse_weights(raw) -> Dict[str, Tuple[str, int]]:
    """Map normalized key -> (original spelling, weight).

    Spellings of the same keyword ('open source', 'open-source', 'opensource')
    are merged; the last one wins. Zero and non-numeric weights are ignored.
    """
    weights: Dict[str, Tuple[str, int]] = {}
    if not isinstance(raw, dict):
        return weights
    for key, value in raw.items():
        try:
            weight = int(value)
        except (TypeError, ValueError):
            continue
        norm = _normalize_key(key)
        if norm and weight:
            weights[norm] = (str(key), weight)
    return weights


@lru_cache(maxsize=256)
def _compile(key: str) -> Optional[Pattern]:
    pattern = keyword_pattern(key)
    return re.compile(pattern, re.IGNORECASE) if pattern else None


def _saturate(raw: float, cap: int) -> int:
    if raw <= 0 or cap <= 0:
        return 0
    return int(round(cap * (1 - math.exp(-raw / cap))))


def _cap(cfg: dict, name: str, default: int) -> int:
    try:
        return max(0, int(cfg.get(name, default)))
    except (TypeError, ValueError):
        return default


def evaluate_keywords(title: str, content: str, prof: Optional[dict] = None) -> Tuple[int, List[str]]:
    """Return (score_delta, matched keyword names ordered by contribution)."""
    if prof is None:
        prof = load_profile()
    cfg = prof.get("scoring_weights") or {}
    if not isinstance(cfg, dict):
        return 0, []

    title_w = _parse_weights(cfg.get("title_keywords"))
    body_w = _parse_weights(cfg.get("body_keywords"))
    if not title_w and not body_w:
        return 0, []

    title = title or ""
    full_text = f"{title}\n{content or ''}"

    positive: List[Tuple[float, str]] = []
    penalty = 0.0
    scored = set()

    for norm, (key, weight) in title_w.items():
        rx = _compile(key)
        if rx and rx.search(title):
            scored.add(norm)
            if weight > 0:
                positive.append((weight, norm))
            else:
                penalty += weight

    body_pos: List[Tuple[float, str]] = []
    for norm, (key, weight) in body_w.items():
        rx = _compile(key)
        if not rx or norm in scored:
            continue
        hits = len(rx.findall(full_text))
        if not hits:
            continue
        scored.add(norm)
        if weight > 0:
            emphasis = min(1.0 + 0.2 * (hits - 1), 1.4)
            body_pos.append((weight * emphasis, norm))
        else:
            penalty += weight

    title_points = _saturate(sum(w for w, _ in positive), _cap(cfg, "title_cap", DEFAULT_TITLE_CAP))
    body_points = _saturate(sum(w for w, _ in body_pos), _cap(cfg, "body_cap", DEFAULT_BODY_CAP))
    penalty_points = max(int(round(penalty)), -_cap(cfg, "penalty_cap", DEFAULT_PENALTY_CAP))

    matched = [n for _, n in sorted(positive, key=lambda x: -x[0])]
    matched += [n for _, n in sorted(body_pos, key=lambda x: -x[0])]
    return title_points + body_points + penalty_points, matched


class KeywordWeightStage(PipelineStage):
    """Applies the profile's ``scoring_weights`` title/body keyword bonuses and penalties."""

    @property
    def name(self) -> str:
        return "keyword_weights"

    def process(self, raw_job: RawJob, job: Job, context: PipelineContext) -> StageResult:
        delta, matched = evaluate_keywords(raw_job.title, raw_job.content)
        tags = []
        if matched or delta:
            sign = "+" if delta >= 0 else ""
            names = ",".join(matched[:4])
            tags.append(f"kw:{names}({sign}{delta})" if names else f"kw:({sign}{delta})")
        return StageResult(should_continue=True, score_delta=delta, tags=tags)
