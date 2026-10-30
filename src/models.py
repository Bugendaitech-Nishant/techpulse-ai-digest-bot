"""
models.py — Strongly-typed Pydantic models for TechPulse AI Digest Bot.
Enforces validation across data harvesting, database persistence, LLM curation, and publishing.
"""

from datetime import datetime, timezone
from typing import List, Literal, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, field_validator


class RawItem(BaseModel):
    """Raw item fetched by any data collector."""
    title: str = Field(..., min_length=2, description="Clean title of the repository, article, or paper")
    url: str = Field(..., description="Direct target URL")
    description: str = Field(default="", description="Snippet, abstract, or description")
    source: str = Field(..., description="Origin collector key (e.g., github_trending, hacker_news, huggingface)")
    score: int = Field(default=0, ge=0, description="Normalized score (stars, upvotes, points)")
    language: Optional[str] = Field(default="", description="Primary programming language or topic")
    published_at: Optional[str] = Field(default="", description="ISO datetime or date string if available")
    extra_metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary collector-specific tags")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        return " ".join(v.strip().split())


class CollectorResult(BaseModel):
    """Execution telemetry and collected items from a single collector."""
    collector_name: str
    items: List[RawItem] = Field(default_factory=list)
    success: bool = True
    duration_seconds: float = 0.0
    error: Optional[str] = None


class DigestItem(BaseModel):
    """LLM-filtered, categorized, and summarized item."""
    title: str = Field(..., description="Item title")
    url: str = Field(..., description="Direct link")
    source: str = Field(..., description="Origin source name")
    category: Literal["Must Read", "Inspiration", "Skip"] = Field(
        ..., description="Priority categorization based on technical profile"
    )
    summary: str = Field(..., description="Punchy, factual 2-sentence summary of the item")
    why_it_matters: str = Field(..., description="1-sentence explanation of concrete value for technical engineers")
    tags: List[str] = Field(default_factory=list, description="Extracted tech tags (e.g. ['python', 'agent', 'rag'])")
    published_at: str = Field(default="", description="When the source published or last updated it (ISO); empty when unknown")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    rank: int = Field(default=0, ge=0)


class TechDigest(BaseModel):
    """Complete finalized daily digest report."""
    date: str = Field(..., description="Date string (YYYY-MM-DD)")
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    items: List[DigestItem] = Field(default_factory=list)
    total_harvested: int = 0
    total_deduplicated: int = 0
    total_curated: int = 0
    ranking_backend: str = "deterministic"
    ranking_version: str = "v1"

    @property
    def must_reads(self) -> List[DigestItem]:
        return [item for item in self.items if item.category == "Must Read"]

    @property
    def inspirations(self) -> List[DigestItem]:
        return [item for item in self.items if item.category == "Inspiration"]

    @property
    def skips(self) -> List[DigestItem]:
        return [item for item in self.items if item.category == "Skip"]
