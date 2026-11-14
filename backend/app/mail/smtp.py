"""SMTP transport (implicit TLS, certificate validation on) and message construction."""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

from app.mail.settings import MailSettings


def build_message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    """A one-way notification. Header values containing line breaks are refused (header injection)."""
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = sender, recipient, subject  # ValueError on CR/LF
    message['Message-ID'] = make_msgid(domain=sender.split('@')[1])
    message['Auto-Submitted'] = 'auto-generated'
    message.set_content(body)
    return message


class SmtpSender:
    def __init__(self, settings: MailSettings):
        self.settings = settings
        self.from_address = settings.mail_from

    async def send(self, message: EmailMessage) -> None:
        await aiosmtplib.send(message, hostname=self.settings.host, port=self.settings.port,
                              username=self.settings.username, password=self.settings.password,
                              use_tls=True, start_tls=False, validate_certs=True, timeout=10)
