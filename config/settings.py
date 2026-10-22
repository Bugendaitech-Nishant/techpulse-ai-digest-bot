"""
settings.py — Centralized typed configuration for TechPulse AI Digest Bot.
Handles API credentials, LLM model selection, data collectors, user interest profiles,
and storage paths.
"""

import os
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

    # ─── Database & Deduplication ────────────────────────────────────────
    DB_PATH: Path = DATA_DIR / "tech_digest.db"
    DEDUP_WINDOW_DAYS: int = 30  # Don't resurface items seen in the last 30 days

    # ─── User Technical Profile ──────────────────────────────────────────
    USER_INTERESTS: List[str] = [
        "AI agents and multi-agent systems",
        "Local LLMs and model optimization",
        "Python developer tooling & frameworks",
        "Cloud automation and serverless architectures",
        "Open-source AI infrastructure",
        "High-performance backend systems",
    ]

    USER_PROFILE: str = (
        "Staff Software Engineer & AI Architect specializing in autonomous agent workflows, "
        "Python ecosystems, open-source AI models, developer productivity tools, "
        "and production-grade cloud infrastructure."
    )

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

    # ─── Production Security & Rate Limiting ────────────────────────────
    APP_VERSION: str = "2.1.0"
    RATE_LIMIT_READ: str = os.getenv("RATE_LIMIT_READ", "60/minute")
    RATE_LIMIT_HARVEST: str = os.getenv("RATE_LIMIT_HARVEST", "5/hour")
    HARVEST_COOLDOWN_SECONDS: int = int(os.getenv("HARVEST_COOLDOWN_SECONDS", "600"))  # 10 min
    MAX_HARVESTS_PER_HOUR: int = int(os.getenv("MAX_HARVESTS_PER_HOUR", "4"))
    HARVEST_API_KEY: Optional[str] = os.getenv("HARVEST_API_KEY", None)
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 min


settings = Settings()
