"""
delivery.py: turn a finished digest into a short email brief and send it over SMTP.

The brief is the product's front door: the top few items, one specific line each, and a
link to the full feed. SMTP keeps this provider-agnostic (Gmail app password, Resend,
Mailgun, SES and similar all speak it) and adds no dependency.
"""

import logging
import smtplib
from email.message import EmailMessage
from html import escape
from typing import Any, Dict, List, Mapping, Sequence

from config.settings import settings

logger = logging.getLogger(__name__)

UNREVIEWED_PREFIX = "Not reviewed"


def pick_top_items(items: Sequence[Mapping[str, Any]], limit: int) -> List[Mapping[str, Any]]:
    """Return the first `limit` non-Skip items. Digest items arrive already ranked."""
    return [i for i in items if i.get("category") != "Skip"][:limit]


def digest_problems(digest: Mapping[str, Any], min_kept: int, max_unreviewed_share: float = 0.5) -> List[str]:
    """Describe anything that makes this run untrustworthy, so it is surfaced instead of hidden."""
    items = digest.get("items") or []
    kept = [i for i in items if i.get("category") != "Skip"]
    problems: List[str] = []
    if len(kept) < min_kept:
        problems.append(f"Only {len(kept)} items were kept (expected at least {min_kept}).")
    if items:
        unreviewed = sum(1 for i in items if str(i.get("why_it_matters", "")).startswith(UNREVIEWED_PREFIX))
        if unreviewed / len(items) > max_unreviewed_share:
            problems.append(
                f"{unreviewed} of {len(items)} items were not reviewed by the AI curator "
                "(missing GROQ_API_KEY or the model failed)."
            )
    return problems


def build_brief(
    digest: Mapping[str, Any],
    *,
    top_n: int,
    feed_url: str = "",
    problems: Sequence[str] = (),
) -> Dict[str, str]:
    """Build subject, plain-text and HTML bodies for the email brief."""
    date = digest.get("date", "")
    top = pick_top_items(digest.get("items") or [], top_n)
    kept_total = len([i for i in (digest.get("items") or []) if i.get("category") != "Skip"])
    subject = f"TechPulse {date}: {len(top)} items worth your time"
    if problems:
        subject = f"[check this run] {subject}"

    text_lines = [f"TechPulse brief for {date}", ""]
    html_rows: List[str] = []
    if problems:
        text_lines += ["Warning:"] + [f"- {p}" for p in problems] + [""]
    for n, item in enumerate(top, 1):
        title, url = str(item.get("title", "")), str(item.get("url", ""))
        why = str(item.get("why_it_matters", "")).strip()
        source = str(item.get("source", ""))
        text_lines += [f"{n}. {title}", f"   {why}", f"   {source}  {url}", ""]
        html_rows.append(
            f'<li style="margin:0 0 16px"><a href="{escape(url, quote=True)}" '
            f'style="font-weight:600;color:#111;text-decoration:none">{escape(title)}</a>'
            f'<br><span style="color:#444">{escape(why)}</span>'
            f'<br><span style="color:#777;font-size:13px">{escape(source)}</span></li>'
        )
    if feed_url:
        text_lines += [f"All {kept_total} curated items: {feed_url}"]

    warning_html = ""
    if problems:
        warning_html = (
            '<div style="border:1px solid #c0392b;padding:8px 12px;margin:0 0 16px;color:#c0392b">'
            + "<br>".join(escape(p) for p in problems)
            + "</div>"
        )
    footer_html = (
        f'<p><a href="{escape(feed_url, quote=True)}">All {kept_total} curated items</a></p>' if feed_url else ""
    )
    html = (
        '<div style="font-family:system-ui,sans-serif;max-width:560px;line-height:1.45;color:#111">'
        f'<h2 style="margin:0 0 16px">TechPulse brief, {escape(str(date))}</h2>'
        f'{warning_html}<ol style="padding-left:20px;margin:0">{"".join(html_rows)}</ol>{footer_html}</div>'
    )
    return {"subject": subject, "text": "\n".join(text_lines), "html": html}


def email_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.EMAIL_TO and settings.EMAIL_FROM)


def send_email(subject: str, text: str, html: str = "") -> None:
    """Send one message to every address in EMAIL_TO. Raises on any SMTP failure."""
    if not email_configured():
        raise RuntimeError("Email is not configured: set SMTP_HOST, EMAIL_FROM and EMAIL_TO.")

    recipients = [a.strip() for a in settings.EMAIL_TO.split(",") if a.strip()]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    port = settings.SMTP_PORT
    if port == 465:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, port, timeout=30)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, port, timeout=30)
    with server:
        if port != 465:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
    logger.info(f"Sent '{subject}' to {len(recipients)} recipient(s).")
