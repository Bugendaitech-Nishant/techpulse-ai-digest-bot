"""
settings.py — Centralized typed configuration for TechPulse AI Digest Bot.
Handles API credentials, LLM model selection, data collectors, user interest profiles,
and storage paths.
"""

import os
import tomllib
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv()

# Root paths
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DIGESTS_DIR: Path = PROJECT_ROOT / "digests"
DATA_DIR: Path = PROJECT_ROOT / "data"

# Ensure directories exist
DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_profile() -> dict:
    """Read the reader profile; a missing or broken file falls back to the built-in defaults."""
    path = Path(os.getenv("PROFILE_FILE", PROJECT_ROOT / "config" / "profile.toml"))
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


_PROFILE = _load_profile()


class Settings:
    """Application configuration settings."""

    # Project directories
    DIGESTS_DIR: Path = DIGESTS_DIR
    DATA_DIR: Path = DATA_DIR

    # ─── LLM Configuration ──────────────────────────────────────────────
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    # Default model with proven fast JSON-mode support on current Groq tier
    GROQ_PRIMARY_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    GROQ_FALLBACK_MODEL: str = "qwen/qwen3.8-27b"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096
    MAX_LLM_RETRIES: int = 2
    LLM_BATCH_SIZE: int = int(os.getenv("LLM_BATCH_SIZE", "12"))  # small batches: big ones get silently truncated
    LLM_MAX_ITEMS: int = int(os.getenv("LLM_MAX_ITEMS", "90"))  # per-run cap on items sent to the model

    # ─── Database & Deduplication ────────────────────────────────────────
    DB_PATH: Path = Path(os.getenv("DB_PATH", str(DATA_DIR / "tech_digest.db")))
    DEDUP_WINDOW_DAYS: int = 30  # Don't resurface items seen in the last 30 days

    # ─── User Technical Profile ──────────────────────────────────────────
    USER_INTERESTS: List[str] = _PROFILE.get("interests") or [
        "AI agents and multi-agent systems",
        "Local LLMs and model optimization",
        "Python developer tooling & frameworks",
        "Cloud automation and serverless architectures",
        "Open-source AI infrastructure",
        "High-performance backend systems",
    ]
    USER_AVOID: List[str] = _PROFILE.get("avoid") or []
    USER_TOOLS: List[str] = _PROFILE.get("tools") or []
    USER_PROFILE: str = " ".join((_PROFILE.get("summary") or (
        "Staff Software Engineer & AI Architect specializing in autonomous agent workflows, "
        "Python ecosystems, open-source AI models, developer productivity tools, "
        "and production-grade cloud infrastructure."
    )).split())

    # ─── Reader feedback (thumbs up / down) ──────────────────────────────
    FEEDBACK_FILE: Path = Path(os.getenv("FEEDBACK_FILE", str(DATA_DIR / "feedback.jsonl")))
    FEEDBACK_SECRET: str = os.getenv("FEEDBACK_SECRET", "")  # signs the one-click email links
    FEEDBACK_GITHUB_TOKEN: str = os.getenv("FEEDBACK_GITHUB_TOKEN", "")  # fine-grained token, Contents read/write
    GITHUB_REPO: str = os.getenv("GITHUB_REPO", "Bugendaitech-Nishant/techpulse-ai-digest-bot")
    RUNS_FILE: Path = Path(os.getenv("RUNS_FILE", str(DIGESTS_DIR / "runs.jsonl")))
    FEEDBACK_EXAMPLES: int = int(os.getenv("FEEDBACK_EXAMPLES", "8"))  # per direction, in the curation prompt

    # ─── Collectors Configuration ────────────────────────────────────────
    COLLECTOR_TIMEOUT: int = 12  # seconds per collector
    MAX_CONCURRENT_COLLECTORS: int = 6
    USER_AGENT: str = "TechPulse-AI-Digest-Bot/2.0 (+https://github.com/developer/tech-digest)"

    # Source Limits
    LIMIT_GITHUB_TRENDING: int = 25
    LIMIT_GITHUB_SEARCH: int = 15
    LIMIT_HACKER_NEWS: int = 25
    LIMIT_HUGGINGFACE_PAPERS: int = 15
    LIMIT_DEVTO: int = 15
    LIMIT_ARXIV: int = 15
    MAX_ITEM_AGE_DAYS: int = int(os.getenv("MAX_ITEM_AGE_DAYS", "7"))  # older items are dropped, except security advisories
    LIMIT_SECURITY: int = int(os.getenv("LIMIT_SECURITY", "5"))  # advisories per run
    SECURITY_LOOKBACK_DAYS: int = int(os.getenv("SECURITY_LOOKBACK_DAYS", "14"))
    GITHUB_API_TOKEN: str = os.getenv("GITHUB_TOKEN", "")  # optional, only raises the advisory API rate limit

    # ─── Email delivery (SMTP; works with Gmail app passwords, Resend, Mailgun, SES) ──
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))  # 465 uses implicit TLS, anything else STARTTLS
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
    EMAIL_TO: str = os.getenv("EMAIL_TO", "")  # comma-separated
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "https://techpulse-ai-digest.onrender.com/")
    BRIEF_TOP_N: int = int(os.getenv("BRIEF_TOP_N", "7"))
    MIN_KEPT_ITEMS: int = int(os.getenv("MIN_KEPT_ITEMS", "5"))  # fewer than this marks a run as suspect

    # ─── Production Security & Rate Limiting ────────────────────────────
    APP_VERSION: str = "2.1.0"
    RATE_LIMIT_READ: str = os.getenv("RATE_LIMIT_READ", "60/minute")
    RATE_LIMIT_HARVEST: str = os.getenv("RATE_LIMIT_HARVEST", "5/hour")
    HARVEST_COOLDOWN_SECONDS: int = int(os.getenv("HARVEST_COOLDOWN_SECONDS", "600"))  # 10 min
    MAX_HARVESTS_PER_HOUR: int = int(os.getenv("MAX_HARVESTS_PER_HOUR", "4"))
    HARVEST_API_KEY: Optional[str] = os.getenv("HARVEST_API_KEY", None)
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 min


settings = Settings()
