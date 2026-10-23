"""
security_advisories.py: recent security advisories for the tools the reader runs.

Uses the GitHub Advisory Database (no key needed; a token only raises the rate limit).
One query per advisory type asks for advisories that affect the packages named in
`config/profile.toml` under `tools`, so only things that can hurt this reader come back.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from config.settings import settings
from src.collectors.base import BaseCollector
from src.models import RawItem

API_URL = "https://api.github.com/advisories"
# Higher means more urgent; it is used as the item's score so ranking can tell them apart.
SEVERITY_SCORE = {"critical": 100, "high": 70, "moderate": 30}


class SecurityAdvisoryCollector(BaseCollector):
    name = "security_advisories"

    def _fetch_items(self) -> List[RawItem]:
        tools = [t.lower() for t in settings.USER_TOOLS]
        if not tools:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SECURITY_LOOKBACK_DAYS)
        headers = {"Accept": "application/vnd.github+json", "User-Agent": settings.USER_AGENT}
        if settings.GITHUB_API_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_API_TOKEN}"

        items: List[RawItem] = []
        seen_ids = set()
        for advisory_type in ("reviewed", "malware"):
            resp = requests.get(
                API_URL,
                params={
                    "affects": ",".join(tools),
                    "type": advisory_type,
                    "per_page": 30,
                    "sort": "published",
                    "direction": "desc",
                },
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"GitHub advisories returned HTTP {resp.status_code}")
            for advisory in resp.json():
                item = self._to_item(advisory, tools, cutoff)
                if item and item.url not in seen_ids:
                    seen_ids.add(item.url)
                    items.append(item)

        items.sort(key=lambda i: i.score, reverse=True)
        return items[: settings.LIMIT_SECURITY]

    @staticmethod
    def _to_item(advisory: Dict[str, Any], tools: List[str], cutoff: datetime) -> RawItem | None:
        if advisory.get("withdrawn_at"):
            return None
        published = advisory.get("published_at") or ""
        try:
            when = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return None
        if when < cutoff:
            return None

        is_malware = advisory.get("type") == "malware"
        severity = (advisory.get("severity") or "").lower()
        if not is_malware and severity not in SEVERITY_SCORE:
            return None  # low severity is noise in a daily brief

        affected: Dict[str, str] = {}
        for vuln in advisory.get("vulnerabilities") or []:
            package = ((vuln.get("package") or {}).get("name") or "").lower()
            if package in tools:
                affected.setdefault(package, vuln.get("first_patched_version") or "")
        if not affected:
            return None  # the API matched on something other than a package the reader runs

        summary = (advisory.get("summary") or "").strip()
        return RawItem(
            title=f"{advisory['ghsa_id']}: {summary}"[:220],
            url=advisory["html_url"],
            description=(advisory.get("description") or summary)[:600],
            source=SecurityAdvisoryCollector.name,
            score=100 if is_malware else SEVERITY_SCORE[severity],
            language="Security",
            published_at=published,
            extra_metadata={
                "severity": "malware" if is_malware else severity,
                "packages": affected,
                "cve": advisory.get("cve_id"),
                "ghsa": advisory["ghsa_id"],
            },
        )
