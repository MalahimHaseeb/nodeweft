import logging
from email.message import EmailMessage

import aiosmtplib

from common.errors import ServiceUnavailableError

from app.settings import AuthSettings

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, settings: AuthSettings):
        self._settings = settings

    async def send_otp(self, recipient: str, code: str) -> None:
        settings = self._settings
        if not settings.smtp_host:
            if settings.is_production:
                raise ServiceUnavailableError("Email delivery is not configured")
            logger.warning("Development mode: OTP for %s is %s", recipient, code)
            return

        message = EmailMessage()
        message["From"] = settings.smtp_from or settings.smtp_user
        message["To"] = recipient
        message["Subject"] = "Your Nodeweft sign-in code"
        message.set_content(
            f"Your sign-in code is {code}. It expires in {settings.otp_ttl_seconds // 60} minutes.\n"
            "If you did not request it, you can ignore this email."
        )
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_starttls,
            timeout=15,
        )
