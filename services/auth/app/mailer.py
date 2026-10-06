import logging
from email.message import EmailMessage

import aiosmtplib

from common.errors import ServiceUnavailableError

from app.settings import AuthSettings

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, settings: AuthSettings):
        self._settings = settings

    async def _send(self, recipient: str, subject: str, content: str) -> None:
        settings = self._settings
        if not settings.smtp_host:
            if settings.is_production:
                raise ServiceUnavailableError("Email delivery is not configured")
            logger.warning("Development mode email to %s subject=%s\n%s", recipient, subject, content)
            return

        message = EmailMessage()
        message["From"] = settings.smtp_from or settings.smtp_user
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(content)
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_starttls,
            timeout=15,
        )

    async def send_otp(self, recipient: str, code: str) -> None:
        settings = self._settings
        await self._send(
            recipient,
            "Your Nodeweft sign-in code",
            f"Your sign-in code is {code}. It expires in {settings.otp_ttl_seconds // 60} minutes.\n"
            "If you did not request it, you can ignore this email.",
        )

    async def send_invite(self, recipient: str, invited_by: str) -> None:
        await self._send(
            recipient,
            "You were added to Nodeweft",
            f"You were added to Nodeweft by {invited_by}. "
            "Use your email to sign in and start creating and running your own workflows.\n\n"
            "Website: https://nodeweft.malahim.dev\n",
        )
