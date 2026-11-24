# Job Radar: Modular Architecture & Plugin System

Job Radar is an automated career intelligence and scoring engine. Scoring is driven entirely by your personal profile and target list (see README "Personalize").

---

## 1. Architectural Pipeline

```
 personal config (git-ignored *.local.yaml, .env)  ─┐   committed fallbacks: *.example.yaml,
   profile · targets · tech_stack · countries · intel│   countries.yaml (see README "Personalize")
                                                    ▼
                                         radar/config.py loaders
                                                    │ list[CompanyTarget]
                                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Source plugins (radar/sources, keyed by `ats`)                           │
│  greenhouse · lever · ashby · workday · smartrecruiters · recruitee ·    │
│  workable · deel · custom.py (amazon, dynatrace, sidero, proxmox) ·      │
│  scraper ──► HTML scraper plugins (radar/scrapers, e.g. pagopa)          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ list[RawJob]   (empty result ⇒ stored jobs kept active)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ PipelineEngine (radar/pipeline/engine.py), stages in order:              │
│  1. TitleFilterStage    drop non-engineering / excluded roles            │
│  2. LocationStage       home country +25 · allowed country +15 ·         │
│                         EMEA/global remote +10 · foreign single-country  │
│                         lock -40 · non-EU / wrong-city drop              │
│                         (countries.yaml + profile + target overrides)    │
│  3. ContractStage       B2B drop/accept policy · tier bonus · entity/EOR │
│  4. RoleSeniorityStage  systems/SRE relevance, seniority, tech stack     │
│  5. SalaryStage         EUR normalization · profile tiers +35/+25/+15/-10│
│  6. ProfileMatchStage   profile skill_matrix → match % + pitch bullets   │
│  7. FreshnessStage      <7d +20 … >75d -30                               │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ Job (score >= --min-score)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Sink plugins (radar/sinks, keyed by `name`, chosen with --sinks/--notify)│
│  db        → jobs.db (SQLite, notified_at dedupe)                        │
│  rss       → feed.xml                                                    │
│  obsidian  → offers, company dossiers, Dataview dashboard                │
│  telegram  → alerts for new matches over score/salary thresholds         │
│  desktop   → notify-send                                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout

```
job-radar/
├── data/
│   ├── profile.example.yaml      # Template: candidate, salary, contract, work_mode, skills, weights
│   ├── targets.example.yaml      # Template: tracked companies & ATS boards
│   ├── tech_stack.example.yaml   # Template: tracked technology regexes
│   ├── countries.yaml            # Country aliases & cities used by LocationStage
│   ├── intel.example.yaml        # Template: company dossier
│   └── *.local.yaml, intel.local/  # Your personal data (git-ignored)
├── radar/
│   ├── config.py                 # Path resolution (env → *.local → example) & YAML loaders
│   ├── models.py                 # RawJob, Job, SalaryInfo, ProfileMatch, CompanyTarget
│   ├── db.py                     # SQLite schema, inline migrations, queries
│   ├── discovery.py              # Peer catalog & CNCF landscape explorer
│   ├── cli.py                    # CLI commands
│   ├── sources/                  # ATS source plugins (auto-discovered)
│   │   ├── base.py               # BaseSource interface
│   │   ├── greenhouse.py, lever.py, ashby.py, workday.py, smartrecruiters.py,
│   │   │   recruitee.py, workable.py, deel.py
│   │   ├── custom.py             # Amazon, Dynatrace, Sidero, Proxmox
│   │   └── scraper.py            # Bridge `ats: scraper` → HTML scraper plugins
│   ├── scrapers/                 # HTML scraper plugins (auto-discovered)
│   │   ├── base.py               # BaseHtmlScraper & parsing helpers
│   │   └── pagopa.py
│   ├── pipeline/                 # Stages (fixed order in engine.py)
│   │   ├── base.py, engine.py
│   │   └── title.py, location.py, contract.py, role.py, salary.py, profile.py,
│   │       keywords.py, workmode.py, freshness.py
│   └── sinks/                    # Sink plugins (auto-discovered)
│       └── base.py, db_sink.py, rss_sink.py, obsidian_sink.py, telegram_sink.py, desktop_sink.py
├── radar.py                      # Entrypoint
├── run_sync.sh                   # systemd runner (sync --notify)
├── systemd/                      # Unit/timer examples
└── matcher.py, telegram_notify.py, obsidian_sync.py, discover.py, run_radar_cron.sh
                                  # Backward-compat wrappers
```

---

## 3. Extending the System

### Adding a new ATS Source Plugin
Create `radar/sources/<name>.py`:
```python
from radar.models import CompanyTarget, RawJob
from radar.sources.base import BaseSource

class MyAtsSource(BaseSource):
    ats_name = "myats"

    def fetch(self, target: CompanyTarget) -> list[RawJob]:
        # fetch logic
        return [...]
```
The dynamic loader automatically registers it upon startup.

### Adding a Custom HTML Scraper Plugin (Non-ATS Sites)
For companies that do not use a standard supported ATS (e.g., custom career portals, regional platforms like InRecruiting), create a dedicated scraper in `radar/scrapers/<name>.py` inheriting from `BaseHtmlScraper`:

```python
from radar.models import CompanyTarget, RawJob
from radar.scrapers.base import BaseHtmlScraper

class MyCompanyScraper(BaseHtmlScraper):
    scraper_id = "mycompany"  # Unique identifier
    name = "MyCompany Careers"
    default_url = "https://careers.mycompany.com/openings"

    def scrape(self, target: CompanyTarget) -> list[RawJob]:
        url = target.extra.get("url") or self.default_url
        html_doc = self.fetch_html(url)

        # Built-in helpers:
        # - self.clean_text(raw_html) strips scripts/tags and unescapes entities
        # - self.extract_section(content, "start_marker", "end_marker")
        
        jobs = []
        # parse jobs from html_doc ...
        jobs.append(
            RawJob(
                id=f"mycompany_{job_slug}",
                company_id=target.id,
                title=title,
                location="Remote (EMEA)",
                url=job_url,
                content=description,
                posted_date="2026-11-20",
            )
        )
        return jobs
```

The scraper is automatically discovered by `radar.scrapers` upon startup. You can reference it in your targets file (`data/targets.local.yaml`) using either:

```yaml
  - id: mycompany
    name: "MyCompany"
    ats: scraper          # Uses generic HtmlScraperSource
    board: mycompany      # Matches scraper_id
```
or directly as the ATS name:
```yaml
  - id: mycompany
    name: "MyCompany"
    ats: mycompany        # Auto-bridged into sources registry
    board: mycompany
```

### Adding a new Pipeline Stage
Create `radar/pipeline/<stage>.py` implementing `PipelineStage` and append it to `PipelineEngine.stages` in `radar/pipeline/engine.py`.

### Adding a new Output Sink
Create `radar/sinks/<sink>.py`:
```python
from radar.models import Job
from radar.sinks.base import BaseSink

class WebhookSink(BaseSink):
    name = "webhook"

    def export(self, jobs: list[Job], context: dict):
        # post to webhook
        pass
```
Pass `--sinks db,rss,obsidian,webhook` to invoke it.
