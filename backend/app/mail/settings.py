"""Mail configuration. Mail is off unless the Gmail account is fully configured; a half-written or malformed value is an
error that names the variable, never its value (the app password is a secret)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from email_validator import EmailNotValidError, validate_email

APP_PASSWORD = re.compile(r'[A-Za-z0-9]{16}')


class MailConfigError(ValueError):
    pass


def _address(value: str, name: str) -> str:
    try:
        return validate_email(value, check_deliverability=False, allow_smtputf8=False).ascii_email.casefold()
    except EmailNotValidError:
        raise MailConfigError(f'{name} must be an e-mail address') from None


@dataclass(frozen=True)
class MailSettings:
    username: str
    password: str = field(repr=False)
    mail_from: str
    host: str = 'smtp.gmail.com'
    port: int = 465

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> 'MailSettings | None':
        username = env.get('SMTP_USERNAME', '').strip()
        password = env.get('SMTP_PASSWORD', '')
        if not username and not password.strip():
            return None
        if not username or not password.strip():
            raise MailConfigError('SMTP_USERNAME and SMTP_PASSWORD must be set together')
        username = _address(username, 'SMTP_USERNAME')
        password = password.replace(' ', '')  # Google shows app passwords in groups of four
        if not APP_PASSWORD.fullmatch(password):
            raise MailConfigError('SMTP_PASSWORD must be a 16-character Google app password')
        mail_from = env.get('MAIL_FROM', '').strip()
        if mail_from and _address(mail_from, 'MAIL_FROM') != username:
            raise MailConfigError('MAIL_FROM must be the authenticated account')  # no unverified aliases
        try:
            port = int(env.get('SMTP_PORT', '').strip() or 465)
        except ValueError:
            raise MailConfigError('SMTP_PORT must be a number') from None
        if not 1 <= port <= 65535:
            raise MailConfigError('SMTP_PORT must be a port number')
        return cls(username, password, username, env.get('SMTP_HOST', '').strip() or 'smtp.gmail.com', port)
