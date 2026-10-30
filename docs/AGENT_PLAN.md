# TechPulse agent plan

Goal: TechPulse stops being a one-model summariser. Agents challenge each other's work, look at more than text where it helps, and other people's agents can ask TechPulse questions.

## What the tests showed (2026-10-30, real digest items)

| Test | Result | Decision |
|---|---|---|
| Critic on 16 current entries | Flagged 37 of 105 claims, in 15 of 16 entries. Mostly generic `why_it_matters` filler; some real errors (`mattpocock/skills` described as shell scripts, `expo/skills` as CI/CD) | This is the slop. Build first |
| Planted false claims | 21 of 21 caught, then 3 of 3 by the shipped module | Critic detects invented facts. False flags not measured |
| Critic + reviser loop, 8 items | 1 verified, 6 corrected, 1 left flagged, in 135 s | Works, costs about 17 s per item |
| Vision on 14 real images | 7 decorative, 7 useful (4 screenshots, 2 diagrams, 1 chart). Numbers absent from the page text in 3, none important | Useful as a filter and diagram captions. Not the main value |
| A2A server and client over HTTP (`a2a-sdk` 1.3.0) | Worked on digest data, returned text and a URL part, 59 MB process | Use for the outside door |
| MCP server (`mcp` 2.3.0) | Worked on digest data, 67 MB process | Use for the outside door |
| LangGraph 1.2 stopped by a simulated quota error | Resumed: finished items not repeated, the one in progress was. Adds 32 MB install, 30 MB memory | Adopt, for resuming |
| CrewAI, Pydantic AI, fastembed | Failed to import in my test environments (Windows); runtime not measured | No need shown; not adopted |

Hard limit found: `gpt-oss-120b` has a daily token cap on the free tier (the 429 is cut off at "Limit 200", presumably 200K). More agents means more tokens, so budget decides the design.

## Architecture

```
Collectors -> Writer (gpt-oss-120b) -> Critic (gpt-oss-20b) <-> Reviser (qwen3.8)
                                           |
                       Vision analyst (qwen3.8), top items only
                                           |
                   Scout: checks releases, advisories, the repo
                                           |
                     Digest -> web, email, MCP and A2A server
                                           ^
              Your coding agent: "does anything affect my lockfile?"
```

Agents inside one process call each other directly. The A2A docs position A2A for crossing boundaries between systems, so internal HTTP would add cost and no value. A2A and MCP are the door for outside agents.

## Phases

1. **Critic and reviser. Built, not committed.** `src/agents/critic.py`, a badge on each card, rate limits stop the pass and never the digest.
2. **Agent tools: MCP, then A2A.** Read-only `action_items(stack)`, `search`, `story`. Then a small script reads a lockfile and asks TechPulse. Done when Claude Code can answer "what affects this repo today?" from live data. This is the part that makes it agent to agent, and it uses almost no LLM tokens.
3. **LangGraph orchestration.** Turn the pipeline into a graph with SQLite checkpoints, so a run stopped by quota continues later. Done when killing a real run and restarting repeats no finished item. Checkpoints must survive between GitHub Actions runs.
4. **Scout agent.** For Patch and Must Read items, call real tools (GitHub releases, OSV advisories) and attach what it confirmed. Done when an entry can say "fixed in 2.3.1" with a link it fetched. Probably needs Gemini for quota.
5. **Vision analyst.** Top items only, skip SVG and dynamic chart URLs (the API rejected them), show useful diagrams on the card with a caption, and drop decorative ones.

Each phase is judged by `scripts/eval_curation.py` plus its own "done when", and is dropped if it does not improve them.

## Not doing

- LangChain itself, CrewAI, Google ADK (274 declared dependencies): no problem here they solve.
- Internal A2A: see above.
- Embeddings for now: story grouping works without them.

## Limits of this evidence

Small samples and one day of data. "Corrected" means the critic accepted the rewrite, not that a person checked it. Web search was degraded during research, so most sources are official docs and PyPI, plus one third-party A2A tutorial; Gemini free limits were not confirmed.
