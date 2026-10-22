"""
api.py — FastAPI service for TechPulse AI Digest Bot.
Serves the web dashboard, exposes REST APIs for digest querying,
database telemetry, and on-demand live harvesting.
"""

import sys
import io
from pathlib import Path
from typing import Optional, Dict, Any

# Windows console encoding safety
if sys.platform == "win32":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.orchestrator import DigestOrchestrator
from src.storage.database import DigestDatabase
from config.settings import settings

app = FastAPI(
    title="TechPulse AI Digest Bot API",
    description="REST API and cockpit interface for autonomous tech intelligence curation",
    version="2.0.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent / "web"
WEB_DIR.mkdir(exist_ok=True)

# Mount static web directory
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

db = DigestDatabase(settings.DB_PATH)
orchestrator = DigestOrchestrator(db=db)


@app.get("/")
def get_dashboard():
    """Serve the cockpit web UI."""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not compiled.")
    return FileResponse(index_file)


@app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    """Return database telemetry and tracking metrics."""
    stats = db.get_stats()
    stats["llm_model"] = settings.GROQ_PRIMARY_MODEL
    stats["dedup_window_days"] = settings.DEDUP_WINDOW_DAYS
    return stats


@app.get("/api/digests")
def list_digests():
    """Return list of all historical digest dates."""
    return db.list_digests()


@app.get("/api/digest/latest")
def get_latest_digest():
    """Return the most recent digest with categorized items."""
    digest = db.get_latest_digest()
    if not digest:
        raise HTTPException(status_code=404, detail="No digests generated yet.")
    return digest


@app.get("/api/digest/{target_date}")
def get_digest_by_date(target_date: str):
    """Return a digest for a specific YYYY-MM-DD date."""
    digest = db.get_digest_by_date(target_date)
    if not digest:
        raise HTTPException(status_code=404, detail=f"No digest found for date {target_date}")
    return digest


@app.get("/api/digest/{target_date}/markdown")
def get_digest_markdown(target_date: str):
    """Return raw markdown content for a given date's digest."""
    md_file = settings.DIGESTS_DIR / f"{target_date}.md"
    if md_file.exists():
        content = md_file.read_text(encoding="utf-8", errors="replace")
    else:
        digest = db.get_digest_by_date(target_date)
        if not digest:
            raise HTTPException(status_code=404, detail=f"No digest found for date {target_date}")
        from src.agents.publisher import PublisherAgent
        from src.models import TechDigest, DigestItem
        items = [DigestItem(**item) for item in digest.get("items", [])]
        d = TechDigest(
            date=target_date,
            items=items,
            total_harvested=digest.get("total_harvested", len(items)),
            total_curated=digest.get("total_curated", len(items)),
        )
        content = PublisherAgent()._render_markdown(d)
    return {"date": target_date, "markdown": content}


@app.post("/api/harvest")
def trigger_harvest():
    """Trigger an on-demand multi-source harvest and curation cycle."""
    try:
        result = orchestrator.run(dry_run=False)
        fresh_digest = db.get_latest_digest()
        return {
            "success": result["success"],
            "execution": result,
            "digest": fresh_digest,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Harvest pipeline failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
