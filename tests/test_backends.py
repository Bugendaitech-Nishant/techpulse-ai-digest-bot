import pytest

from src.backends import BackendMetadata, DeterministicV1Backend, LayaBackend, RankingBackend
from src.models import DigestItem, RawItem


def _item(title: str, url: str) -> DigestItem:
    return DigestItem(
        title=title,
        url=url,
        source="github_trending",
        category="Must Read",
        summary=title,
        why_it_matters="Relevant.",
    )


def test_deterministic_backend_has_explicit_metadata_and_ranks():
    backend = DeterministicV1Backend()
    raw = [
        RawItem(title="AA", url="https://x/a", source="github_trending", score=1),
        RawItem(title="BB", url="https://x/b", source="github_trending", score=2),
    ]

    ranked = backend.rank([_item("AA", raw[0].url), _item("BB", raw[1].url)], raw)

    assert backend.metadata == BackendMetadata(name="deterministic", version="v1")
    assert [item.rank for item in ranked] == [1, 2]


def test_backend_contract_accepts_model_like_implementation():
    class FakeBackend:
        metadata = BackendMetadata(name="fake", version="test")

        def rank(self, items, raw_items):
            return list(reversed(items))

    backend: RankingBackend = FakeBackend()
    items = [_item("A", "https://x/a"), _item("B", "https://x/b")]

    assert [item.title for item in backend.rank(items, [])] == ["B", "A"]


def test_laya_backend_maps_typed_scores_without_importing_laya():
    raw = [
        RawItem(title="AA", url="https://x/a", source="github_trending", score=1),
        RawItem(title="BB", url="https://x/b", source="github_trending", score=2),
    ]
    scores = {
        "https://x/a": {"relevance_score": 0.2, "impact_score": 0.2, "confidence": 0.8},
        "https://x/b": {"relevance_score": 0.9, "impact_score": 0.9, "confidence": 0.9},
    }
    backend = LayaBackend(lambda item: scores[item.url], version="test")

    result = backend.rank([_item("AA", raw[0].url), _item("BB", raw[1].url)], raw)

    assert backend.metadata == BackendMetadata(name="laya", version="test")
    assert result[0].url == "https://x/b"
    assert result[0].relevance_score == 0.9


def test_laya_backend_rejects_invalid_scores():
    raw = [RawItem(title="AA", url="https://x/a", source="github_trending")]
    backend = LayaBackend(lambda item: {"relevance_score": 1.1})

    with pytest.raises(ValueError, match="between 0 and 1"):
        backend.rank([_item("AA", raw[0].url)], raw)


def test_laya_router_scores_are_normalized_from_criterion_indices():
    class FakeRouter:
        def predict(self, state, questions):
            assert state["description"] == "AA"
            assert len(questions["relevance_score"]["criteria"]) == 5
            return {
                "answers": {
                    "relevance_score": {"score": 4, "confidence": 0.8},
                    "impact_score": {"score": 2, "confidence": 0.6},
                }
            }

    backend = LayaBackend(LayaBackend._router_predictor(FakeRouter()), version="test")
    raw = [RawItem(title="AA", url="https://x/a", source="test", description="AA")]

    result = backend.rank([_item("AA", raw[0].url)], raw)

    assert result[0].relevance_score == 1.0
    assert result[0].impact_score == 0.5
    assert result[0].confidence == 0.8
