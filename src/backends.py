"""Typed ranking backend contract and the production-safe v1 implementation."""

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Protocol, Sequence

from src.models import DigestItem, RawItem
from src.ranking import RANKING_VERSION, rank_items


@dataclass(frozen=True)
class BackendMetadata:
    """Identifies the backend used to produce ranking decisions."""

    name: str
    version: str


class RankingBackend(Protocol):
    """Interface implemented by deterministic and model-backed rankers."""

    metadata: BackendMetadata

    def rank(
        self,
        items: Sequence[DigestItem],
        raw_items: Sequence[RawItem],
    ) -> list[DigestItem]:
        """Return the input items ranked with validated score fields."""


class DeterministicV1Backend:
    """Stable baseline backend used until a model beats it on labelled data."""

    metadata = BackendMetadata(name="deterministic", version=RANKING_VERSION)

    def rank(
        self,
        items: Sequence[DigestItem],
        raw_items: Sequence[RawItem],
    ) -> list[DigestItem]:
        return rank_items(items, raw_items)


class LayaBackend:
    """Opt-in Laya score adapter; the caller supplies the installed-model predictor."""

    def __init__(
        self,
        predict: Callable[[RawItem], Mapping[str, float]],
        *,
        version: str = "external",
    ):
        self.metadata = BackendMetadata(name="laya", version=version)
        self._predict = predict

    @classmethod
    def from_installed(
        cls,
        *,
        device: str = "cpu",
        version: str = "installed",
    ) -> "LayaBackend":
        """Build a backend from the optional Laya package without eager imports."""
        try:
            from laya import Router
        except ImportError as error:
            raise RuntimeError(
                "Laya backend requested but the optional 'laya' package is not installed."
            ) from error

        router = Router(device=device)
        return cls(cls._router_predictor(router), version=version)

    @staticmethod
    def _router_predictor(router: object) -> Callable[[RawItem], Mapping[str, float]]:
        def predict(raw: RawItem) -> Mapping[str, float]:
            state = {
                "title": raw.title,
                "description": raw.description,
                "source": raw.source,
                "score": raw.score,
                "language": raw.language,
                "published_at": raw.published_at,
            }
            questions = {
                "relevance_score": {
                    "type": "score",
                    "instructions": "How relevant is this item to the configured technical profile?",
                    "criteria": [
                        "not relevant",
                        "slightly relevant",
                        "moderately relevant",
                        "highly relevant",
                        "essentially relevant",
                    ],
                },
                "impact_score": {
                    "type": "score",
                    "instructions": "How significant is the technical impact for engineers?",
                    "criteria": [
                        "negligible impact",
                        "low impact",
                        "moderate impact",
                        "high impact",
                        "exceptional impact",
                    ],
                },
            }
            result = router.predict(state, questions)
            answers = result.get("answers", {})
            scores: dict[str, float] = {}
            for name in ("relevance_score", "impact_score"):
                answer = answers.get(name)
                if not isinstance(answer, Mapping):
                    raise TypeError(f"Laya response missing answer mapping for {name}")
                criteria_count = len(questions[name]["criteria"])
                raw_score = answer.get("score")
                if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
                    raise TypeError(f"Laya response score for {name} must be numeric")
                scores[name] = float(raw_score) / (criteria_count - 1)
                confidence = answer.get("confidence")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    scores["confidence"] = max(scores.get("confidence", 0.0), float(confidence))
            return scores

        return predict

    def rank(
        self,
        items: Sequence[DigestItem],
        raw_items: Sequence[RawItem],
    ) -> list[DigestItem]:
        raw_by_url = {item.url: item for item in raw_items}
        scored: list[DigestItem] = []
        for item in items:
            raw = raw_by_url.get(item.url)
            if raw is None:
                raise ValueError(f"Laya backend received item without raw input: {item.url}")
            scores = self._predict(raw)
            if not isinstance(scores, Mapping):
                raise TypeError("Laya predictor must return a mapping of score names to floats")
            updates = {
                name: self._validated_score(scores, name)
                for name in ("relevance_score", "impact_score", "novelty_score", "confidence")
                if name in scores
            }
            scored.append(item.model_copy(update=updates))
        return rank_items(scored, raw_items)

    @staticmethod
    def _validated_score(scores: Mapping[str, float], name: str) -> float:
        value = scores[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Laya score {name} must be numeric")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"Laya score {name} must be between 0 and 1")
        return float(value)
