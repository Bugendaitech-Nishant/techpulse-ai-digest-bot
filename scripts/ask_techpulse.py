"""An outside agent: reads a project's dependency files and asks TechPulse over A2A what affects them.

    python scripts/ask_techpulse.py [project_dir] [--url https://techpulse-ai-digest.onrender.com]

Exits 2 when something needs patching, so it can fail a CI step.
"""

import argparse
import asyncio
import json
import re
import sys
import tomllib
import uuid
from pathlib import Path
from typing import List

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_data_parts
from a2a.types import Message, Part, Role, SendMessageRequest

DEFAULT_URL = "https://techpulse-ai-digest.onrender.com"


def read_dependencies(project: Path) -> List[str]:
    """Direct dependency names from requirements*.txt, pyproject.toml and package.json. Lockfiles would add hundreds of transitive names."""
    names: List[str] = []
    for path in project.glob("requirements*.txt"):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if match:
                names.append(match.group(1))
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for spec in data.get("project", {}).get("dependencies", []):
            names.append(re.match(r"[A-Za-z0-9._-]+", spec).group(0))
    package = project / "package.json"
    if package.exists():
        data = json.loads(package.read_text(encoding="utf-8"))
        for group in ("dependencies", "devDependencies"):
            names.extend(data.get(group, {}))
    return list(dict.fromkeys(n.lower() for n in names))


async def ask(url: str, stack: List[str]) -> List[dict]:
    async with httpx.AsyncClient(timeout=90) as http:  # the free host can take a while to wake
        card = await A2ACardResolver(http, url).get_agent_card()
    client = await create_client(card, client_config=ClientConfig(streaming=False))
    message = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()), parts=[Part(text=" ".join(stack))])
    items: List[dict] = []
    try:
        async for event in client.send_message(SendMessageRequest(message=message)):
            if event.HasField("message"):
                for part in get_data_parts(event.message.parts):
                    items.extend(part.get("items", []))
    finally:
        await client.close()
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    stack = read_dependencies(Path(args.project))
    if not stack:
        print("No dependency files found.")
        return 1
    print(f"Asking TechPulse about {len(stack)} dependencies...")
    items = asyncio.run(ask(args.url, stack))
    if not items:
        print("Nothing recent names your dependencies.")
        return 0
    actionable = [i for i in items if i["next_step"] != "Read"]
    for item in actionable:
        action = f"\n    {item['next_step_detail']}" if item.get("next_step_detail") else ""
        print(f"[{item['next_step']}] {item['title']} (matched: {', '.join(item['matched'])})\n    {item['url']}{action}")
    print(f"{len(items) - len(actionable)} more mention your dependencies, nothing to do." if actionable else f"{len(items)} items mention your dependencies, nothing to do.")
    return 2 if any(i["next_step"] == "Patch" for i in items) else 0


if __name__ == "__main__":
    sys.exit(main())
