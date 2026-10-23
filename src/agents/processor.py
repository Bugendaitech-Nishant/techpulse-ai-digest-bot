"""
processor.py — Agent 2: Groq LLM Filter, Ranker & Categorizer
Uses Groq API with primary (openai/gpt-oss-120b) and fallback (qwen/qwen3.8-27b) models
to filter out noise, categorize items into "Must Read" / "Inspiration" / "Skip",
and generate factual 2-sentence summaries and "Why it matters" notes.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from groq import Groq

from src.backends import DeterministicV1Backend, RankingBackend
from src.models import RawItem, DigestItem, TechDigest
from config.settings import settings

logger = logging.getLogger(__name__)

SECURITY_SOURCE = "security_advisories"

SYSTEM_PROMPT = """You are an elite AI technical curator and Principal Software Architect.
Analyze the following batch of technical items (repositories, research papers, community discussions, and articles).

Curate and categorize every item strictly based on this profile:
TARGET PROFILE:
{user_profile}

FOCUS AREAS:
{interest_keywords}

PUSH DOWN, EVEN IF POPULAR:
{avoid_keywords}
{feedback_block}
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
      "relevance": 0-4 integer,
      "impact": 0-4 integer,
      "summary": "Factual 2-sentence summary of what this actually builds or discusses.",
      "why_it_matters": "1 concise sentence explaining practical relevance for engineers. Be specific to this item, never generic.",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}

SCORING (relevance = fit to the profile, impact = how much it changes what an engineer should do):
4 = act on it now (a security incident in a tool they run, a release that changes their stack)
3 = clearly useful (a strong tool, framework or result in their focus areas)
2 = interesting but niche or indirect
1 = marginal
0 = unrelated

Return exactly one entry for every input item, using the same url. Never omit an item; use category "Skip" with scores 0 instead.
No conversational filler, no code fences, only valid raw JSON.
"""


class ProcessorAgent:
    """Agent responsible for intelligent LLM curation and structured output validation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        ranking_backend: Optional[RankingBackend] = None,
        feedback_provider: Optional[Callable[[], Dict[str, List[Dict[str, str]]]]] = None,
    ):
        self.feedback_provider = feedback_provider
        self.api_key = api_key or settings.GROQ_API_KEY
        self.ranking_backend = ranking_backend or DeterministicV1Backend()
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

        # Security advisories are factual and already matched to the reader's tools, so they skip
        # the model: it could only dilute or reword them. They are always shown first.
        security_raw = [r for r in raw_items if r.source == SECURITY_SOURCE]
        if security_raw:
            raw_items = [r for r in raw_items if r.source != SECURITY_SOURCE]
            rest = self.process(raw_items, target_date) if raw_items else TechDigest(date=target_date)
            return self._with_security_first(rest, security_raw)

        # If no client or no key, use heuristic fallback
        if not self.client:
            return self._heuristic_fallback(raw_items, target_date)

        selected = self._select_for_curation(raw_items)
        curated: dict[str, DigestItem] = {}
        models_to_try = [settings.GROQ_PRIMARY_MODEL, settings.GROQ_FALLBACK_MODEL]

        for start in range(0, len(selected), settings.LLM_BATCH_SIZE):
            self._curate_chunk(selected[start:start + settings.LLM_BATCH_SIZE], curated, models_to_try)

        # The model sometimes omits items; ask once more for exactly the missing ones.
        missing = [r for r in selected if r.url not in curated]
        if missing and curated:
            logger.warning(f"Agent 2 (Processor): {len(missing)} items missing from model output, retrying them")
            self._curate_chunk(missing, curated, models_to_try)

        if not curated:
            logger.error("Agent 2 (Processor): All LLM calls failed. Falling back to rule-based curation.")
            return self._heuristic_fallback(raw_items, target_date)

        digest_items = [curated[r.url] for r in selected if r.url in curated]
        leftover = [r for r in selected if r.url not in curated]
        if leftover:
            logger.warning(f"Agent 2 (Processor): {len(leftover)} items stayed unreviewed; using keyword fallback for them")
            digest_items += [self._heuristic_item(r) for r in leftover]

        digest_items = self.ranking_backend.rank(digest_items, selected)
        logger.info(f"Agent 2 (Processor): Curated {len(curated)}/{len(selected)} items with the LLM")
        return TechDigest(
            date=target_date,
            items=digest_items,
            total_harvested=len(raw_items),
            total_curated=len([i for i in digest_items if i.category in ("Must Read", "Inspiration")]),
            ranking_backend=self.ranking_backend.metadata.name,
            ranking_version=self.ranking_backend.metadata.version,
        )

    @staticmethod
    def _security_item(raw: RawItem) -> DigestItem:
        """Turn an advisory into a digest item without a model: the facts are already structured."""
        meta = raw.extra_metadata or {}
        severity = str(meta.get("severity", "")).lower()
        packages: dict = meta.get("packages") or {}
        names = ", ".join(sorted(packages)) or "a tool you run"
        fixes = [f"{name} {version}" for name, version in sorted(packages.items()) if version]
        fix_text = f"Fixed in {', '.join(fixes)}." if fixes else "No fixed version is listed."
        impact = {"malware": 1.0, "critical": 1.0, "high": 0.85, "moderate": 0.6}.get(severity, 0.5)
        category = "Must Read" if severity in ("malware", "critical", "high") else "Inspiration"
        return DigestItem(
            title=f"Security: {raw.title}",
            url=raw.url,
            source=raw.source,
            category=category,
            summary=raw.description[:320],
            why_it_matters=f"Affects {names}, which you run. Severity: {severity or 'unknown'}. {fix_text}",
            tags=["security", *sorted(packages)],
            relevance_score=1.0,
            impact_score=impact,
        )

    def _with_security_first(self, digest: TechDigest, security_raw: List[RawItem]) -> TechDigest:
        """Prepend deterministic security items to a digest and renumber the ranks."""
        security_items = [self._security_item(r) for r in security_raw]
        security_items.sort(key=lambda i: (i.category != "Must Read", -i.impact_score, i.title))
        items = security_items + list(digest.items)
        items = [i.model_copy(update={"rank": n}) for n, i in enumerate(items, 1)]
        return digest.model_copy(update={
            "items": items,
            "total_harvested": digest.total_harvested + len(security_raw),
            "total_curated": digest.total_curated + len(security_items),
        })

    def _build_system_prompt(self) -> str:
        """Profile, anti-interests and the reader's own recent ratings as calibration examples."""
        examples: Dict[str, List[Dict[str, str]]] = {"up": [], "down": []}
        if self.feedback_provider:
            try:
                examples = self.feedback_provider() or examples
            except Exception as error:  # a broken feedback store must never stop curation
                logger.warning(f"Agent 2 (Processor): feedback examples unavailable: {error}")
        return SYSTEM_PROMPT.format(
            user_profile=settings.USER_PROFILE,
            interest_keywords="; ".join(settings.USER_INTERESTS),
            avoid_keywords="; ".join(settings.USER_AVOID) or "nothing specific",
            feedback_block=self._format_feedback(examples),
        )

    @staticmethod
    def _format_feedback(examples: Dict[str, List[Dict[str, str]]]) -> str:
        """Render the reader's recent verdicts; empty when there are none yet."""
        def lines(rows: List[Dict[str, str]]) -> str:
            return "\n".join(f"- {r['title']} ({r.get('source', '')}): {r.get('summary', '')[:140]}" for r in rows)

        parts = []
        if examples.get("up"):
            parts.append("The reader found these USEFUL (score items like them higher):\n" + lines(examples["up"]))
        if examples.get("down"):
            parts.append("The reader found these NOT USEFUL (score items like them lower):\n" + lines(examples["down"]))
        if not parts:
            return ""
        return "\nREADER FEEDBACK, recent real verdicts. Calibrate to them:\n" + "\n\n".join(parts) + "\n"

    @staticmethod
    def _select_for_curation(raw_items: List[RawItem]) -> List[RawItem]:
        """Cap the run at LLM_MAX_ITEMS, taking the best of each source in turn so none is starved."""
        by_source: dict[str, List[RawItem]] = {}
        for item in sorted(raw_items, key=lambda r: r.score, reverse=True):
            by_source.setdefault(item.source, []).append(item)
        selected: List[RawItem] = []
        while len(selected) < settings.LLM_MAX_ITEMS and any(by_source.values()):
            for source in list(by_source):
                if by_source[source] and len(selected) < settings.LLM_MAX_ITEMS:
                    selected.append(by_source[source].pop(0))
        return selected

    def _curate_chunk(self, chunk: List[RawItem], curated: dict, models_to_try: List[str]) -> None:
        """Send one chunk to the model chain and add every validated item to `curated`."""
        payload = [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "score": item.score,
                "language": item.language,
                "description": item.description[:600],
            }
            for item in chunk
        ]
        system_msg = self._build_system_prompt()
        user_msg = "Please curate and categorize these items:\n\n" + json.dumps(payload, indent=2)

        for model in models_to_try:
            for attempt in range(1, settings.MAX_LLM_RETRIES + 1):
                try:
                    logger.info(f"Agent 2 (Processor): Calling model [{model}] on {len(chunk)} items (attempt {attempt})")
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
                    for item in self._parse_and_validate(content, chunk):
                        curated.setdefault(item.url, item)
                    if any(r.url in curated for r in chunk):
                        return
                except Exception as e:
                    logger.warning(f"Agent 2 (Processor): Model [{model}] attempt {attempt} failed: {e}")

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
                    relevance_score=self._scale_score(item_dict.get("relevance")),
                    impact_score=self._scale_score(item_dict.get("impact")),
                )
                validated_items.append(validated)
            except Exception as e:
                logger.debug(f"Skipping malformed LLM item: {e}")
                continue

        return validated_items

    @staticmethod
    def _scale_score(value) -> float:
        """Map the model's 0-4 integer to the 0-1 range; absent or invalid scores stay 0 (unscored)."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        return max(0.0, min(1.0, float(value) / 4.0))

    # Words too generic to signal an interest on their own ("systems", "local", "open", ...).
    _GENERIC_WORDS = frozenset({
        "and", "the", "for", "with", "systems", "local", "high", "performance", "open",
        "source", "model", "cloud", "developer", "python", "backend",
    })

    def _heuristic_item(self, raw: RawItem) -> DigestItem:
        """Keyword-only categorisation. Without the LLM it never claims 'Must Read'."""
        text_tokens = set(re.findall(r"[a-z0-9]+", f"{raw.title} {raw.description} {raw.language}".lower()))
        matches = []
        for interest in settings.USER_INTERESTS:
            distinctive = {
                w for w in re.findall(r"[a-z0-9]+", interest.lower())
                if len(w) >= 3 and w not in self._GENERIC_WORDS
            }
            if distinctive & text_tokens:
                matches.append(interest)
        cat = "Inspiration" if matches else "Skip"
        why = (
            f"Not reviewed by the AI curator. Keyword match: {matches[0].lower()}."
            if matches
            else "Not reviewed by the AI curator and matched none of your interests."
        )
        return DigestItem(
            title=raw.title,
            url=raw.url,
            source=raw.source,
            category=cat,
            summary=raw.description or "Automated tech feed item.",
            why_it_matters=why,
            tags=[m.split()[0].lower() for m in matches[:3]],
        )

    def _heuristic_fallback(self, raw_items: List[RawItem], target_date: str) -> TechDigest:
        """Deterministic rule-based categorization when the LLM is unavailable or offline."""
        items = [self._heuristic_item(raw) for raw in raw_items]
        return TechDigest(
            date=target_date,
            items=self.ranking_backend.rank(items, raw_items),
            total_harvested=len(raw_items),
            total_curated=len([i for i in items if i.category in ("Must Read", "Inspiration")]),
            ranking_backend=self.ranking_backend.metadata.name,
            ranking_version=self.ranking_backend.metadata.version,
        )
