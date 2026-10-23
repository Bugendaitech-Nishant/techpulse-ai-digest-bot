import json

from fastapi.testclient import TestClient

import api


def _fixture(path):
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Test item",
                    "url": "https://example.com/item",
                    "source": "test_source",
                    "description": "A test description.",
                    "why_it_matters": "A test rationale.",
                    "relevance": 2,
                    "label_source": "assistant_provisional",
                    "label_notes": "",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_label_review_page_and_fixture_endpoint(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    human = tmp_path / "human.json"
    _fixture(source)
    monkeypatch.setattr(api, "LABEL_FIXTURE", source)
    monkeypatch.setattr(api, "HUMAN_LABEL_FIXTURE", human)

    with TestClient(api.app) as client:
        page = client.get("/label-review")
        data = client.get("/api/label-review")

    assert page.status_code == 200
    assert "Human relevance review" in page.text
    assert data.status_code == 200
    assert data.json()["total"] == 1
    assert data.json()["labelled"] == 0


def test_label_review_persists_human_provenance_atomically(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    human = tmp_path / "human.json"
    _fixture(source)
    monkeypatch.setattr(api, "LABEL_FIXTURE", source)
    monkeypatch.setattr(api, "HUMAN_LABEL_FIXTURE", human)

    with TestClient(api.app) as client:
        response = client.put(
            "/api/label-review/0",
            json={"relevance": 4, "label_notes": "Directly useful."},
        )

    assert response.status_code == 200
    saved = json.loads(human.read_text(encoding="utf-8"))
    assert saved[0]["relevance"] == 4
    assert saved[0]["label_source"] == "human"
    assert saved[0]["label_notes"] == "Directly useful."
    assert not human.with_suffix(".json.tmp").exists()


def test_label_review_rejects_invalid_scores_and_indexes(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    human = tmp_path / "human.json"
    _fixture(source)
    monkeypatch.setattr(api, "LABEL_FIXTURE", source)
    monkeypatch.setattr(api, "HUMAN_LABEL_FIXTURE", human)

    with TestClient(api.app) as client:
        invalid_score = client.put("/api/label-review/0", json={"relevance": 5})
        missing_item = client.put("/api/label-review/4", json={"relevance": 2})

    assert invalid_score.status_code == 422
    assert missing_item.status_code == 404
