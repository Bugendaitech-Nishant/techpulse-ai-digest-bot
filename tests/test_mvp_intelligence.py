"""Article text, fixed topics, typed next steps and story grouping."""

import json

from config.settings import settings
from src.agents.processor import ProcessorAgent
from src.agents.publisher import PublisherAgent
from src.extraction import enrich_with_text, needs_text
from src.models import TOPICS, DigestItem, RawItem, TechDigest, normalize_tag
from src.orchestrator import DigestOrchestrator
from src.stories import find_story_groups, story_id_for
from src.storage.database import DigestDatabase


def _raw(url, description="", source="hacker_news"):
    return RawItem(title="Some title", url=url, source=source, description=description)


def test_only_thin_items_with_an_article_are_fetched():
    assert needs_text(_raw("https://blog.example.com/p", "HN discussion (12 points, 3 comments) by x"))
    assert needs_text(_raw("https://blog.example.com/p", "short"))
    assert not needs_text(_raw("https://blog.example.com/p", "long " * 60))
    assert not needs_text(_raw("https://news.ycombinator.com/item?id=1", "HN discussion (1 points)"))
    assert not needs_text(_raw("https://github.com/a/b", "short", source="github_trending"))
    assert not needs_text(_raw("https://arxiv.org/abs/1", "short", source="arxiv_ai"))


def test_enrichment_replaces_the_stub_and_survives_a_failed_fetch():
    good, blocked = _raw("https://a.example.com/1", "HN discussion (5 points)"), _raw("https://b.example.com/2", "HN discussion (5 points)")
    article = "The article body explains the change in detail. " * 6
    done = enrich_with_text([good, blocked], fetch=lambda url: article if "a.example" in url else "")
    assert done == 1
    assert good.description == article
    assert blocked.description.startswith("HN discussion")  # kept, not blanked


def test_tags_are_normalised_and_topics_limited_to_the_fixed_list():
    assert normalize_tag("AI agents") == normalize_tag("#ai-agents") == normalize_tag("AI_Agents") == "ai-agents"
    agent = ProcessorAgent(api_key=None)
    raw = RawItem(title="Thing", url="https://x.dev/1", source="hacker_news")
    reply = json.dumps({"items": [{
        "url": raw.url, "category": "Must Read", "relevance": 4, "impact": 3, "summary": "s", "why_it_matters": "w",
        "tags": ["LiteLLM", "litellm", "AI agents"], "topics": ["security", "made-up-topic", "agents"],
        "next_step": "Patch", "next_step_detail": "pip install -U litellm",
    }]})
    item = agent._parse_and_validate(reply, [raw])[0]
    assert item.tags == ["litellm", "ai-agents"]
    assert item.topics == ["security", "agents"] and set(item.topics) <= set(TOPICS)
    assert (item.next_step, item.next_step_detail) == ("Patch", "pip install -U litellm")


def test_skip_is_always_ignore_and_unknown_steps_fall_back_to_read():
    assert ProcessorAgent._next_step("Try", "Skip") == "Ignore"
    assert ProcessorAgent._next_step("Ignore", "Must Read") == "Read"
    assert ProcessorAgent._next_step("Banana", "Inspiration") == "Read"
    assert ProcessorAgent._next_step("Evaluate", "Must Read") == "Evaluate"


def test_the_prompt_lists_the_topics_and_still_formats():
    prompt = ProcessorAgent(api_key=None)._build_system_prompt()
    assert "vulnerabilities" in prompt and "next_step" in prompt


def _item(n):
    return DigestItem(title=f"Item {n}", url=f"https://x.dev/{n}", source="hacker_news", category="Must Read",
                      summary="s", why_it_matters="w")


def test_story_groups_ignore_unknown_ids_and_bad_replies():
    today = [_item(1), _item(2)]
    recent = [{"title": "Old", "url": "https://x.dev/0", "date": "2026-10-24"}]
    groups = find_story_groups(today, recent, lambda p: json.dumps({"groups": [["t0", "r0"], ["t1", "zzz"], ["t0", "t1"]]}))
    assert groups == [["https://x.dev/1", "https://x.dev/0"]]  # single-member and already-claimed groups dropped
    assert find_story_groups(today, recent, lambda p: "not json") == []
    assert story_id_for(["https://x.dev/b", "https://x.dev/a"]) == story_id_for(["https://x.dev/a", "https://x.dev/b"])


def test_story_ids_reach_old_items_the_database_and_a_rebuilt_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIGESTS_DIR", tmp_path)
    publisher = PublisherAgent(output_dir=tmp_path)
    db = DigestDatabase(tmp_path / "t.db", auto_hydrate=False)
    yesterday = TechDigest(date="2026-10-29", items=[_item(0)], total_harvested=1)
    publisher.publish(yesterday)
    db.record_digest(yesterday)

    processor = ProcessorAgent(api_key="x")
    processor.ask_json = lambda prompt: json.dumps({"groups": [["t0", "r0"]]})
    orchestrator = DigestOrchestrator(db=db, harvester=object(), processor=processor, publisher=publisher)

    today = orchestrator.assign_stories(TechDigest(date="2026-10-30", items=[_item(1)], total_harvested=1))
    sid = today.items[0].story_id
    assert sid and sid == story_id_for(["https://x.dev/0", "https://x.dev/1"])
    assert [i["url"] for i in db.get_story(sid)] == ["https://x.dev/0"]  # old member stamped in the database

    publisher.publish(today)
    rebuilt = DigestDatabase(tmp_path / "rebuilt.db")  # as Render does on a cold start
    assert {i["url"] for i in rebuilt.get_story(sid)} == {"https://x.dev/0", "https://x.dev/1"}
