# TechPulse AI Digest Bot

> **Autonomous Multi-Source Technical Intelligence Agent**  
> Ingests trending open-source projects, research preprints, and developer discussions across **6 high-signal tech sources**, filters out marketing noise using Groq's high-speed LLM inference, enforces a 30-day SQLite sliding deduplication window, and delivers executive-ready Markdown digests.

[![Daily Tech Digest](https://img.shields.io/badge/schedule-daily%208AM%20UTC-blue?style=flat-square)](.github/workflows/digest.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python)](https://python.org)
[![Tests Passing](https://img.shields.io/badge/pytest-36%20core%20tests-brightgreen?style=flat-square)](tests/)
[![Playwright E2E](https://img.shields.io/badge/playwright-e2e%20verified-brightgreen?style=flat-square)](tests/test_ui_playwright.py)
[![Cost](https://img.shields.io/badge/cost-%240%2Fmonth-green?style=flat-square)](https://console.groq.com)

---

## Web Observatory & Intelligence Cockpit

TechPulse includes a local observatory web UI inspired by modern engineering cockpits (Linear, Raycast, Vercel design aesthetic):

- **Zero-Scroll Cockpit Flight Mode**: Viewport-contained master-detail layout with keyboard flight controls (`↑`/`↓` or `J`/`K` navigation, `↵` to launch source).
- **Responsive Auto-Fill Bento Cards**: High-density 3-column card grid with glowing category accents and executive takeaways.
- **High-Signal Filtering & Noise Audit**: Keeps rejected noise quarantined in an audit tab while presenting only high-conviction signals by default.
- **Historical Date Switcher**: Browse historical digest editions directly through an integrated dropdown.
- **Markdown Export**: Direct one-click download of `TechPulse-Digest-YYYY-MM-DD.md`.
- **On-Demand Live Harvesting**: Trigger a real-time multi-source crawl and Groq curation cycle with live progress toasts.

Launch the cockpit:
```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to `http://127.0.0.1:8000`.

---

## Testing & Quality Assurance

TechPulse maintains strict test coverage across unit collectors, database deduplication, and browser end-to-end automation:

```bash
# Run unit & integration tests
pytest tests/test_models.py tests/test_database.py tests/test_collectors.py tests/test_pipeline.py -v

# Run Playwright visual end-to-end tests (Chromium headless)
pytest tests/test_ui_playwright.py -v

# Run entire test suite (core tests; start the API first for Playwright)
pytest tests/ -v
```

### Ranking evaluation

Curated items receive a deterministic, source-aware `v1` priority score based on
profile relevance, impact, freshness, novelty, and source-normalized popularity.
The dependency-free metrics in `src/evaluation.py` support offline comparison
against human-labelled relevance judgements:

- Precision@K for top-of-digest usefulness
- NDCG@K for graded ordering quality
- Reciprocal rank for first relevant-item placement

This baseline is intentionally separated from model integrations so Laya or
Jev can be evaluated against the same labelled examples before affecting
production ordering.

Run the reproducible backend comparison command:

```bash
python scripts/evaluate_ranking.py --backend deterministic
python scripts/evaluate_ranking.py --backend laya --device cpu
```

Run both backends and get a machine-readable recommendation:

```bash
python scripts/compare_ranking_backends.py \
  --fixture tests/fixtures/ranking_labels_human.json
```

The comparison command requires `label_source: "human"` for every item. Use
`evaluate_ranking.py` with the provisional fixture for exploratory experiments.

For a promotion-quality gate, require a larger, multi-source fixture:

```bash
python scripts/evaluate_ranking.py --backend deterministic --min-items 100 --min-sources 4
```

The Laya command requires the optional Laya environment and reports backend
metadata, latency, ranking metrics, model warnings, confidence values, and the
resulting order. Laya remains opt-in until it is evaluated on a substantially
larger labelled fixture.

Build a review queue from historical digests before expanding the benchmark:

```bash
python scripts/export_ranking_review.py
```

This writes `tests/fixtures/ranking_review.json` with full summaries and
metadata. The `relevance` field is intentionally blank; `suggested_category`
and `suggested_priority_score` are only context for a human reviewer and must
not be treated as ground truth. Set `label_source` and `label_notes` when
reviewing each item, then copy verified numeric relevance labels into the
evaluation fixture.

Check annotation progress and promotion readiness:

```bash
python scripts/ranking_label_status.py
```

The command reports completion by source and returns
`ready_for_comparison: true` only when every item is labelled, every source
has at least one labelled item, every label is explicitly marked
`label_source: "human"`, and the minimum item/source thresholds are met.
Assistant-provisional labels can be used for exploratory comparisons but cannot
pass this promotion gate.

For a faster browser workflow, start the API and open
`http://127.0.0.1:8000/label-review`. The workspace shows one item at a time,
supports keyboard scores `0`–`4`, records an optional rationale, and saves to
`tests/fixtures/ranking_labels_human.json` without modifying the provisional
fixture.

To refresh an expanded exploratory corpus from a live collector snapshot:

```bash
python scripts/build_assistant_expanded_fixture.py
```

This combines the reviewed historical examples with newly collected public
items and applies an explicit provisional rubric. It is useful for stress
testing rankers, but its labels remain non-human and cannot authorize a
production change.

---

## Zero-Cost Infrastructure

- **LLM Inference**: $0 (Groq Cloud API free tier, using `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`)
- **Automated Scheduling**: $0 (GitHub Actions scheduled cron at 8:00 AM UTC)
- **Database & State**: $0 (Local SQLite file with WAL mode, committed or cached)
- **Feed Ingestion**: $0 (All public APIs & RSS feeds)
- **Web UI & Dashboard**: $0 (FastAPI + Vanilla CSS/JS glassmorphism)

## Architecture

TechPulse operates as a modular, decoupled **3-Agent Autonomous Pipeline**:

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                        6 High-Signal Data Sources                      │
 │   GitHub Trending · GitHub Search · Hacker News · HF Papers · Dev.to · ArXiv AI │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                   Agent 1: Harvester (harvester.py)                    │
 │    - Concurrent harvesting via ThreadPoolExecutor (<7s total)          │
 │    - In-batch URL deduplication                                        │
 │    - 30-day SQLite sliding window filter (eliminates repeat items)    │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ (Novel RawItems)
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                   Agent 2: Processor (processor.py)                    │
 │    - Groq Cloud API: Primary (openai/gpt-oss-120b)                     │
 │    - Automatic fallback (qwen/qwen3.8-27b)                             │
 │    - Pydantic schema validation & Markdown fence stripping            │
 │    - "Must Read" vs "Inspiration" vs "Skip" categorization             │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │ (Curated TechDigest)
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                   Agent 3: Publisher (publisher.py)                    │
 │    - Compiles structured Markdown report with source badges & tags     │
 │    - Idempotent export to `digests/YYYY-MM-DD.md`                      │
 │    - Persists digest summary & items to SQLite historical database     │
 │    - Windows-safe encoding (cp1252 & UTF-8 resilient)                  │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 6 High-Signal Sources

| Source | Collector | Content Type |
|---|---|---|
| **GitHub Trending** | `GitHubTrendingCollector` | Top trending repos across Python and all languages |
| **GitHub Search API** | `GitHubSearchCollector` | Newly active high-star repositories in AI agents & tooling |
| **Hacker News** | `HackerNewsCollector` | Front-page tech discussions and announcements via Algolia API |
| **Hugging Face Papers**| `HuggingFacePapersCollector` | Top daily AI/ML research papers with community upvotes |
| **Dev.to Articles** | `DevToCollector` | Top engineering deep dives in AI, Python, and open-source |
| **ArXiv AI** | `ArXivCollector` | Cutting-edge preprints in `cs.AI` and `cs.LG` via official Atom API |

---

## Project Structure

```
AIAgentInitiative/
├── config/
│   ├── __init__.py
│   └── settings.py          # Centralized configuration & user interest profile
├── src/
│   ├── __init__.py
│   ├── models.py            # Pydantic v2 data models (RawItem, DigestItem, TechDigest)
│   ├── storage/
│   │   ├── __init__.py
│   │   └── database.py      # SQLite WAL database & 30-day deduplication engine
│   ├── security/            # Rate limiting, hourly caps, & in-memory caching
│   │   ├── __init__.py
│   │   ├── quota_manager.py # Concurrency lock, harvest cooldown, & sliding-window hourly caps
│   │   └── cache_manager.py # In-memory TTL cache with instant invalidation
│   ├── collectors/          # Decoupled data collectors with isolated error handling
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract BaseCollector with telemetry
│   │   ├── github_trending.py
│   │   ├── github_search.py
│   │   ├── hacker_news.py
│   │   ├── huggingface.py
│   │   ├── devto.py
│   │   └── arxiv_ai.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── harvester.py     # Agent 1: Parallel harvesting & deduplication
│   │   ├── processor.py     # Agent 2: Groq LLM filter & categorizer with fallback
│   │   └── publisher.py     # Agent 3: Markdown compiler & exporter
│   └── orchestrator.py      # End-to-end pipeline coordinator
├── tests/                   # Complete test suite (36 core + 10 UI passing)
│   ├── __init__.py
│   ├── test_models.py       # Pydantic validation tests
│   ├── test_database.py     # SQLite deduplication & window tests
│   ├── test_collectors.py   # Collector parsing & error isolation tests
│   ├── test_pipeline.py     # End-to-end integration tests
│   ├── test_api_security.py # Rate limits, cooldowns, caps, and caching tests
│   └── test_ui_playwright.py# Playwright browser E2E test suite (10/10)
├── digests/                 # Generated daily Markdown reports (YYYY-MM-DD.md)
├── data/                    # SQLite database storage (tech_digest.db)
├── Dockerfile               # Production container definition with health check
├── fly.toml                 # Free-tier Fly.io config with persistent volume mount
├── main.py                  # CLI entry point (--dry-run, --stats, --date)
├── api.py                   # Hardened FastAPI server with slowapi & telemetry
├── requirements.txt         # Dependencies
├── pytest.ini               # Pytest configuration
├── .env.example             # Template for API credentials & security controls
└── README.md
```

---

## Production Security & Rate Limiting

The application includes built-in protection against API abuse and quota exhaustion:

| Security Layer | Policy | Action on Breach |
|---|---|---|
| **Read Rate Limit** | 60 requests / minute per IP | Returns `429 Too Many Requests` |
| **Harvest Rate Limit** | 5 requests / hour per IP | Returns `429 Too Many Requests` |
| **Global Harvest Cooldown** | 10 minutes mandatory minimum gap | Returns `429` with remaining seconds |
| **Hourly Global Cap** | Max 4 harvests / hour (sliding window) | Returns `429` with slot reset countdown |
| **Concurrency Lock** | Only 1 harvest executes at any given time | Returns `409 Conflict` |
| **Response Caching** | 5-min in-memory cache for digests & stats | `X-Cache: HIT`, `Cache-Control` |
| **Optional API Key** | `X-API-Key` header authentication | Returns `401 Unauthorized` |
| **Health Check** | `GET /api/health` cloud health monitoring | Returns 200 with DB & quota telemetry |

---

## Free-Tier Cloud Deployment (Render.com — Zero Credit Card Required)

Render provides a **100% free Web Service tier** with **no credit card required**, automated HTTPS certificates, and built-in health monitoring.

### 🛡️ Why SQLite Survives on Render Ephemeral Disks:
Standard free web tiers reset disks on idle spin-down. TechPulse AI Digest Bot solves this natively with **Markdown Auto-Hydration**:
When the service boots on a fresh container, [`DigestDatabase`](file:///c:/Users/Rentorzo/Downloads/AIAgentInitiative/src/storage/database.py) automatically scans all committed `digests/*.md` files, parses their items, and re-populates SQLite and the 30-day deduplication history in **0.4 seconds**. Zero data is ever lost.

### 🚀 Deploy to Render in 2 Steps:
1. Open [dashboard.render.com](https://dashboard.render.com) and click **New +** → **Blueprint**.
2. Connect your private repository: `Bugendaitech-Nishant/techpulse-ai-digest-bot`.
   - Render reads [`render.yaml`](file:///c:/Users/Rentorzo/Downloads/AIAgentInitiative/render.yaml) automatically.
   - Paste your free `GROQ_API_KEY` when prompted.
   - Click **Apply**! Your live app will be accessible at: `https://techpulse-ai-digest.onrender.com`.

---

## Alternative: Self-Hosted on Coolify / Docker

If you have your own VPS running [Coolify](https://coolify.io):
1. In Coolify, click **New Resource** → **Application** → **From GitHub**.
2. Select `Bugendaitech-Nishant/techpulse-ai-digest-bot`.
3. Set Build Pack to **Dockerfile** (uses our pre-configured [`Dockerfile`](file:///c:/Users/Rentorzo/Downloads/AIAgentInitiative/Dockerfile)).
4. Add environment variable `GROQ_API_KEY` and click **Deploy**.

*(Note on Cloudflare Workers: Cloudflare Workers is an edge V8/JS runtime with a 10-30ms CPU limit and no native threading or filesystem, making it incompatible with Python multi-agent threadpool harvesting and SQLite).*

---

## Quick Start

### 1. Installation

```bash
git clone https://github.com/Bugendaitech-Nishant/techpulse-ai-digest-bot.git
cd techpulse-ai-digest-bot
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` using `.env.example`:

```bash
cp .env.example .env
```

Add your free Groq API key:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
```

### 3. Run Web Observatory Server

```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to `http://localhost:8000` to access the Cockpit interface.

### 4. Run Full Test Suite

```bash
pytest tests/ -v
```

---

## Zero-Cost Infrastructure

- **LLM Inference**: $0 (Groq Cloud API free tier, using `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`)
- **Web & API Host**: $0 (Fly.io free tier or Render)
- **Database & State**: $0 (Persistent SQLite volume with WAL mode)
- **Rate-Limiting & Caching**: $0 (In-memory token bucket + SlowAPI)
- **Feed Ingestion**: $0 (All public APIs & RSS feeds)

### Daily email brief

`scripts/run_daily.py` runs the pipeline and emails the top items. The GitHub Actions workflow
`.github/workflows/digest.yml` runs it every day at 08:00 UTC. Set these repository secrets:

```bash
gh secret set GROQ_API_KEY
gh secret set SMTP_HOST
gh secret set SMTP_PORT
gh secret set SMTP_USER
gh secret set SMTP_PASSWORD
gh secret set EMAIL_FROM
gh secret set EMAIL_TO
gh variable set PUBLIC_URL --body https://techpulse-ai-digest.onrender.com/
```

Locally, copy the SMTP lines from `.env.example` into `.env` and run
`python scripts/run_daily.py --no-email` to test without sending. Exit code 3 means the run
finished but looks suspect (too few items, or the AI curator was not used).
