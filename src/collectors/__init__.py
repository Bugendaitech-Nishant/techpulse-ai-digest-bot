"""
Collectors package for TechPulse AI Digest Bot.
Contains modular data collectors for GitHub, Hacker News, Hugging Face, Dev.to, and ArXiv.
"""

from src.collectors.base import BaseCollector
from src.collectors.github_trending import GitHubTrendingCollector
from src.collectors.github_search import GitHubSearchCollector
from src.collectors.hacker_news import HackerNewsCollector
from src.collectors.huggingface import HuggingFacePapersCollector
from src.collectors.devto import DevToCollector
from src.collectors.arxiv_ai import ArXivCollector
from src.collectors.security_advisories import SecurityAdvisoryCollector

__all__ = [
    "BaseCollector",
    "GitHubTrendingCollector",
    "GitHubSearchCollector",
    "HackerNewsCollector",
    "HuggingFacePapersCollector",
    "DevToCollector",
    "ArXivCollector",
    "SecurityAdvisoryCollector",
]
