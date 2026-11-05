"""Check which configured feeds answer from this machine, and what they hold.

    python scripts/check_feeds.py

Run it where the harvest runs (your laptop, or a CI job) before relying on a feed. Exit code 1 if any fail.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from src.collectors.feeds import OfficialFeedsCollector  # noqa: E402


def main() -> int:
    collector = OfficialFeedsCollector()
    bad = 0
    for feed in settings.FEEDS:
        label, items, why = collector._read(feed)
        if why:
            bad += 1
            print(f"FAIL  {label:<24} {why}")
        else:
            print(f"ok    {label:<24} {len(items)} entries in the last {settings.FEED_MAX_AGE_DAYS} days")
    print(f"\n{len(settings.FEEDS) - bad} of {len(settings.FEEDS)} feeds answered.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
