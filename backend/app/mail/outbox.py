"""Notifications are queued in the same transaction as the change they describe and sent after it commits.

A kind is queued once per request. A crash or a transport error is recorded as 'failed' with a fixed code (never the
transport's text, which can hold addresses or credentials) and is NOT retried automatically: a timeout can mean the mail
was delivered, so a repeat could send it twice.
"""
from __future__ import annotations

import asyncio
import logging

import psycopg
from email_validator import EmailNotValidError, validate_email

from app.auth.deps import database_url
from app.mail.smtp import build_message
from app.mail.templates import render

logger = logging.getLogger(__name__)
BATCH = 20
STUCK_AFTER = '10 minutes'


def _address(login_id: str) -> str | None:
    try:
        return validate_email(login_id, check_deliverability=False, allow_smtputf8=False).ascii_email
    except EmailNotValidError:
        return None


def enqueue(connection, number: int, kind: str) -> None:
    """Queue one mail to whoever filed the request, if their login is an e-mail address."""
    row = connection.execute('SELECT u.login_id FROM service_request r JOIN app_user u ON u.id=r.created_by WHERE r.id=%s',
                             (number,)).fetchone()
    if row is None:
        return
    address = _address(row[0])
    connection.execute(
        """INSERT INTO service_mail(request_id,kind,recipient,status,error_code) VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (request_id,kind) DO NOTHING""",
        (number, kind, address, 'pending' if address else 'skipped', None if address else 'no_address'))


def dispatch(sender, url: str | None = None) -> None:
    """Send what is pending. Safe to run concurrently: a row is claimed by one dispatcher only."""
    url = url or database_url()
    with psycopg.connect(url, connect_timeout=5) as connection:
        connection.execute(
            f"UPDATE service_mail SET status='failed', error_code='interrupted' "
            f"WHERE status='sending' AND claimed_at < now() - interval '{STUCK_AFTER}'")
        claimed = connection.execute(
            """UPDATE service_mail SET status='sending', claimed_at=now(), attempts=attempts+1
               WHERE id IN (SELECT id FROM service_mail WHERE status='pending' ORDER BY id
                            FOR UPDATE SKIP LOCKED LIMIT %s)
               RETURNING id, request_id, kind, recipient""", (BATCH,)).fetchall()
    for mail_id, number, kind, recipient in claimed:
        outcome = _send(sender, url, number, kind, recipient)
        with psycopg.connect(url, connect_timeout=5) as connection:
            connection.execute(
                "UPDATE service_mail SET status=%s, error_code=%s, sent_at=CASE WHEN %s='sent' THEN now() END WHERE id=%s",
                ('sent' if outcome is None else 'failed', outcome, 'sent' if outcome is None else 'failed', mail_id))


def _send(sender, url: str, number: int, kind: str, recipient: str) -> str | None:
    """None on success, otherwise a fixed error code."""
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            row = connection.execute(
                "SELECT equipment_snapshot->>'machine', reason, resolution->>'note' FROM service_request WHERE id=%s",
                (number,)).fetchone()
        subject, body = render(kind, {'number': number, 'machine': row[0], 'reason': row[1], 'note': row[2] or ''})
        message = build_message(sender.from_address, recipient, subject, body)
        asyncio.run(sender.send(message))
    except Exception as error:  # noqa: BLE001 - recorded as a code only
        logger.warning('mail %s for request %s failed: %s', kind, number, type(error).__name__)
        return 'send_failed'
    return None
