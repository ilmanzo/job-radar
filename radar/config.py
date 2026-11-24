"""Configuration & YAML data loaders for Job Radar."""

import functools
import glob
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
import yaml

from radar.models import CompanyTarget

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")


class ConfigError(Exception):
    """Required personal configuration is missing."""


def load_dotenv_if_present(dotenv_path: Optional[str] = None):
    """Load key-value pairs from .env into os.environ without overwriting existing environment variables."""
    if dotenv_path is None:
        dotenv_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Automatically load local .env if present
load_dotenv_if_present()


def _env_path(var: str) -> Optional[str]:
    """Resolve a file path from an environment variable.

    Relative paths (e.g. ``data/profile_me.yaml`` in .env) are resolved against
    the current working directory if the file exists there, otherwise against
    the project root, so the configuration works regardless of where the
    radar is launched from (cron, systemd, another directory).
    """
    value = os.environ.get(var)
    if not value:
        return None
    path = os.path.expanduser(value)
    if os.path.isabs(path) or os.path.exists(path):
        return os.path.abspath(path)
    return os.path.join(BASE_DIR, path)


SETTINGS_FILE = (
    _env_path("JOB_RADAR_CONFIG")
    or (os.path.join(DATA_DIR, "settings.yaml") if os.path.exists(os.path.join(DATA_DIR, "settings.yaml")) else None)
    or (os.path.join(BASE_DIR, "config.yaml") if os.path.exists(os.path.join(BASE_DIR, "config.yaml")) else None)
)

PROFILE_FILE = (
    _env_path("JOB_RADAR_PROFILE")
    or (os.path.join(DATA_DIR, "profile.local.yaml") if os.path.exists(os.path.join(DATA_DIR, "profile.local.yaml")) else None)
    or (os.path.join(DATA_DIR, "profile.yaml") if os.path.exists(os.path.join(DATA_DIR, "profile.yaml")) else None)
    or (os.path.join(BASE_DIR, "profile.yaml") if os.path.exists(os.path.join(BASE_DIR, "profile.yaml")) else None)
    or os.path.join(DATA_DIR, "profile.example.yaml")
)

TARGETS_FILE = (
    _env_path("JOB_RADAR_TARGETS")
    or (os.path.join(DATA_DIR, "targets.local.yaml") if os.path.exists(os.path.join(DATA_DIR, "targets.local.yaml")) else None)
    or (os.path.join(DATA_DIR, "targets.yaml") if os.path.exists(os.path.join(DATA_DIR, "targets.yaml")) else None)
    or os.path.join(DATA_DIR, "targets.example.yaml")
)
# `discover add` writes here so the committed example list is never modified.
TARGETS_WRITE_FILE = _env_path("JOB_RADAR_TARGETS") or os.path.join(DATA_DIR, "targets.local.yaml")

TECH_STACK_FILE = (
    _env_path("JOB_RADAR_TECH_STACK")
    or (os.path.join(DATA_DIR, "tech_stack.local.yaml") if os.path.exists(os.path.join(DATA_DIR, "tech_stack.local.yaml")) else None)
    or (os.path.join(DATA_DIR, "tech_stack.yaml") if os.path.exists(os.path.join(DATA_DIR, "tech_stack.yaml")) else None)
    or (os.path.join(BASE_DIR, "tech_stack.yaml") if os.path.exists(os.path.join(BASE_DIR, "tech_stack.yaml")) else None)
    or os.path.join(DATA_DIR, "tech_stack.example.yaml")
)

def _first_existing(env_var: str, *candidates: str) -> Optional[str]:
    """Return env override, else first existing candidate path (personal *.local files first)."""
    return _env_path(env_var) or next((c for c in candidates if os.path.exists(c)), None)


COUNTRIES_FILE = _first_existing(
    "JOB_RADAR_COUNTRIES",
    os.path.join(DATA_DIR, "countries.local.yaml"),
    os.path.join(DATA_DIR, "countries.yaml"),
)

INTEL_DIR = _first_existing(
    "JOB_RADAR_INTEL_DIR",
    os.path.join(DATA_DIR, "intel.local"),
    os.path.join(DATA_DIR, "intel"),
) or os.path.join(DATA_DIR, "intel.local")

LEGACY_INTEL_FILE = os.path.join(BASE_DIR, "company_intel.yaml")

DB_PATH = _env_path("JOB_RADAR_DB") or os.path.join(BASE_DIR, "jobs.db")
FEED_PATH = _env_path("JOB_RADAR_FEED") or os.path.join(BASE_DIR, "feed.xml")


_SETTINGS_CACHE: Dict[str, Any] = {"mtime": None, "data": None}
_PROFILE_CACHE: Dict[str, Any] = {"mtime": None, "data": None}
_TECH_STACK_CACHE: Dict[str, Any] = {"mtime": None, "data": None, "compiled": None, "regex": None}

def load_settings() -> dict:
    """Load optional global settings from config.yaml or data/settings.yaml."""
    if SETTINGS_FILE and os.path.exists(SETTINGS_FILE):
        try:
            mtime = os.path.getmtime(SETTINGS_FILE)
            if _SETTINGS_CACHE["mtime"] == mtime and _SETTINGS_CACHE["data"] is not None:
                return _SETTINGS_CACHE["data"]
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                _SETTINGS_CACHE["mtime"] = mtime
                _SETTINGS_CACHE["data"] = data
                return data
        except Exception:
            return {}
    return {}


_PROFILE_MISSING_WARNED = False


def load_profile() -> dict:
    """Load candidate career profile, domain expertise, and scoring weights."""
    if not PROFILE_FILE or not os.path.exists(PROFILE_FILE):
        global _PROFILE_MISSING_WARNED
        if PROFILE_FILE and not _PROFILE_MISSING_WARNED:
            _PROFILE_MISSING_WARNED = True
            print(
                f"Warning: candidate profile not found at {PROFILE_FILE}.",
                file=sys.stderr,
            )
        return {}
    try:
        mtime = os.path.getmtime(PROFILE_FILE)
        if _PROFILE_CACHE["mtime"] == mtime and _PROFILE_CACHE["data"] is not None:
            return _PROFILE_CACHE["data"]
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            _PROFILE_CACHE["mtime"] = mtime
            _PROFILE_CACHE["data"] = data
            return data
    except Exception:
        return {}


def _normalize_tech_item(item: Any) -> Optional[Tuple[str, str]]:
    """Convert string or dict into (canonical_name, regex_pattern)."""
    if isinstance(item, str):
        name = item.strip().lower()
        if not name:
            return None
        if name == "c":
            return ("c", r"\bc\b")
        if name == "go":
            return ("go", r"\bgo\b")
        if name in ("c++", "cpp"):
            return ("c++", r"\bc\+\+")
        return (name, rf"\b{re.escape(name)}\b")
    elif isinstance(item, dict) and "name" in item:
        name = str(item["name"]).strip().lower()
        if not name:
            return None
        pat = item.get("pattern")
        if pat:
            return (name, pat)
        return _normalize_tech_item(name)
    return None


def load_tech_stack() -> List[Dict[str, str]]:
    """Load tracked technology keywords and patterns from tech_stack.yaml."""
    if not TECH_STACK_FILE or not os.path.exists(TECH_STACK_FILE):
        return []
    try:
        mtime = os.path.getmtime(TECH_STACK_FILE)
        if _TECH_STACK_CACHE["mtime"] == mtime and _TECH_STACK_CACHE["data"] is not None:
            return _TECH_STACK_CACHE["data"]

        with open(TECH_STACK_FILE, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        items: List[Any] = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("tech_stack") or raw.get("technologies") or []

        parsed = []
        for it in items:
            normalized = _normalize_tech_item(it)
            if normalized:
                parsed.append({"name": normalized[0], "pattern": normalized[1]})

        _TECH_STACK_CACHE["mtime"] = mtime
        _TECH_STACK_CACHE["data"] = parsed
        _TECH_STACK_CACHE["compiled"] = None
        _TECH_STACK_CACHE["regex"] = None
        return parsed
    except Exception:
        return []


def get_compiled_tech_stack() -> List[Tuple[str, re.Pattern]]:
    """Return compiled (canonical_name, regex) pairs for each tracked tech."""
    load_tech_stack()
    if _TECH_STACK_CACHE["compiled"] is not None:
        return _TECH_STACK_CACHE["compiled"]

    tech_list = _TECH_STACK_CACHE["data"] or []
    compiled = []
    for item in tech_list:
        try:
            p = re.compile(item["pattern"], re.IGNORECASE)
            compiled.append((item["name"], p))
        except re.error:
            p = re.compile(rf"\b{re.escape(item['name'])}\b", re.IGNORECASE)
            compiled.append((item["name"], p))

    _TECH_STACK_CACHE["compiled"] = compiled
    return compiled


def get_tech_stack_regex() -> re.Pattern:
    """Return single combined regex matching any tracked technology."""
    load_tech_stack()
    if _TECH_STACK_CACHE["regex"] is not None:
        return _TECH_STACK_CACHE["regex"]

    compiled = get_compiled_tech_stack()
    patterns = [p.pattern for _, p in compiled]
    if not patterns:
        combined = re.compile(r"(?!)")
    else:
        combined = re.compile(rf"(?:{'|'.join(patterns)})", re.IGNORECASE)

    _TECH_STACK_CACHE["regex"] = combined
    return combined


def find_tech_matches(text: str) -> List[str]:
    """Find unique canonical tech names matching in text, sorted alphabetically."""
    if not text:
        return []
    compiled = get_compiled_tech_stack()
    matches = set()
    for name, pattern in compiled:
        if pattern.search(text):
            matches.add(name)
    return sorted(list(matches))


def get_candidate_info() -> Dict[str, Any]:
    """Retrieve structured candidate identity and preferences."""
    prof = load_profile()
    cand = prof.get("candidate", {})
    return {
        "name": cand.get("name", ""),
        "headline": cand.get("headline", ""),
        "current_role": cand.get("current_role", ""),
        "experience_years": cand.get("experience_years"),
        "location": os.environ.get("CANDIDATE_LOCATION") or cand.get("location") or "",
        "allowed_locations": cand.get("allowed_locations") or [],
        "contract_preference": cand.get("contract_preference", ""),
        "website": cand.get("website", ""),
        "remote_only": cand.get("remote_only", False),
        "city": cand.get("city", ""),
    }


def get_salary_expectations() -> Dict[str, Optional[int]]:
    """Retrieve salary threshold tiers (EUR equivalent) from the profile; unset tiers are None (not scored)."""
    prof = load_profile()
    comp = prof.get("compensation", {}) or prof.get("salary_expectations", {})
    return {
        tier: int(comp[key]) if comp.get(key) is not None else None
        for tier, key in (("high", "target_high"), ("mid", "target_mid"), ("low", "target_low"))
    }


def get_location_config() -> Dict[str, Any]:
    """Retrieve candidate target country, allowed secondary locations, and remote preferences."""
    cand = get_candidate_info()
    home = (
        os.environ.get("CANDIDATE_COUNTRY")
        or os.environ.get("CANDIDATE_LOCATION")
        or cand.get("location")
        or ""
    ).strip()
    if not home:
        raise ConfigError(
            "Candidate country not configured: set CANDIDATE_COUNTRY in .env or candidate.location "
            "in data/profile.local.yaml (see README 'Personalize')."
        )

    allowed_env = os.environ.get("CANDIDATE_ALLOWED_COUNTRIES")
    if allowed_env:
        allowed = [c.strip() for c in allowed_env.split(",") if c.strip()]
    else:
        raw_allowed = cand.get("allowed_locations") or []
        if isinstance(raw_allowed, list):
            allowed = [c.strip() for c in raw_allowed if c.strip()]
        elif isinstance(raw_allowed, str):
            allowed = [c.strip() for c in raw_allowed.split(",") if c.strip()]
        else:
            allowed = []

    env_remote = os.environ.get("CANDIDATE_REMOTE_ONLY")
    if env_remote is not None:
        remote_only = env_remote.strip().lower() in ("true", "1", "yes")
    else:
        remote_only = bool(cand.get("remote_only", False))

    city = (
        os.environ.get("CANDIDATE_CITY")
        or cand.get("city", "")
    ).strip()

    return {
        "home_country": home,
        "primary_country": home,
        "allowed_countries": allowed,
        "remote_only": remote_only,
        "city": city,
    }


def get_obsidian_vault_path() -> Optional[str]:
    """Resolve Obsidian vault directory from environment or settings; None if not configured."""
    settings = load_settings()
    vault = (
        os.environ.get("OBSIDIAN_VAULT_PATH")
        or os.environ.get("JOB_RADAR_OBSIDIAN_VAULT")
        or settings.get("obsidian", {}).get("vault_path")
    )
    return os.path.expanduser(vault) if vault else None


def get_telegram_config() -> Dict[str, Any]:
    """Resolve Telegram bot credentials and notification thresholds."""
    settings = load_settings()
    tg_settings = settings.get("telegram", {})

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_settings.get("bot_token")
    # Optional JSON file holding {"telegram": {"bot_token": ...}} (shared with another bot).
    legacy_cfg_path = os.path.expanduser(os.environ.get("TELEGRAM_CONFIG_JSON") or tg_settings.get("config_json") or "")
    if not token and legacy_cfg_path and os.path.exists(legacy_cfg_path):
        try:
            import json
            with open(legacy_cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            token = cfg.get("telegram", {}).get("bot_token")
        except Exception:
            pass

    chat_id_val = os.environ.get("TELEGRAM_CHAT_ID") or tg_settings.get("chat_id")
    chat_id = int(chat_id_val) if chat_id_val else None

    min_score_val = os.environ.get("JOB_RADAR_NOTIFY_MIN_SCORE") or tg_settings.get("min_score")
    min_score = int(min_score_val) if min_score_val is not None else None

    # Unset: salary alone never triggers an alert.
    min_sal_val = os.environ.get("JOB_RADAR_NOTIFY_MIN_SALARY") or tg_settings.get("min_salary")
    min_salary = int(min_sal_val) if min_sal_val is not None else None

    return {
        "bot_token": token,
        "chat_id": chat_id,
        "min_score": min_score,
        "min_salary": min_salary,
    }


def load_targets() -> List[CompanyTarget]:
    """Load target companies list."""
    if not os.path.exists(TARGETS_FILE):
        return []
    with open(TARGETS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw_list = data.get("companies", [])
    targets = []
    for c in raw_list:
        targets.append(
            CompanyTarget(
                id=c["id"],
                name=c.get("name", c["id"].capitalize()),
                tier=c.get("tier", "scaleup"),
                category=c.get("category", ""),
                ats=c.get("ats", "greenhouse"),
                board=c.get("board", c["id"]),
                entity_in_home_country=c.get("entity_in_home_country", False),
                eor_supported=c.get("eor_supported", True),
                allowed_countries=c.get("allowed_countries") or [],
                notes=c.get("notes", ""),
                site=c.get("site", "jobs"),
                sub_domain=c.get("sub_domain", "wd5"),
                search_text=c.get("search_text", ""),
                extra=c,
            )
        )
    return targets


@functools.lru_cache(maxsize=1)
def load_countries() -> Dict[str, dict]:
    """Load country table {name: {aliases: [...], cities: [...]}} from countries.yaml."""
    if not COUNTRIES_FILE or not os.path.exists(COUNTRIES_FILE):
        return {}
    with open(COUNTRIES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k.lower(): v or {} for k, v in (data.get("countries") or {}).items()}


def load_all_intel() -> Dict[str, dict]:
    """Load all company intel dossiers from INTEL_DIR/*.yaml."""
    intel_map = {}
    if os.path.isdir(INTEL_DIR):
        for path in glob.glob(os.path.join(INTEL_DIR, "*.yaml")):
            cid = os.path.splitext(os.path.basename(path))[0]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    intel_map[cid] = yaml.safe_load(f) or {}
            except Exception:
                pass

    if not intel_map and os.path.exists(LEGACY_INTEL_FILE):
        with open(LEGACY_INTEL_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            intel_map = data.get("companies", {})

    return intel_map


def load_company_intel(company_id: str) -> Optional[dict]:
    """Load dossier for a specific company."""
    specific_path = os.path.join(INTEL_DIR, f"{company_id.lower()}.yaml")
    if os.path.exists(specific_path):
        with open(specific_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    all_intel = load_all_intel()
    return all_intel.get(company_id.lower())
