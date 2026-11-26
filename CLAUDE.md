# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Job Radar: scrapes ATS job boards for target companies, scores roles through a filter/scoring pipeline against a candidate profile, exports to sinks (SQLite, RSS, Obsidian, Telegram, desktop). User docs: `README.md`. Plugin how-tos: `ARCHITECTURE.md`.

## Commands

```bash
uv sync                                   # deps (runtime: pyyaml only; dev: pytest)
uv run pytest                             # all tests (pythonpath=".", testpaths=tests)
uv run pytest tests/test_scrapers.py -k pagopa   # single file / test
python3 radar.py sync --company cloudflare --sinks db   # sync one target, DB only (hits network)
python3 radar.py top --by-profile         # inspect results in jobs.db
```

`run_sync.sh` is the systemd entrypoint (`sync --notify --min-score=$JOB_RADAR_NOTIFY_MIN_SCORE`). No linter/formatter configured. `tests/conftest.py` pins every data path to the committed examples (and `CANDIDATE_COUNTRY=Germany`), so tests never read a developer's `*.local` files.

## Architecture

Flow (`radar/cli.py:cmd_sync`): `load_targets()` → per target `get_source(target.ats).fetch(target)` → `list[RawJob]` → `PipelineEngine.process()` per job → jobs with `score >= --min-score` → each sink's `export(jobs, context)`.

- **Plugin registries** (`radar/sources`, `radar/sinks`, `radar/scrapers` `__init__.py`): `pkgutil` scans the package, registers every subclass of the base class, keyed by `ats_name` / `name` / `scraper_id`. Modules named `base` are skipped. A module that fails to import only prints a warning and is skipped. Check the output if a new plugin "doesn't exist".
- **Scrapers vs sources**: `radar/scrapers/` holds HTML scrapers (`BaseHtmlScraper`) for non-ATS career sites. `discover_sources()` also registers each scraper as a source under its `scraper_id` (unless that name is already taken by an ATS source), so `ats: <scraper_id>` works in `targets.yaml`, as does `ats: scraper` + `board: <scraper_id>`. One-off HTML sources (Amazon, Dynatrace, Sidero, Proxmox) live in `radar/sources/custom.py`. Feed-based ATS sources (teamtailor, rss, successfactors, eightfold, oracle_orc, jibe, personio, talentadore) share helpers in `radar/sources/_feed.py`.
- **Pipeline** (`radar/pipeline/engine.py`): fixed ordered stage list (title → location → contract → role → salary → profile → freshness). Each stage returns `StageResult(should_continue, score_delta, tags)`: `should_continue=False` drops the job; deltas add up; tags are strings like `loc:foreign_restriction` that sinks read later (e.g. Telegram drops foreign-restricted jobs). New stages must be added to that list by hand; they are not auto-discovered.
- **DB lifecycle** (`radar/db.py`): sync calls `deactivate_company_jobs` for each target before processing, so any job that is dropped or under `--min-score` stays inactive. Exception: when `source.fetch` raises (`radar.http.FetchError` from the `http_get_*` helpers, or any error), sync prints it and skips that company, so stored jobs stay active; `[]` means a real zero-opening board and deactivates. HTML-parsing sources raise `FetchError` when they parse zero postings (layout change). `first_seen` is carried over from existing rows. `notified_at` dedupes Telegram alerts. Schema migrations are inline `ALTER TABLE` calls in `get_db()`.
- **Config** (`radar/config.py`): importing it loads `.env` into `os.environ` without overwriting existing vars. Data files resolve as env var → `data/<name>.local.yaml` → committed example (`JOB_RADAR_PROFILE`, `JOB_RADAR_TARGETS`, `JOB_RADAR_TECH_STACK`, `JOB_RADAR_COUNTRIES`, `JOB_RADAR_INTEL_DIR` → `data/intel.local/`, `JOB_RADAR_CONFIG`, `JOB_RADAR_DB`, `JOB_RADAR_FEED`). Paths are fixed at import time. Profile, settings and tech stack are cached by mtime; `load_countries()` uses `lru_cache`. Location env vars (`CANDIDATE_COUNTRY`, `CANDIDATE_ALLOWED_COUNTRIES`, …) override the profile.
- **No personal defaults in code**: missing country raises `ConfigError` (caught in `main()`); unset salary tiers or notification thresholds are skipped, not defaulted; unset Obsidian vault skips that sink; no skill_matrix means 0% match. Country aliases and cities live in `data/countries.yaml`; per-company extra countries come from `allowed_countries` in targets.
- **Data**: targets (companies + ATS board ids), profile (candidate, salary tiers, `skill_matrix`, `scoring_weights`, `fallback_pitch`), tech_stack (tech regexes), countries, intel dossiers `<company_id>.yaml` (used by `radar.py company` and Obsidian).

## Conventions

- HTTP uses stdlib `urllib.request` only, through `radar/http.py` (`http_get_json`/`http_get_text`, which raise `FetchError`). Don't add `requests` or other deps for a few lines.
- Tests are `unittest`-style, run through pytest, with network calls mocked via `unittest.mock.patch`. No test may hit the network.
- Root scripts `matcher.py`, `telegram_notify.py`, `obsidian_sync.py`, `discover.py`, `run_radar_cron.sh` are backward-compat wrappers. Put new logic in `radar/`.
- The public repo must stay generic and anonymous. Personal data (CV, country, salary, company lists, dossiers, paths, tokens) goes only in git-ignored `data/*.local.yaml`, `data/intel.local/`, or `.env`, never in code defaults, examples, tests or docs. Generic improvements (e.g. a new country in `countries.yaml`) go in the committed files.
