"""
processor.py — Agent 2: Groq LLM Filter, Ranker & Categorizer
Uses Groq API with primary (openai/gpt-oss-120b) and fallback (qwen/qwen3.8-27b) models
to filter out noise, categorize items into "Must Read" / "Inspiration" / "Skip",
and generate factual 2-sentence summaries and "Why it matters" notes.
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from groq import Groq

from src.models import RawItem, DigestItem, TechDigest
from config.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite AI technical curator and Principal Software Architect.
Analyze the following batch of technical items (repositories, research papers, community discussions, and articles).

Curate and categorize every item strictly based on this profile:
TARGET PROFILE:
{user_profile}

FOCUS AREAS:
{interest_keywords}

CATEGORIZATION RULES:
1. "Must Read": Highest priority. Directly relevant to AI agents, LLM architectures, Python dev tooling, or high-impact open source. Write a clear technical summary and why it matters.
2. "Inspiration": Interesting architectures, side-project ideas, or emerging tech trends.
3. "Skip": Generic marketing, duplicate concepts, cryptocurrency noise, or unrelated domain topics.

OUTPUT SPECIFICATION:
Respond ONLY with a valid JSON object matching this schema:
{{
  "items": [
    {{
      "title": "Clean item title",
      "url": "Direct link from input",
      "source": "Source name from input",
      "category": "Must Read" | "Inspiration" | "Skip",
      "summary": "Factual 2-sentence summary of what this actually builds or discusses.",
      "why_it_matters": "1 concise sentence explaining practical relevance for engineers.",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}

No conversational filler, no code fences, only valid raw JSON.
"""


class ProcessorAgent:
    """Agent responsible for intelligent LLM curation and structured output validation."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        if not self.api_key:
            logger.warning("GROQ_API_KEY is not configured. LLM processing will use rule-based fallback.")
        self.client = Groq(api_key=self.api_key) if self.api_key else None

    def process(self, raw_items: List[RawItem], target_date: str) -> TechDigest:
        """
        Process raw items through Groq LLM with schema validation and automatic model fallback.
        """
        logger.info(f"Agent 2 (Processor): Starting LLM curation of {len(raw_items)} items for {target_date}")

        if not raw_items:
            logger.info("Agent 2 (Processor): No items to process.")
            return TechDigest(date=target_date, items=[], total_harvested=0, total_curated=0)

        # If no client or no key, use heuristic fallback
        if not self.client:
            return self._heuristic_fallback(raw_items, target_date)

        # Construct batch payload (capped to top 40 to stay comfortably within context window)
        batch = raw_items[:40]
        items_payload = [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "score": item.score,
                "language": item.language,
                "description": item.description,
            }
            for item in batch
        ]

        system_msg = SYSTEM_PROMPT.format(
            user_profile=settings.USER_PROFILE,
            interest_keywords=", ".join(settings.USER_INTERESTS),
        )
        user_msg = "Please curate and categorize these items:\n\n" + json.dumps(items_payload, indent=2)

        models_to_try = [settings.GROQ_PRIMARY_MODEL, settings.GROQ_FALLBACK_MODEL]

        for model in models_to_try:
            for attempt in range(1, settings.MAX_LLM_RETRIES + 1):
                try:
                    logger.info(f"Agent 2 (Processor): Calling model [{model}] (attempt {attempt})")
                    completion = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg},
                        ],
                        temperature=settings.LLM_TEMPERATURE,
                        max_tokens=settings.LLM_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )

                    content = completion.choices[0].message.content or "{}"
                    digest_items = self._parse_and_validate(content, batch)

                    if digest_items:
                        logger.info(
                            f"Agent 2 (Processor): Successfully curated {len(digest_items)} items with [{model}]"
                        )
                        return TechDigest(
                            date=target_date,
                            items=digest_items,
                            total_harvested=len(raw_items),
                            total_curated=len([i for i in digest_items if i.category in ("Must Read", "Inspiration")]),
                        )

                except Exception as e:
                    logger.warning(f"Agent 2 (Processor): Model [{model}] attempt {attempt} failed: {e}")

        # If all LLM attempts fail, return rule-based fallback
        logger.error("Agent 2 (Processor): All LLM calls failed. Falling back to rule-based curation.")
        return self._heuristic_fallback(raw_items, target_date)

    def _parse_and_validate(self, raw_json_str: str, original_items: List[RawItem]) -> List[DigestItem]:
        """Parse JSON response, strip code fences if present, and validate via Pydantic."""
        cleaned = raw_json_str.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)
        items_data = data.get("items", [])
        if not isinstance(items_data, list):
            return []

        # Create quick URL lookup for fallback
        item_lookup = {item.url: item for item in original_items}
        validated_items: List[DigestItem] = []

        for item_dict in items_data:
            try:
                # Ensure URL is present and matches
                url = item_dict.get("url")
                if not url or url not in item_lookup:
                    continue

                category = item_dict.get("category", "Inspiration")
                if category not in ("Must Read", "Inspiration", "Skip"):
                    category = "Inspiration"

                validated = DigestItem(
                    title=item_dict.get("title") or item_lookup[url].title,
                    url=url,
                    source=item_dict.get("source") or item_lookup[url].source,
                    category=category,
                    summary=item_dict.get("summary") or item_lookup[url].description or "No summary available.",
                    why_it_matters=item_dict.get("why_it_matters") or "Matches your general tech profile.",
                    tags=item_dict.get("tags") or [],
                )
                validated_items.append(validated)
            except Exception as e:
                logger.debug(f"Skipping malformed LLM item: {e}")
                continue

        return validated_items

    def _heuristic_fallback(self, raw_items: List[RawItem], target_date: str) -> TechDigest:
        """Deterministic rule-based categorization when LLM is unavailable or offline."""
        items: List[DigestItem] = []
        interest_keywords = [k.lower() for k in settings.USER_INTERESTS]

        for raw in raw_items:
            text = f"{raw.title} {raw.description} {raw.language}".lower()
            # Match keywords
            matches = [k for k in interest_keywords if any(word in text for word in k.split())]

            if len(matches) >= 2 or raw.score >= 100:
                cat = "Must Read"
            elif len(matches) >= 1 or raw.score >= 20:
                cat = "Inspiration"
            else:
                cat = "Skip"

            items.append(DigestItem(
                title=raw.title,
                url=raw.url,
                source=raw.source,
                category=cat,
                summary=raw.description or "Automated tech feed item.",
                why_it_matters=f"Matched interest criteria: {', '.join(matches[:2]) if matches else 'High popularity'}.",
                tags=matches[:3],
            ))

        return TechDigest(
            date=target_date,
            items=items,
            total_harvested=len(raw_items),
            total_curated=len([i for i in items if i.category in ("Must Read", "Inspiration")]),
        )
