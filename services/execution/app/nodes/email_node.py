import logging
import re
from email.message import EmailMessage

import aiosmtplib

from app.engine.context import RunContext
from app.engine.errors import NodeError
from app.nodes.util import render_for_item
from app.settings import split_csv

logger = logging.getLogger(__name__)

RECIPIENT = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def effective_allowed_domains(server_domains: list[str], node_domains: list[str]) -> set[str]:
    node_set = {domain.strip().lower() for domain in node_domains if domain.strip()}
    server_set = set(server_domains)
    if server_set and node_set:
        return server_set & node_set
    return server_set or node_set


def validate_recipient(recipient: str, allowed_domains: set[str]) -> str:
    text = recipient.strip()
    if "\r" in text or "\n" in text or not RECIPIENT.match(text):
        raise NodeError("Recipient is not a valid email address")
    domain = text.rsplit("@", 1)[1].lower()
    if allowed_domains and domain not in allowed_domains:
        raise NodeError(f"Recipient domain '{domain}' is not allowed")
    return text


async def email_send(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    config = node["config"]
    settings = ctx.settings
    allowed = effective_allowed_domains(split_csv(settings.email_allowed_domains), config.get("allowed_domains", []))
    if not settings.smtp_host and settings.is_production:
        raise NodeError("Email delivery is not configured on this server")

    results = []
    for item in items:
        if ctx.emails_sent >= settings.max_emails_per_run:
            raise NodeError(f"Email limit of {settings.max_emails_per_run} per run reached")
        context = ctx.template_context(item)
        recipient = validate_recipient(str(render_for_item(config["to"], context)), allowed)
        subject = str(render_for_item(config["subject"], context)).replace("\r", " ").replace("\n", " ").strip()
        body = str(render_for_item(config["body"], context))
        if not subject:
            raise NodeError("Email subject resolved to an empty value")

        if settings.smtp_host:
            message = EmailMessage()
            message["From"] = settings.smtp_from or settings.smtp_user
            message["To"] = recipient
            message["Subject"] = subject[:300]
            message.set_content(body[:20000])
            try:
                await aiosmtplib.send(
                    message,
                    hostname=settings.smtp_host,
                    port=settings.smtp_port,
                    username=settings.smtp_user or None,
                    password=settings.smtp_password or None,
                    start_tls=settings.smtp_starttls,
                    timeout=20,
                )
            except Exception:
                logger.exception("SMTP send failed")
                raise NodeError("Could not send the email") from None
            status = "sent"
        else:
            logger.info("Development mode, email to %s with subject %s not sent", recipient, subject)
            status = "logged"

        ctx.emails_sent += 1
        results.append({**item, "email": {"to": recipient, "status": status}})
    return results
