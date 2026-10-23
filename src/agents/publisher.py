"""
publisher.py — Agent 3: Formatter & Publisher
Compiles the curated TechDigest into an executive-ready Markdown report,
saves it to digests/YYYY-MM-DD.md, and logs a clean console summary.
Includes Windows cp1252-safe console printing to prevent UnicodeEncodeError.
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict

from src.models import TechDigest, DigestItem
from config.settings import settings

logger = logging.getLogger(__name__)

SOURCE_BADGES: Dict[str, str] = {
    "github_trending": "GitHub Trending",
    "github_search": "GitHub Search",
    "hacker_news": "Hacker News",
    "huggingface_papers": "Hugging Face Papers",
    "devto_articles": "Dev.to Articles",
    "arxiv_ai": "ArXiv AI",
}


class PublisherAgent:
    """Agent responsible for report compilation, Markdown formatting, and file export."""

    def __init__(self, output_dir: Path = settings.DIGESTS_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, digest: TechDigest) -> Path:
        """
        Format the TechDigest and write to digests/YYYY-MM-DD.md.
        Returns the absolute Path of the generated Markdown file.
        """
        logger.info(f"Agent 3 (Publisher): Compiling Markdown digest for {digest.date}")

        markdown_content = self.render_markdown(digest)
        output_file = self.output_dir / f"{digest.date}.md"
        output_file.write_text(markdown_content, encoding="utf-8")

        logger.info(f"Agent 3 (Publisher): Digest saved to {output_file}")
        self._print_safe_summary(digest, output_file)

        return output_file

    def render_markdown(self, digest: TechDigest) -> str:
        """Render complete Markdown document from TechDigest object."""
        must_reads = digest.must_reads
        inspirations = digest.inspirations
        skips = digest.skips

        # Count items per source for badge summary
        source_counts: Dict[str, int] = {}
        for item in must_reads + inspirations:
            s_name = SOURCE_BADGES.get(item.source, item.source)
            source_counts[s_name] = source_counts.get(s_name, 0) + 1

        source_pills = " · ".join([f"**{src}** ({cnt})" for src, cnt in source_counts.items()]) if source_counts else "None"

        lines = [
            f"# TechPulse Daily Digest — {digest.date}",
            "",
            "> **Autonomous Multi-Source Technical Intelligence**",
            "> ",
            f"> **Curated Sources**: {source_pills}",
            f"> ",
            f"> **Pipeline Stats**: {len(must_reads)} Must Read · {len(inspirations)} Inspiration · {len(skips)} Filtered Out (Total Harvested: {digest.total_harvested})",
            f"> **Ranking**: `{digest.ranking_backend}/{digest.ranking_version}` priority scoring",
            "",
            "---",
            "",
        ]

        # Section 1: Must Reads
        if must_reads:
            lines.append("## Must Read")
            lines.append("")
            lines.append("*High-impact updates directly relevant to autonomous agents, LLM architectures, and developer tooling.*")
            lines.append("")
            for idx, item in enumerate(must_reads, 1):
                lines.extend(self._render_item_card(item, idx))
        else:
            lines.append("## Must Read")
            lines.append("")
            lines.append("*No items met the high-signal threshold for Must Read today.*")
            lines.append("")

        # Section 2: Side Project Inspiration
        if inspirations:
            lines.append("## Side Project Inspiration")
            lines.append("")
            lines.append("*Emerging tools, creative implementations, and valuable technical explorations.*")
            lines.append("")
            for idx, item in enumerate(inspirations, 1):
                lines.extend(self._render_item_card(item, idx))

        # Footer
        lines.extend([
            "",
            "---",
            "",
            "## About TechPulse AI Digest Bot",
            "",
            "- **Architecture**: 3-Agent Autonomous Pipeline (Harvester -> Processor -> Publisher)",
            "- **Sources**: GitHub Trending, GitHub Search, Hacker News, Hugging Face Papers, Dev.to, ArXiv AI",
            "- **Curation Model**: Groq Cloud LLM with Pydantic schema validation & 30-day SQLite deduplication",
            f"- **Generated At**: `{digest.generated_at}` UTC",
            "",
            "*Delivering zero-noise technical intelligence daily.*",
        ])

        return "\n".join(lines)

    def _render_item_card(self, item: DigestItem, index: int) -> List[str]:
        """Render a single formatted technical item block."""
        badge = SOURCE_BADGES.get(item.source, item.source)
        tags_str = f" · `{'` `'.join(item.tags)}`" if item.tags else ""

        return [
            f"### {index}. [{item.title}]({item.url})",
            f"**Source**: {badge}{tags_str}",
            f"**Priority**: {item.priority_score:.1f}/100",
            "",
            f"**Summary**: {item.summary}",
            "",
            f"**Why It Matters**: {item.why_it_matters}",
            "",
            "---",
            "",
        ]

    def _print_safe_summary(self, digest: TechDigest, output_file: Path) -> None:
        """Print console summary cleanly avoiding Windows Unicode encoding errors."""
        try:
            summary = (
                f"\n{'=' * 60}\n"
                f"[SUCCESS] TechPulse Digest generated for {digest.date}\n"
                f"Saved to: {output_file}\n"
                f"Must Read:   {len(digest.must_reads)}\n"
                f"Inspiration: {len(digest.inspirations)}\n"
                f"Skipped:     {len(digest.skips)}\n"
                f"{'=' * 60}\n"
            )
            # Use safe stdout write or encoding
            if hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(summary.encode("utf-8", errors="replace"))
                sys.stdout.buffer.flush()
            else:
                print(summary)
        except Exception:
            pass  # Non-fatal telemetry logging
