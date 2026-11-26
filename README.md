# Job Radar

Automated job discovery, ATS scraping, and semantic scoring engine targeting Linux, Kernel, Systems, Observability, and Cloud Platform engineering roles.

**Key Highlights:**
- **ATS API Ingestion & Extensible Scrapers**: Queries public REST / GraphQL ATS endpoints directly (Greenhouse, Lever, Ashby, Workday, Deel, Recruitee, Workable, SmartRecruiters, Teamtailor, SuccessFactors, Eightfold, Oracle Recruiting Cloud, iCIMS Jibe, Personio, Talentadore, generic RSS) and supports modular HTML scrapers for non-ATS portals (e.g. PagoPA, Fly.io).
- **Multi-Stage Scoring Pipeline**: Filters non-engineering roles, evaluates geographic eligibility & legal entity status, normalizes compensation, and scores candidate skill alignment.
- **100% Local Semantic Vector Search**: Offline feature-hashed subword vectorizer (`local-subword-hash-384`) in pure Python. Zero external API calls, zero C extensions, and lightweight zero-ops design. Evaluates semantic similarity against candidate domain pillars and awards $+5$ to $+30$ bonus points for non-exact technical synonyms.
- **Deferred Asynchronous Embeddings**: High-speed ATS ingestion decoupled from embedding math; `radar embed` processes un-embedded jobs asynchronously or via cron chaining.
- **Custom Application Pitch Generator**: Dynamically crafts tailored CV & interview pitch bullets based on candidate profile.
- **Multiple Output Sinks**: SQLite database (with automatic schema migrations and binary vector BLOBs), RSS 2.0 feed, Obsidian markdown vault (with Dataview dashboard), Telegram bot notifications, and desktop alerts.

---

## 🚀 Quickstart

```bash
git clone https://github.com/ilmanzo/job-radar.git
cd job-radar
uv sync            # or: pip install -r requirements.txt
uv run pytest      # tests run against the committed example data only
```

The repository ships **generic code and example data only**. Your personal setup (country, salary, skills, companies, research notes) lives in git-ignored files, so you can pull updates (or publish your fork) without leaking it.

---

## 🧑‍💻 Personalize

### How config is resolved

Each data file is looked up in this order: **env var → `data/<name>.local.yaml` (git-ignored, yours) → committed example**. Nothing personal has a built-in default in code. If your country isn't configured, `sync` stops with an error.

| What | Your file (git-ignored) | Env override | Committed template |
|------|------------------------|--------------|--------------------|
| Profile: country, salary tiers, skills, pitches | `data/profile.local.yaml` | `JOB_RADAR_PROFILE` | `data/profile.example.yaml` |
| Companies to track | `data/targets.local.yaml` | `JOB_RADAR_TARGETS` | `data/targets.example.yaml` |
| Tech keywords | `data/tech_stack.local.yaml` | `JOB_RADAR_TECH_STACK` | `data/tech_stack.example.yaml` |
| Country/city table | `data/countries.local.yaml` | `JOB_RADAR_COUNTRIES` | `data/countries.yaml` |
| Company dossiers | `data/intel.local/<id>.yaml` | `JOB_RADAR_INTEL_DIR` | `data/intel.example.yaml` |
| Secrets, thresholds, vault | `.env` | (env itself) | `.env.example` |
| Database, feed | `jobs.db`, `feed.xml` | `JOB_RADAR_DB`, `JOB_RADAR_FEED` | — |

Env vars (`CANDIDATE_COUNTRY`, `CANDIDATE_ALLOWED_COUNTRIES`, `CANDIDATE_REMOTE_ONLY`, `CANDIDATE_CITY`) override the profile. See `.env.example`.

### Steps

```bash
cp .env.example .env                                   # Telegram, thresholds, Obsidian vault
cp data/profile.example.yaml data/profile.local.yaml   # set candidate.location (required)
# build data/targets.local.yaml from your CV (below), or start from the example:
cp data/targets.example.yaml data/targets.local.yaml
python3 radar.py sync --company <one_id> --sinks db    # smoke test
```

If your country isn't in `data/countries.yaml`, add it there (aliases + cities). That's a generic improvement, so send it upstream. Put only personal tweaks (e.g. your small home town) in `data/countries.local.yaml`.

### Generate your company list and skill matrix from your CV with an LLM

Feed your CV (plus links to your blog or projects if you like) to an LLM with this prompt, then review the output by hand. LLMs invent ATS board ids, so check every company with `python3 radar.py sync --company <id> --sinks db`: a wrong `ats`/`board` shows up as `fetch failed: ... HTTP 404` (or `Found: 0`).

```text
You are helping me configure Job Radar, a job-board scraper. Attached is my CV.
I live in <COUNTRY> and can also work in <OTHER COUNTRIES>. I want <ROLE TYPES>, <remote/hybrid>.

1. Produce data/targets.local.yaml: 30-60 companies that hire for my profile and can employ
   people in my country (local entity or Employer of Record). Use exactly this schema per entry:
     - id: lowercase-slug
       name: "Company"
       tier: big_tech | enterprise_infra | scaleup
       category: "short domain label"
       ats: greenhouse | lever | ashby | workday | smartrecruiters | recruitee | workable | deel |
            teamtailor | rss | successfactors | eightfold | oracle_orc | jibe | personio | talentadore
       board: <ATS board id, e.g. the slug in boards.greenhouse.io/<board> or jobs.lever.co/<board>>
       # workday only: site: <site>, sub_domain: wd1..wd12, search_text: <optional filter>
       entity_in_home_country: true|false   # legal entity in MY country
       eor_supported: true|false
       allowed_countries: []                 # optional extra countries for this company only
       notes: "why this company fits me, in one line"
   Only use companies whose careers page runs on one of those ATSs; say "unsure" in notes
   when you are not certain of the board id.

2. Produce the `skill_matrix`, `scoring_weights` and `deep_domain_expertise` sections of
   data/profile.local.yaml, following the format of data/profile.example.yaml (pasted below).
   skill_matrix entries: regex pattern (lowercase, \\b word boundaries), skill name, weight
   (10-30, higher = rarer/more valuable skill of mine), and a one-sentence pitch citing a
   concrete achievement from my CV.

<paste data/profile.example.yaml here>
```

### Domain Pillars & Semantic Vector Matching

Job Radar combines deterministic regex filters with a **100% local semantic vector engine** (`local-subword-hash-384`).

In `data/profile.local.yaml`, define your **Domain Pillars** under `deep_domain_expertise:`. Each pillar represents a signature technical specialization:
```yaml
deep_domain_expertise:
  - category: "Storage Systems & Block Layer Reliability"
    description: "Low-level Linux storage verification, crash-safety testing, device-mapper dm-flakey fault simulation, and BTRFS multi-device redundancy under power failure."
    keywords: ["storage", "dm-flakey", "btrfs", "block device", "io_uring", "nvme", "page cache", "fsync"]
```

**How it works:**
1. Reference embeddings are computed for each pillar and cached in SQLite (`profile_embeddings`).
2. When jobs are ingested, `radar embed` projects job titles and content excerpts into the 384-dimensional vector space using FastText-style character $n$-grams ($n \in \{4,5\}$) and word bigrams with sublinear term-frequency weighting.
3. Cosine similarity is computed against each pillar. Jobs with similarity above threshold receive $+5$ to $+30$ bonus points and are tagged with `semantic:<pillar_slug>` (e.g. `semantic:storage_systems_block_layer`).
4. Catches non-exact technical synonyms (e.g. "fault tolerance", "packet pacing", "chaos testing", "Linux internals") without requiring exhaustive regex dictionaries.

### Keep your setup outside the checkout (multiple machines, public fork)

Put your personal files in a **separate private git repo** (e.g. `~/job-radar-private/`) and point the env vars from `.env` at it (`JOB_RADAR_PROFILE`, `JOB_RADAR_TARGETS`, `JOB_RADAR_INTEL_DIR`, ...; see `.env.example`). The public checkout then stays a clean clone: `git pull` never touches your data, and your setup is versioned and synced on its own.

---

## 💻 CLI Usage

### Sync & Run Pipeline
Scrape all target companies, compute scores, and export to default sinks (db, rss, obsidian):
```bash
python3 radar.py sync
```

Sync with Telegram and Desktop alerts enabled:
```bash
python3 radar.py sync --notify
```

Sync only a single target company:
```bash
python3 radar.py sync --company cloudflare
```

### Discover Companies
Browse the built-in peer catalog and the CNCF landscape; `add` appends to `data/targets.local.yaml` (or `$JOB_RADAR_TARGETS`):
```bash
python3 radar.py discover list
python3 radar.py discover cncf "runtime"
python3 radar.py discover add sysdig
```
Feed-based ATS types and the target fields they need:

| `ats` | Fields |
|---|---|
| `teamtailor` | `board` (the `<board>.teamtailor.com` subdomain) or `url` (the `/jobs.rss` feed on a custom domain) |
| `rss` | `url` (any RSS 2.0 job feed), optional `location` used when items carry none |
| `successfactors` | `url` (career site root that serves `/search/`), optional `search_text` |
| `eightfold` | `url` (career site host), `board` (tenant domain), `search_text` (location), optional `careers_url` |
| `oracle_orc` | `url` (REST host), `board` (site number, e.g. `CX_1`), `site_url` (candidate site), optional `search_text` |
| `jibe` | `url` (career site host), optional `search_text` (location) |
| `personio` | `board` (the `<board>.jobs.personio.de` subdomain) |
| `talentadore` | `board` (feed key from the career page widget) |

Non-ATS career sites need an HTML scraper plugin: see [ARCHITECTURE.md](ARCHITECTURE.md#adding-a-custom-html-scraper-plugin-non-ats-sites).

### Explore Matched Roles
View roles sorted by **Profile Match %**:
```bash
python3 radar.py top --by-profile
python3 radar.py top --by-profile --min-match=75
```

View highest-paying positions:
```bash
python3 radar.py top --by-salary
python3 radar.py top --by-salary --min-salary=120000
```

Interactive review with tailored CV pitch bullets:
```bash
python3 radar.py review --limit=10
```

Inspect company intelligence dossier:
```bash
python3 radar.py company cloudflare
```

Update job tracking status (`new`, `reviewing`, `applied`, `interviewing`, `offer`, `rejected`, `archived`):
```bash
python3 radar.py status <job_id> applied
```

### Local Semantic Embeddings
Process pending un-embedded jobs and compute similarity scores against domain pillars:
```bash
python3 radar.py embed
python3 radar.py embed --batch-size=100
```

Force recomputing profile reference vectors after updating domain pillars:
```bash
python3 radar.py embed --reindex-profile
```

View database & scoring statistics:
```bash
python3 radar.py stats
```

---

## 📡 Sinks & Outputs

### 1. SQLite Database (`jobs.db`)
Central store for all tracked roles, historical states, notification timestamps, and vector embeddings:
- **`jobs` table**: Role metadata, location eligibility flags, salary data, matched skills, `embedding_status`, and `semantic_score`.
- **`job_embeddings` & `profile_embeddings` tables**: 384-dimensional binary IEEE-754 `float32` BLOBs.
- **In-Place Schema Migration**: Automatic and non-destructive. Calling any `radar` command triggers `get_db()` which executes `ALTER TABLE` and `CREATE TABLE IF NOT EXISTS`, preserving 100% of existing historical data.

### 2. RSS 2.0 Feed (`feed.xml`)
Every `sync` generates a standard RSS feed at `feed.xml`. Subscribe using any feed reader (**newsboat**, Thunderbird, Feedly, NetNewsWire).

### 3. Obsidian Vault
When `OBSIDIAN_VAULT_PATH` is set (otherwise the sink is skipped), exports structured notes into your vault:
- **`jobs/offers/`**: One markdown file per role with YAML frontmatter, compensation breakdown, match percentage, and tailored pitch points. User edits in `## My Notes` or status changes are **strictly preserved** across runs.
- **`jobs/companies/`**: Dossiers with Glassdoor ratings, remote policy, EMEA compensation benchmarks, and interview pipeline stages.
- **`Job Radar Dashboard.md`**: Master dashboard with a Dataview pipeline table and static fallback tables.

### 4. Telegram Alerts
Dispatches HTML-formatted push alerts with clickable application links whenever a new role exceeds `JOB_RADAR_NOTIFY_MIN_SCORE` (or `--notify-min-score`) or `JOB_RADAR_NOTIFY_MIN_SALARY`. `--min-score` only controls what is stored.

---

## ⏰ Automated Scheduling (systemd User Timer)

To run Job Radar automatically in the background on Linux:

1. Copy the unit files to your systemd user directory:
   ```bash
   mkdir -p ~/.config/systemd/user/
   cp systemd/job-radar.timer ~/.config/systemd/user/
   cp systemd/job-radar.service.example ~/.config/systemd/user/job-radar.service
   ```

2. Adjust `WorkingDirectory` and `ExecStart` in `~/.config/systemd/user/job-radar.service` to match your checkout path.

3. Enable and start the timer:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now job-radar.timer
   ```

4. Check timer schedule and logs:
   ```bash
   systemctl --user list-timers job-radar.timer
   journalctl --user -u job-radar.service -n 50
   ```

---

## 🧩 Architecture

Sources → pipeline stages → sinks, all plugin-based. Diagram, layout and how to add sources, scrapers, stages and sinks: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 📄 License

MIT
