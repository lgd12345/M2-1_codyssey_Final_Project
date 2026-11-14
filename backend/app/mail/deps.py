"""The mail transport as a FastAPI dependency: tests and the E2E server replace it, so nothing real is reachable."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from app.mail.settings import MailConfigError, MailSettings
from app.mail.smtp import SmtpSender

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _sender() -> SmtpSender | None:
    try:
        settings = MailSettings.from_env(os.environ)
    except MailConfigError as error:
        logger.warning('mail notifications are off: %s', error)
        return None
    return SmtpSender(settings) if settings else None


def get_mail_sender() -> SmtpSender | None:
    return _sender()
