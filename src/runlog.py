"""
runlog.py: one JSON line per pipeline run (duration, volume, failed sources).

It lives next to the digests so the daily job commits it and the web server, whose disk is
ephemeral, can read it back after a restart.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings


def make_record(
    *, date: str, duration_seconds: float, harvested: int, novel: int, kept: int,
    unreviewed: int, security: int, failed_sources: List[str],
) -> Dict[str, Any]:
    return {
        "date": date,
        "at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration_seconds, 1),
        "harvested": harvested,
        "novel": novel,
        "kept": kept,
        "unreviewed": unreviewed,
        "security": security,
        "failed_sources": sorted(failed_sources),
    }


def append_run(record: Dict[str, Any], path: Optional[Path] = None) -> None:
    path = Path(path or settings.RUNS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def read_runs(limit: int = 14, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The most recent runs, newest first. Corrupt lines are skipped."""
    path = Path(path or settings.RUNS_FILE)
    if not path.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("date"):
            runs.append(record)
    return runs[::-1][:limit]
