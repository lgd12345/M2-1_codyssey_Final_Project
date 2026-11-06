"""Temporary deployment probe: fixed destinations, no email transmission or secrets."""
import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
import platform

from fastapi import APIRouter, HTTPException

router = APIRouter()
_probe_task = None
_EXPIRES = datetime(2026, 11, 6, 12, 50, tzinfo=timezone.utc)


async def _smtp_probe(host, port):
    import aiosmtplib

    client = aiosmtplib.SMTP(
        hostname=host, port=port, timeout=4,
        start_tls=False, local_hostname="diagnostic.invalid",
    )
    result = {"host": host, "port": port, "connected": False}
    try:
        greeting = await client.connect()
        result.update(connected=True, greeting_code=greeting.code)
        ehlo = await client.ehlo()
        result["ehlo_code"] = ehlo.code
        result["starttls_offered"] = client.supports_extension("starttls")
        if result["starttls_offered"]:
            try:
                await client.starttls()
                result["tls_verified"] = True
            except Exception as exc:
                result["tls_verified"] = False
                result["tls_error"] = type(exc).__name__
        # Deliberately do not use AUTH, MAIL FROM, RCPT TO, DATA, or send().
    except Exception as exc:
        result["error"] = type(exc).__name__
        if isinstance(exc, aiosmtplib.errors.SMTPResponseException):
            result["smtp_code"] = exc.code
    finally:
        if client.is_connected:
            try:
                await asyncio.wait_for(client.quit(), timeout=2)
            except Exception:
                client.close()
    return result


async def _recipient_domain(domain):
    import dns.asyncresolver

    result = {"recipient_domain": domain, "mx_lookup": False}
    try:
        records = await dns.asyncresolver.resolve(domain, "MX", lifetime=4)
        hosts = [str(record.exchange).rstrip(".")
                 for record in sorted(records, key=lambda record: record.preference)]
        result.update(mx_lookup=True, mx_hosts=hosts)
        result["smtp"] = await _smtp_probe(hosts[0], 25)
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


async def run_probe():
    result = {
        "probe_id": "mail-egress-20261106-v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": _EXPIRES.isoformat(),
        "python": platform.python_version(),
        "system": platform.system(),
        "email_sent": False,
        "packages": {},
    }
    for distribution, module_name in (
        ("dnspython", "dns.asyncresolver"),
        ("aiosmtplib", "aiosmtplib"),
        ("dkimpy", "dkim"),
    ):
        try:
            __import__(module_name)
            result["packages"][distribution] = {"version": version(distribution), "imported": True}
        except Exception as exc:
            result["packages"][distribution] = {"imported": False, "error": type(exc).__name__}
    if not all(package["imported"] for package in result["packages"].values()):
        return result
    checks = await asyncio.gather(
        _recipient_domain("gmail.com"),
        _recipient_domain("naver.com"),
        _smtp_probe("smtp.gmail.com", 587),
    )
    result["direct_delivery_checks"] = checks[:2]
    result["submission_connection_control"] = checks[2]
    result["note"] = "Connection and TLS checks only; sender DNS, reputation and inbox delivery are not tested."
    return result


@router.get("/api/diagnostics/mail-egress", include_in_schema=False)
async def mail_egress():
    global _probe_task
    if datetime.now(timezone.utc) >= _EXPIRES:
        raise HTTPException(status_code=410, detail="Temporary diagnostic expired")
    # One probe per process; repeated public requests reuse the same task/result.
    if _probe_task is None:
        _probe_task = asyncio.create_task(run_probe())
    return await asyncio.shield(_probe_task)
