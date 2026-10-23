"""
api.py — FastAPI service for TechPulse AI Digest Bot.
Includes production rate limiting (slowapi), global harvest cooldown locks,
hourly budget caps, in-memory response caching, health checks, and sanitized error handling.
"""

import sys
import io
import time
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any

import os
import threading
from html import escape

# Windows console encoding safety (only when running standalone server, not under pytest)
if sys.platform == "win32" and "pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST"):
    try:
        if hasattr(sys.stdout, "buffer") and not getattr(sys.stdout, "closed", False):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "buffer") and not getattr(sys.stderr, "closed", False):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Request, Header, BackgroundTasks, Response
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.orchestrator import DigestOrchestrator
from src.storage.database import DigestDatabase
from src.security.quota_manager import quota_manager
from src.security.cache_manager import cache_manager
from src import feedback as feedback_store
from config.settings import settings

logger = logging.getLogger(__name__)

# ─── Rate Limiter Setup ───────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_READ],
    headers_enabled=False,
)

app = FastAPI(
    title="TechPulse AI Digest Bot API",
    description="REST API and cockpit interface for autonomous tech intelligence curation",
    version=settings.APP_VERSION,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Enable CORS for local and staging access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent / "web"
WEB_DIR.mkdir(exist_ok=True)
LABEL_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "ranking_labels_assistant_expanded.json"
HUMAN_LABEL_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "ranking_labels_human.json"

# Mount static web directory
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

db = DigestDatabase(settings.DB_PATH)
orchestrator = DigestOrchestrator(db=db)
APP_START_TIME = time.time()


def _hydrate_feedback_from_remote() -> None:
    """Load ratings stored on the feedback branch so a freshly started server shows them."""
    try:
        applied = db.load_feedback_events(feedback_store.fetch_remote_events())
        if applied:
            logger.info(f"Loaded {applied} ratings from the feedback branch.")
    except Exception as error:  # never block start-up on this
        logger.warning(f"Feedback hydration failed: {error}")


threading.Thread(target=_hydrate_feedback_from_remote, daemon=True).start()


# ─── Public Web & Health Endpoints ───────────────────────────────────────────

@app.get("/")
def get_dashboard(request: Request):
    """Serve the cockpit web UI."""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not compiled.")
    return FileResponse(index_file)


@app.get("/curated-digests")
def get_curated_digests(request: Request):
    """Serve the Curated Digests Archive web UI."""
    archive_file = WEB_DIR / "curated_digests.html"
    if not archive_file.exists():
        raise HTTPException(status_code=404, detail="Curated Digests UI not compiled.")
    return FileResponse(archive_file)


@app.get("/label-review")
def get_label_review(request: Request):
    """Serve the local human annotation workspace."""
    review_file = WEB_DIR / "label_review.html"
    if not review_file.exists():
        raise HTTPException(status_code=404, detail="Label review UI not available.")
    return FileResponse(review_file)


class LabelUpdate(BaseModel):
    relevance: int = Field(..., ge=0, le=4)
    label_notes: str = Field(default="", max_length=2000)


def _read_label_fixture() -> list[dict[str, Any]]:
    if not LABEL_FIXTURE.exists():
        raise HTTPException(status_code=404, detail="Expanded label fixture not found.")
    try:
        data = json.loads(LABEL_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Could not read label fixture: %s", error)
        raise HTTPException(status_code=500, detail="Label fixture could not be read.") from error
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Label fixture has an invalid format.")
    return data


def _read_human_fixture() -> list[dict[str, Any]]:
    if not HUMAN_LABEL_FIXTURE.exists():
        return _read_label_fixture()
    try:
        data = json.loads(HUMAN_LABEL_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Could not read human label fixture: %s", error)
        raise HTTPException(status_code=500, detail="Human label fixture could not be read.") from error
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="Human label fixture has an invalid format.")
    return data


def _write_human_fixture(items: list[dict[str, Any]]) -> None:
    HUMAN_LABEL_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    temporary = HUMAN_LABEL_FIXTURE.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
        temporary.replace(HUMAN_LABEL_FIXTURE)
    except OSError as error:
        logger.error("Could not persist human label fixture: %s", error)
        raise HTTPException(status_code=500, detail="Label could not be saved.") from error


@app.get("/api/label-review")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_label_review_data(request: Request):
    """Return annotation items and progress for the local review workspace."""
    items = _read_human_fixture()
    labelled = sum(
        isinstance(item.get("relevance"), int)
        and not isinstance(item.get("relevance"), bool)
        and item.get("label_source") == "human"
        for item in items
    )
    return {
        "items": items,
        "total": len(items),
        "labelled": labelled,
        "unlabelled": len(items) - labelled,
    }


@app.put("/api/label-review/{item_index}")
@limiter.limit("120/minute")
def update_label_review(
    item_index: int,
    payload: LabelUpdate,
    request: Request,
):
    """Persist one human label to the separate review fixture."""
    items = _read_human_fixture()
    if item_index < 0 or item_index >= len(items):
        raise HTTPException(status_code=404, detail="Label review item not found.")
    item = dict(items[item_index])
    item["relevance"] = payload.relevance
    item["label_source"] = "human"
    item["label_notes"] = payload.label_notes.strip()
    items[item_index] = item
    _write_human_fixture(items)
    labelled = sum(entry.get("label_source") == "human" for entry in items)
    return {"success": True, "item": item, "labelled": labelled, "total": len(items)}


@app.get("/api/health")
@limiter.limit("120/minute")
def get_health(request: Request) -> Dict[str, Any]:
    """
    Health check endpoint for cloud hosts (Fly.io, Render, Railway, Uptime monitors).
    Returns system status, DB connectivity, quota metrics, and caching telemetry.
    """
    db_connected = False
    db_items = 0
    try:
        stats = db.get_stats()
        db_connected = True
        db_items = stats.get("total_seen_urls", 0)
    except Exception as e:
        logger.error(f"Health check DB probe error: {e}")

    quota_status = quota_manager.get_status()
    cache_stats = cache_manager.get_stats()

    is_healthy = db_connected

    return {
        "status": "healthy" if is_healthy else "degraded",
        "service": "techpulse-ai-digest-bot",
        "version": settings.APP_VERSION,
        "uptime_seconds": round(time.time() - APP_START_TIME, 1),
        "database": {
            "connected": db_connected,
            "type": "sqlite",
            "path": str(settings.DB_PATH.name),
            "total_seen_items": db_items,
        },
        "groq_configured": bool(settings.GROQ_API_KEY),
        "llm_primary_model": settings.GROQ_PRIMARY_MODEL,
        "quota": quota_status,
        "cache": cache_stats,
    }


@app.get("/api/stats")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_stats(request: Request, response: Response) -> Dict[str, Any]:
    """Return database telemetry, rate limiting quota, and model parameters."""
    cache_key = "api:stats"
    cached = cache_manager.get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=60"
        return cached

    stats = db.get_stats()
    stats["llm_model"] = settings.GROQ_PRIMARY_MODEL
    stats["dedup_window_days"] = settings.DEDUP_WINDOW_DAYS
    stats["quota"] = quota_manager.get_status()
    stats["cache"] = cache_manager.get_stats()

    cache_manager.set(cache_key, stats, ttl=60)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=60"
    return stats


@app.get("/api/insights")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_insights(request: Request, response: Response) -> Dict[str, Any]:
    """Return real archive statistics aggregated from the database (sources, funnel, history)."""
    cache_key = "api:insights"
    cached = cache_manager.get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=60"
        return cached

    insights = db.get_insights()
    cache_manager.set(cache_key, insights, ttl=60)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=60"
    return insights


@app.get("/api/digests")
@limiter.limit(settings.RATE_LIMIT_READ)
def list_digests(request: Request, response: Response):
    """Return list of all historical digest dates (cached with short TTL)."""
    cache_key = "api:digests"
    cached = cache_manager.get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=120"
        return cached

    digests = db.list_digests()
    cache_manager.set(cache_key, digests, ttl=120)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=120"
    return digests


@app.get("/api/digest/latest")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_latest_digest(request: Request, response: Response):
    """Return the most recent digest with categorized items (cached with 5-min TTL)."""
    cache_key = "api:digest:latest"
    cached = cache_manager.get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=300"
        return cached

    digest = db.get_latest_digest()
    if not digest:
        raise HTTPException(status_code=404, detail="No digests generated yet.")

    cache_manager.set(cache_key, digest, ttl=300)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=300"
    return digest


@app.get("/api/digest/{target_date}")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_digest_by_date(target_date: str, request: Request, response: Response):
    """Return a digest for a specific YYYY-MM-DD date."""
    cache_key = f"api:digest:{target_date}"
    cached = cache_manager.get(cache_key)
    if cached:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=600"
        return cached

    digest = db.get_digest_by_date(target_date)
    if not digest:
        raise HTTPException(status_code=404, detail=f"No digest found for date {target_date}")

    cache_manager.set(cache_key, digest, ttl=600)
    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=600"
    return digest


@app.get("/api/digest/{target_date}/markdown")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_digest_markdown(target_date: str, request: Request):
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


# ─── Reader Feedback (thumbs up / down) ──────────────────────────────────────

class FeedbackIn(BaseModel):
    url: str = Field(..., max_length=2000)
    rating: int = Field(..., ge=-1, le=1)  # 1 useful, -1 not useful, 0 clear


class SignedFeedbackIn(BaseModel):
    u: str = Field(..., min_length=64, max_length=64)  # sha256 of the item URL
    r: str = Field(..., pattern="^(up|down)$")
    sig: str = Field(..., max_length=64)


def _store_rating(item: Dict[str, Any], rating: int) -> Dict[str, Any]:
    """Save one rating locally, in the durable log and, when configured, on GitHub."""
    current = db.get_feedback_map().get(item["url"], 0)
    if current == rating:
        return {"ok": True, "rating": rating, "persisted": feedback_store.github_sync_enabled(), "changed": False}
    event = feedback_store.make_event(
        item["url"], rating, item["title"], item["source"], item.get("summary", ""), item.get("category", "")
    )
    db.record_feedback(event)
    feedback_store.append_event(event)
    persisted = feedback_store.push_event(event)
    return {"ok": True, "rating": rating, "persisted": persisted, "changed": True}


@app.get("/api/feedback")
@limiter.limit(settings.RATE_LIMIT_READ)
def get_feedback(request: Request) -> Dict[str, Any]:
    """Current ratings per URL, totals, and whether ratings survive a server restart."""
    return {
        "ratings": db.get_feedback_map(),
        "counts": db.get_feedback_counts(),
        "persistent": feedback_store.github_sync_enabled(),
        "write_requires_key": bool(quota_manager.api_key),
    }


@app.post("/api/feedback")
@limiter.limit("60/minute")
def post_feedback(
    request: Request,
    payload: FeedbackIn,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Rate an item. Needs the API key when one is configured, so strangers cannot skew the ratings."""
    if not quota_manager.check_auth(x_api_key):
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized: invalid or missing X-API-Key."})
    item = db.find_item_by_hash(db.hash_url(payload.url))
    if item is None:
        raise HTTPException(status_code=404, detail="That item is not in any digest.")
    return _store_rating(item, payload.rating)


@app.post("/api/feedback/signed")
@limiter.limit("30/minute")
def post_signed_feedback(request: Request, payload: SignedFeedbackIn):
    """Apply a rating from a signed email link (confirmed on the page, so link scanners cannot vote)."""
    if not feedback_store.verify(payload.u, payload.r, payload.sig):
        raise HTTPException(status_code=403, detail="This link is not valid.")
    item = db.find_item_by_hash(payload.u)
    if item is None:
        raise HTTPException(status_code=404, detail="That item is not in any digest.")
    return _store_rating(item, feedback_store.RATINGS[payload.r])


@app.get("/feedback", response_class=HTMLResponse)
@limiter.limit("60/minute")
def feedback_confirm_page(request: Request, u: str = "", r: str = "", sig: str = ""):
    """One-click landing page from the email: shows the item and asks to confirm the rating."""
    if not feedback_store.verify(u, r, sig):
        return HTMLResponse("<p>This link is not valid.</p>", status_code=403)
    item = db.find_item_by_hash(u)
    if item is None:
        return HTMLResponse("<p>That item is no longer in the archive.</p>", status_code=404)
    verdict = "Useful" if r == "up" else "Not useful"
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Rate this item</title>
<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;line-height:1.5}}
button{{font:inherit;padding:.6rem 1.2rem;border-radius:6px;border:1px solid #333;background:#f5b942;cursor:pointer}}
button:disabled{{opacity:.6;cursor:default}}</style></head><body>
<h1>Mark as: {escape(verdict)}</h1><p>{escape(item["title"])}</p>
<button id="go" type="button">Confirm</button><p id="msg" role="status"></p>
<script>
document.getElementById('go').addEventListener('click', async (e) => {{
  e.target.disabled = true;
  const res = await fetch('/api/feedback/signed', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{u: {u!r}, r: {r!r}, sig: {sig!r}}})}});
  document.getElementById('msg').textContent = res.ok ? 'Saved. This improves tomorrow's brief.' : 'Could not save this rating.';
}});
</script></body></html>"""
    return HTMLResponse(body)


# ─── Harvest Pipeline Execution (Governed by Rate Limits & Quotas) ────────────

def _execute_harvest_job():
    """Worker function for executing harvest pipeline in background or synchronously."""
    try:
        orchestrator.run(dry_run=False)
        cache_manager.invalidate()
        quota_manager.finish_harvest(success=True)
        logger.info("Harvest job successfully finalized.")
    except Exception as e:
        quota_manager.finish_harvest(success=False)
        logger.error(f"Harvest pipeline execution failed: {e}", exc_info=True)


@app.post("/api/harvest")
@limiter.limit(settings.RATE_LIMIT_HARVEST)
def trigger_harvest(
    request: Request,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    background: bool = False,
):
    """
    Trigger a multi-source harvest and AI curation cycle.
    Protected by:
    1. slowapi per-IP rate limit (settings.RATE_LIMIT_HARVEST)
    2. Concurrency lock (prevents overlapping parallel runs)
    3. Mandatory cooldown (HARVEST_COOLDOWN_SECONDS)
    4. Hourly budget cap (MAX_HARVESTS_PER_HOUR)
    5. Optional API Key authentication (HARVEST_API_KEY)
    """
    allowed, message, status_code, telemetry = quota_manager.check_harvest_allowed(x_api_key)
    if not allowed:
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": message,
                "quota": telemetry,
            },
        )

    # Acquire lock and mark start
    quota_manager.start_harvest()

    if background:
        # Schedule as asynchronous background task
        background_tasks.add_task(_execute_harvest_job)
        return JSONResponse(
            status_code=202,
            content={
                "success": True,
                "status": "accepted",
                "message": "Harvest pipeline initiated in background. Poll /api/health or /api/digest/latest for completion.",
                "quota": quota_manager.get_status(),
            },
        )

    # Synchronous execution
    try:
        result = orchestrator.run(dry_run=False)
        cache_manager.invalidate()  # Purge stale caches
        quota_manager.finish_harvest(success=True)
        fresh_digest = db.get_latest_digest()

        return {
            "success": True,
            "execution": result,
            "digest": fresh_digest,
            "quota": quota_manager.get_status(),
        }
    except Exception as e:
        quota_manager.finish_harvest(success=False)
        logger.error(f"Synchronous harvest pipeline failed: {e}", exc_info=True)
        # Sanitize error detail to prevent internal path leaks
        safe_msg = str(e).split("\n")[0][:250]
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Harvest execution failed: {safe_msg}",
                "quota": quota_manager.get_status(),
            },
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
