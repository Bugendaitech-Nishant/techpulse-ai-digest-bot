# TechPulse: from side project to a tool you rely on

Goal: a digest that reaches you without effort, ranks what matters to you personally, and
says why in one specific line. Everything below was measured on this repo, not assumed.

## 1. What the tests showed (2026-10-23)

| Finding | Evidence | Status |
| --- | --- | --- |
| The model path silently dropped items | 108 items in, 51 out; the 2026-10-21 digest kept 1 of 94 | **Fixed**: batches of 12, a coverage check, a retry for missing items. Now 108 of 108 |
| Only the first 40 harvested items were ever sent to the model | `raw_items[:40]` in `processor.py`; a harvest is up to about 110 | **Fixed**: round-robin across sources, capped at 90 |
| The keyword fallback labelled 79% of items "Must Read" | "and", "ai", "in" matched everything; precision 0.36 against a 0.33 base rate | **Fixed**: generic words ignored, and the fallback never claims Must Read |
| Evaluation leaked the answer | `_load_fixture` set category from the label, so v1 looked perfect (P@5 1.0) | **Fixed** earlier. Honest v1 NDCG@5 is 0.22 |
| The dashboard showed invented numbers | Reach, delivery health, open rate, Slack factor were hard-coded | **Fixed**: real figures from `/api/insights` |
| A harvest request would time out on a hosted server | 90 items took 292 s | **Fixed**: the UI now uses background mode and polls |
| Nothing reaches the user | No email, Slack or RSS code anywhere; pull-only web page | **Open** (Phase 1) |
| It does not learn | One hard-coded generic profile; the 108 labels are not used by the product | **Open** (Phase 2) |
| Tests can call the live model | `test_pipeline` uses `api_key=None`, which falls back to the `.env` key | **Open**, small |

Quality after the fixes, on the 108 labels (101 are my proxy labels, so treat as indicative):

| Ranker | Must Read precision | NDCG@10 | NDCG over all 108 |
| --- | --- | --- | --- |
| Keyword fallback, before | 0.36 | n/a | n/a |
| v1 deterministic, no category | n/a | 0.21 | 0.67 |
| Laya typed-decisions (local CPU) | n/a | 0.49 | 0.76 |
| **LLM curation after the fixes** | **0.67** (base rate 0.33) | **0.63** | **0.84** |

Decision: keep Groq `gpt-oss-120b` as the curator. Laya is slower on CPU and scored lower; drop Jev (paid API).

## 2. Plan

### Phase 1: make it arrive (built 2026-10-23, needs your secrets to go live)
The single biggest gap. A digest nobody opens is not helpful.
1. **Schedule the harvest.** A daily GitHub Actions workflow already existed, but its `GROQ_API_KEY` secret was empty, so every scheduled run used the keyword fallback (this is why the live site showed boilerplate). The workflow now fails loudly without the key, runs `scripts/run_daily.py`, and commits `digests/YYYY-MM-DD.md`; the web app rebuilds its database from those files.
2. **Push it.** Email over SMTP (any provider): the top 7 items, one specific line each, a link to the full feed (`src/delivery.py`).
3. **Reliability.** Exit code 3 and a `[check this run]` subject when fewer than 5 items are kept or most were unreviewed; a crash sends its own alert email.
4. **Cost and time budget.** A real run curated 80 of 80 items in 202 s. Groq's free tier allows 8,000 tokens per minute, and one batch hit that limit and recovered on retry. Parallel batches would worsen it; keep batches serial.

Done when: seven days in a row, a digest lands without you touching anything.

### Phase 2: make it yours (built 2026-10-23; needs one GitHub token to persist ratings from the site)
1. **Thumbs up/down on every item** (site rows, the reading pane, and signed links in the email), stored in a `feedback` table and an append-only log on the `feedback` branch. Built.
2. **Use the feedback.** Your 8 most recent useful and not-useful items go into the curation prompt as examples. Built. Research on few-shot preference methods (FSPO, arXiv 2502.19312) supports adapting to one user from a handful of examples.
3. **A real profile file**, `config/profile.toml` (summary, interests, things to push down, tools you run). Built; edit it freely. Your own ratings show what it should contain: security incidents in tools you run score 4, infrastructure that changes your stack scores 3, niche research scores 2, general news scores 0.
4. **Regression gate.** `evaluate_ranking.py` against your human labels runs in CI; a change that drops NDCG@10 below a floor fails. **Not built yet.**

Done when: week-over-week thumbs-up rate on the top 10 rises, and the label gate is green.

### Phase 3: make it actionable (about 2 weeks)
1. **Merge duplicates** across sources (the same release on HN, a blog and GitHub becomes one entry).
2. **Security feed**: NVD and package advisories matched against a list of tools you use, shown first.
3. **Weekly "what changed"** summary built from the stored digests.
4. **Full-text summaries** for the top items only, to keep cost down and make "why it matters" concrete.

### Phase 4: measure what counts
| Metric | Target | Source |
| --- | --- | --- |
| Thumbs-up rate, top 10 | above 60% and rising | feedback table |
| Click-through from the brief | tracked, no target until a baseline exists | email or link redirect |
| Must Read precision against labels | at least 0.65 | label gate |
| Items dropped silently | 0 | coverage log |
| Cost and time per digest | under 3 minutes, under a set budget | run log |

## 3. Decisions needed from you
1. **Who is it for?** Just you, or other people? Others need accounts, per-user profiles and unsubscribe handling.
2. **Which channel first?** Email, Slack or Discord, RSS.
3. **Hosting:** GitHub Actions plus a static or free web host (cheapest, recommended), or keep Render and add a paid disk.
4. **Budget** for model calls per day.

## 4. Not verified
Free-tier limits for Resend and Render, and GitHub Actions cron reliability, were not checked in this session; confirm them before committing to a channel. All quality numbers rest on 108 items, 101 of which are my proxy labels. Rate the 20 or so items where you disagree most, and re-run the comparison.
