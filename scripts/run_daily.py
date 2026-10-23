"""Run the pipeline once, then email the brief. Built for the daily GitHub Actions job.

Exit codes: 0 ok, 1 pipeline crashed, 2 email failed, 3 ran but the result is suspect
(too few items or the AI curator was not used). Non-zero turns the Actions run red.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings
from src import delivery
from src.orchestrator import DigestOrchestrator

logger = logging.getLogger("run_daily")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-email", action="store_true", help="Run the pipeline but do not send mail")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    can_email = delivery.email_configured() and not args.no_email
    if not can_email:
        logger.warning("Email is off (not configured or --no-email); the digest will only be written to disk.")

    try:
        orchestrator = DigestOrchestrator()
        result = orchestrator.run(dry_run=False)
        digest = orchestrator.db.get_digest_by_date(result["date"])
        if digest is None:
            raise RuntimeError(f"Digest for {result['date']} was not stored.")
    except Exception as error:
        logger.exception("Pipeline failed")
        if can_email:
            try:
                delivery.send_email(
                    "[TechPulse failed] The daily run crashed",
                    f"The daily run failed with: {str(error).splitlines()[0][:300]}\n\nCheck the Actions log.",
                )
            except Exception:
                logger.exception("Could not send the failure alert either")
        return 1

    problems = delivery.digest_problems(digest, settings.MIN_KEPT_ITEMS, failed_sources=result.get("failed_sources", []))
    for problem in problems:
        logger.warning(problem)

    if can_email:
        brief = delivery.build_brief(
            digest, top_n=settings.BRIEF_TOP_N, feed_url=settings.PUBLIC_URL, problems=problems,
            rating_counts=orchestrator.db.get_feedback_counts(),
        )
        try:
            delivery.send_email(brief["subject"], brief["text"], brief["html"])
        except Exception:
            logger.exception("Email delivery failed")
            return 2

    return 3 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
