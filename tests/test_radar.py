"""The radar decides what a team sees first. These tests pin down what counts as 'touches our stack'."""

import pytest

from src import radar

STACK = radar.Stack(["fastapi", "postgresql", "python", "go"], {"postgresql": ["postgres"]}, {"python"})


def _item(title, *, category="Must Read", step="Read", detail="", source="hacker_news", topics=(), score=50, summary="", tags=()):
    return {"title": title, "url": f"https://x.test/{title}", "source": source, "category": category, "summary": summary,
            "next_step": step, "next_step_detail": detail, "topics": list(topics), "tags": list(tags), "priority_score": score}


def _tier(item):
    return radar.annotate([item], STACK)[0]["tier"]


@pytest.mark.parametrize("text,expected", [
    ("Google ships a new model", []),            # "go" is not inside "google"
    ("Why we moved to Go", ["go"]),
    ("Tuning postgres autovacuum", ["postgresql"]),  # alias
    ("FastAPI-users 12 released", []),           # a different package
    ("fastapi 0.162 released", ["fastapi"]),
])
def test_matching_is_by_whole_word_and_honours_aliases(text, expected):
    assert STACK.hits({"title": text}) == expected


def test_stack_item_with_an_action_is_an_alert_and_without_one_is_news():
    assert _tier(_item("FastAPI 0.162 fixes a bug", step="Patch")) == "alert"
    assert _tier(_item("Postgres internals book", step="Read")) == "stack"


def test_security_advisories_are_alerts_even_when_the_text_names_no_tool():
    assert _tier(_item("GHSA-1234 something", source="security_advisories")) == "alert"
    assert _tier(_item("A fastapi CVE write-up", topics=["security"])) == "alert"


def test_a_broad_tool_alone_never_promotes_an_item_but_still_shows_in_the_strip():
    item = radar.annotate([_item("A Python trick", summary="python python")], STACK)
    assert item[0]["tier"] == "major" and item[0]["stack_hits"] == [] and item[0]["broad_hits"] == ["python"]
    assert {s["name"]: s["hits"] for s in radar.stack_strip(item, STACK)}["python"] == 1


def test_the_briefing_is_capped_and_keeps_the_best_majors():
    majors = [_item(f"Read {n}", score=n) for n in range(20)]
    out = radar.annotate(majors, STACK)
    featured = [i for i in out if i["tier"] == "major"]
    assert len(featured) == radar.MAJOR_SIZE
    assert [i["priority_score"] for i in featured] == sorted((i["priority_score"] for i in featured), reverse=True)
    assert max(i["priority_score"] for i in featured) == 19
    assert sum(i["tier"] == "more" for i in out) == 20 - radar.MAJOR_SIZE


def test_alerts_are_never_cut_to_make_room():
    alerts = [_item(f"FastAPI bug {n}", step="Patch") for n in range(12)]
    out = radar.annotate(alerts + [_item("A good read")], STACK)
    assert sum(i["tier"] == "alert" for i in out) == 12
    assert sum(i["tier"] == "major" for i in out) == 1  # at most what exists, never fewer than MIN_PICKS allows


def test_boilerplate_actions_are_not_work():
    generic = _item("Cool repo", step="Try", detail="Clone the repo and run the example script.")
    out = radar.annotate([generic], STACK)[0]
    assert out["action"] == "" and out["actionable"] is False
    specific = _item("FastAPI fix", step="Patch", detail="Upgrade to 0.162.0 and rerun the suite.")
    out = radar.annotate([specific], STACK)[0]
    assert out["actionable"] is True and out["action"].startswith("Upgrade")


def test_skips_are_filtered_and_order_is_alert_stack_major_more_filtered():
    items = [_item("skip", category="Skip", step="Ignore"), _item("Plain read", category="Inspiration"),
             _item("A good read"), _item("Postgres news"), _item("FastAPI bug", step="Patch")]
    assert [i["tier"] for i in radar.annotate(items, STACK)] == ["alert", "stack", "major", "more", "filtered"]
    assert radar.headline(radar.annotate(items, STACK)) == {"alerts": 1, "stack": 1, "major": 1, "more": 1, "filtered": 1}


@pytest.mark.parametrize("topics,source,expected", [
    (["agents", "inference"], "hacker_news", ["GenAI & ML"]),
    (["kubernetes", "security"], "devto_articles", ["Cloud & DevOps", "Security"]),
    (["developer-tools"], "github_trending", ["General"]),
    ([], "hacker_news", ["General"]),
    (["web"], "devto_articles", ["Frontend & mobile"]),
    ([], "security_advisories", ["Security"]),
])
def test_items_land_in_the_areas_their_topics_name(topics, source, expected):
    assert radar.areas_of({"topics": topics, "source": source}) == expected


def test_kind_comes_from_the_source():
    assert [radar.kind_of({"source": s}) for s in ("github_trending", "arxiv_ai", "hacker_news", "security_advisories", "unknown")] == \
        ["tool", "paper", "article", "advisory", "article"]


def test_a_team_with_no_watchlist_still_gets_majors_and_areas():
    none = radar.Stack([])
    items = [_item(f"Update {n}", score=n, topics=["cloud"]) for n in range(8)]
    out = radar.annotate(items, none)
    assert radar.headline(out) == {"alerts": 0, "stack": 0, "major": radar.MAJOR_SIZE, "more": 3, "filtered": 0}
    assert radar.area_strip(out) == [{"name": "Cloud & DevOps", "count": 8}]
