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
│  workable · deel · teamtailor · rss · successfactors · eightfold ·       │
│  oracle_orc · jibe · personio · talentadore ·                            │
│  custom.py (amazon, dynatrace, sidero, proxmox) ·                        │
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
│  3. ContractStage       drop B2B · tier bonus · home entity +35 / EOR +25│
│  4. RoleSeniorityStage  systems/SRE relevance, seniority, tech stack     │
│  5. SalaryStage         EUR normalization · profile tiers +35/+25/+15/-10│
│  6. ProfileMatchStage   profile skill_matrix → match % + pitch bullets   │
│  7. FreshnessStage      <7d +20 … >75d -30                               │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ Job (score >= --min-score; Telegram: >= --notify-min-score)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Sink plugins (radar/sinks, keyed by `name`, chosen with --sinks/--notify)│
│  db        → jobs.db (SQLite, notified_at dedupe, embedding_status)      │
│  rss       → feed.xml                                                    │
│  obsidian  → offers, company dossiers, Dataview dashboard                │
│  telegram  → alerts for new matches over score/salary thresholds         │
│  desktop   → notify-send                                                 │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ jobs.db (embedding_status = 'pending')
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Offline Local Semantic Engine (radar/semantic, run via `radar embed`)    │
│  1. Profile Pillars   deep_domain_expertise (profile.local.yaml) →       │
│                       pre-cached 384-dim centroids (profile_embeddings)  │
│  2. Local Vectorizer  FastText-style subword n-grams (n=4..5) + bigrams  │
│                       sublinear TF, signed feature hashing (pure Python) │
│  3. Cosine Matching   Max similarity vs pillars → +5..+30 bonus pts      │
│  4. In-Place Update   jobs.db: score, semantic_score, semantic:<tag>     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout

```
job-radar/
├── data/
│   ├── profile.example.yaml      # Template: candidate, salary tiers, skill_matrix, domain pillars
│   ├── targets.example.yaml      # Template: tracked companies & ATS boards
│   ├── tech_stack.example.yaml   # Template: tracked technology regexes
│   ├── countries.yaml            # Country aliases & cities used by LocationStage
│   ├── intel.example.yaml        # Template: company dossier
│   └── *.local.yaml, intel.local/  # Your personal data (git-ignored)
├── radar/
│   ├── config.py                 # Path resolution (env → *.local → example) & YAML loaders
│   ├── models.py                 # RawJob, Job, SalaryInfo, ProfileMatch, CompanyTarget
│   ├── db.py                     # SQLite schema, inline migrations, vector BLOB serialization
│   ├── discovery.py              # Peer catalog & CNCF landscape explorer
│   ├── cli.py                    # CLI commands (sync, top, review, company, stats, embed)
│   ├── sources/                  # ATS source plugins (auto-discovered)
│   │   ├── base.py               # BaseSource interface
│   │   ├── greenhouse.py, lever.py, ashby.py (with salary tiers), workday.py,
│   │   │   smartrecruiters.py, recruitee.py, workable.py, deel.py
│   │   ├── teamtailor.py, rss.py, successfactors.py, eightfold.py, oracle_orc.py,
│   │   │   jibe.py, personio.py, talentadore.py   # feed-based sources (_feed.py helpers)
│   │   ├── custom.py             # Amazon, Dynatrace, Sidero, Proxmox
│   │   └── scraper.py            # Bridge `ats: scraper` → HTML scraper plugins
│   ├── scrapers/                 # HTML scraper plugins (auto-discovered)
│   │   ├── base.py               # BaseHtmlScraper & parsing helpers
│   │   └── pagopa.py, flyio.py
│   ├── semantic/                 # 100% Local Offline Semantic Vector Engine
│   │   ├── base.py               # BaseEmbeddingProvider & pure Python cosine_similarity
│   │   ├── local.py              # LocalHashedEmbeddingProvider (subword FastText-style hashing)
│   │   └── matcher.py            # Pillar centroids, similarity thresholds, bonus scoring
│   ├── pipeline/                 # Stages (fixed order in engine.py)
│   │   ├── base.py, engine.py
│   │   └── title.py, location.py, contract.py, role.py, salary.py, profile.py, freshness.py
│   └── sinks/                    # Sink plugins (auto-discovered)
│       └── base.py, db_sink.py, rss_sink.py, obsidian_sink.py, telegram_sink.py, desktop_sink.py
├── radar.py                      # Entrypoint
├── run_sync.sh                   # systemd runner (sync --notify + embed)
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

---

## 4. Local Semantic Vector Engine & Domain Pillars

Job Radar implements a **hybrid matching architecture**:
- **Deterministic Regex Stages:** Enforce hard negative gates (dropping frontend/management roles), geographic eligibility (home country / EOR validation), and exact CV skill matches.
- **100% Offline Semantic Vector Engine (`radar/semantic`):** Evaluates dense conceptual proximity between job openings and the candidate's core technical specializations without relying on external APIs or third-party neural libraries.

### A. Subword Feature-Hashed Embedding Model
To guarantee zero-ops portability and maximum compatibility across all environments without heavy external dependencies, Job Radar avoids heavy runtime frameworks like PyTorch or ONNX.

`LocalHashedEmbeddingProvider` (`radar/semantic/local.py`) runs in pure Python:
1. **Unigram Extraction with Stopword Suppression:** Eliminates common English noise and structural titles (`lead`, `manager`, `head`).
2. **Sublinear Term Frequency:** Weighted as $1 + \ln(\text{TF})$.
3. **FastText-Style Character $n$-grams:** Computes 4-grams and 5-grams for words with length $\ge 4$, capturing morphological variants (e.g. `microvm` $\leftrightarrow$ `microvms` $\leftrightarrow$ `firecracker-microvm`).
4. **Word Bigrams:** Captures compound technical concepts (e.g. `socket_activation`, `fault_injection`).
5. **Signed Feature Hashing Projection:** Projects tokens into a 384-dimensional vector space using signed MD5 hashing ($E[h] = 0$).
6. **$L_2$ Unit Normalization:** Produces vectors where cosine similarity equals the dot product.

### B. Domain Pillars as Reference Centroids
Defined in `data/profile.local.yaml` under `deep_domain_expertise:`, each pillar provides dense technical context:
- `category`: Pillar identifier (e.g., `Linux Kernel Security, Sandboxing & Capabilities`).
- `description`: 2–3 sentences detailing actual hands-on engineering, subsystems, and architectures.
- `keywords`: Concrete tools, syscalls, and interfaces.

Pillar reference vectors are stored in SQLite (`profile_embeddings`). For each job, cosine similarity is computed against all pillars:
$$\text{similarity} = \max_{p \in \text{pillars}} \vec{v}_{\text{job}} \cdot \vec{v}_p$$

Jobs matching above the similarity threshold receive $+5$ to $+30$ bonus points and are tagged with `semantic:<pillar_slug>`.

### C. Deferred Asynchronous Ingestion
To ensure `radar sync` remains sub-second fast and non-blocking:
1. Scrapers store ingested jobs in `jobs.db` with `embedding_status = 'pending'`.
2. `radar embed` runs as a deferred task (chained in `run_sync.sh` or executed via cron/timer), batch-processing pending jobs in memory without slowing down sync operations or notification dispatches.
3. Vectors are packed into binary IEEE-754 `float32` BLOBs using Python's standard `struct` library, maintaining zero external database overhead.

Pass `--sinks db,rss,obsidian,webhook` to invoke it.
