"""Tests for the LLM curation contract: coverage, source balance and honest fallbacks."""

import json
from types import SimpleNamespace

from config.settings import settings
from src.agents.processor import ProcessorAgent
from src.models import RawItem


def _raw(n: int, source: str = "arxiv_ai", score: int = 0, description: str = "") -> RawItem:
    return RawItem(title=f"Item {n}", url=f"https://example.com/{source}/{n}", source=source, score=score, description=description)


class FakeClient:
    """Chat-completions stub that answers only the first `answer_first` items of every request."""

    def __init__(self, answer_first: int | None = None, fail: bool = False):
        self.calls = 0
        self._answer_first = answer_first
        self._fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        if self._fail:
            raise RuntimeError("model down")
        payload = json.loads(kwargs["messages"][1]["content"].split("\n\n", 1)[1])
        answered = payload if self._answer_first is None else payload[: self._answer_first]
        items = [
            {"title": p["title"], "url": p["url"], "source": p["source"], "category": "Must Read",
             "relevance": 4, "impact": 2, "summary": "s", "why_it_matters": "specific reason", "tags": ["t"]}
            for p in answered
        ]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"items": items})))])


def _agent(client) -> ProcessorAgent:
    agent = ProcessorAgent(api_key="test-key")
    agent.client = client
    return agent


def test_every_item_is_covered_even_when_the_model_omits_some(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BATCH_SIZE", 4)
    raw = [_raw(i) for i in range(10)]
    digest = _agent(FakeClient(answer_first=2)).process(raw, "2026-10-23")
    assert {i.url for i in digest.items} == {r.url for r in raw}
    # Items the model never answered are labelled as unreviewed, not passed off as curated.
    assert any(i.why_it_matters.startswith("Not reviewed") for i in digest.items)


def test_model_scores_are_scaled_into_item_fields(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BATCH_SIZE", 10)
    digest = _agent(FakeClient()).process([_raw(1)], "2026-10-23")
    assert digest.items[0].relevance_score == 1.0
    assert digest.items[0].impact_score == 0.5


def test_selection_is_capped_and_balanced_across_sources(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_ITEMS", 6)
    raw = [_raw(i, "hacker_news", score=100 - i) for i in range(20)] + [_raw(i, "arxiv_ai", score=i) for i in range(20)]
    selected = ProcessorAgent._select_for_curation(raw)
    assert len(selected) == 6
    assert {r.source for r in selected} == {"hacker_news", "arxiv_ai"}
    assert sum(r.source == "arxiv_ai" for r in selected) == 3


def test_keyword_fallback_never_claims_must_read(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")  # a local .env key must not turn this into a live call
    agent = ProcessorAgent(api_key=None)
    raw = [
        _raw(1, description="A multi-agent framework for AI agents and local LLMs"),
        _raw(2, description="A celebrity gossip roundup"),
    ]
    digest = agent.process(raw, "2026-10-23")
    cats = {i.url: i.category for i in digest.items}
    assert cats[raw[0].url] == "Inspiration"
    assert cats[raw[1].url] == "Skip"
    assert not digest.must_reads


def test_total_llm_failure_falls_back_instead_of_raising():
    digest = _agent(FakeClient(fail=True)).process([_raw(1, description="AI agents")], "2026-10-23")
    assert len(digest.items) == 1
