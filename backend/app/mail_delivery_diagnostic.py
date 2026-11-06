"""Temporary authenticated diagnosis and one-recipient delivery test. Remove after use."""
import asyncio
import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.parser import BytesParser
from email.utils import getaddresses
from email.utils import format_datetime, make_msgid
import hashlib
from importlib.metadata import version
import ipaddress
import json
import os
from pathlib import Path
import platform
import secrets
import urllib.request

import aiosmtplib
import dkim
import dns.asyncresolver
import dns.reversename
import dns.rdata
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
RUN_ID = "mail-delivery-20261106-v2"
TOKEN_HASH = "bd0b7718ad1d9ff69ffff96afb5b0f0bf46381528f03748141aa3fc240620999"
RECIPIENT_HASH = "286345b98040b3dee1b367e0b9e9d9c9689c92c67296f977912e719a1b4b458a"
SENDER = "diagnostic@demo.morrono.com"
DOMAIN = "demo.morrono.com"
SELECTOR = "codex20261106"
EXPIRES = datetime(2026, 11, 6, 14, 10, tzinfo=timezone.utc)
STATE_DIR = Path("/tmp")
_probe_task = None
_send_tasks = {}
UNSIGNED_REJECTION = {"status": "rejected", "smtp_code": 550,
                      "checked_at": "2026-11-06T12:13:53.490271+00:00",
                      "smtp_message": "5.7.26 SPF and DKIM did not pass; observed by previous deployment; local-signing-v3"}


def authorize(request):
    if datetime.now(timezone.utc) >= EXPIRES:
        raise HTTPException(410, "Temporary diagnostic expired")
    candidate = hashlib.sha256(request.headers.get("x-mail-probe-key", "").encode()).hexdigest()
    if not secrets.compare_digest(candidate, TOKEN_HASH):
        raise HTTPException(404, "Not found")


def error_detail(exc):
    result = {"error": type(exc).__name__}
    if isinstance(exc, aiosmtplib.errors.SMTPResponseException):
        result.update(smtp_code=exc.code, smtp_message=str(exc.message))
    else:
        result["message"] = str(exc)[:1500]
    return result


def response_detail(response):
    return {"code": response.code, "message": response.message}


async def dns_lookup(name, kind):
    try:
        answer = await dns.asyncresolver.resolve(name, kind, lifetime=5)
        return {"name": str(name), "type": kind, "records": [str(item) for item in answer]}
    except Exception as exc:
        return {"name": str(name), "type": kind, **error_detail(exc)}


async def close_client(client):
    if client.is_connected:
        try:
            await asyncio.wait_for(client.quit(), timeout=2)
        except Exception:
            client.close()


async def connection_probe(host):
    result = {"host": host, "port": 25, "stage": "greeting", "email_sent": False}
    client = aiosmtplib.SMTP(hostname=host, port=25, timeout=6,
                             start_tls=False, local_hostname=DOMAIN)
    try:
        result["greeting"] = response_detail(await client.connect())
        result["stage"] = "ehlo"
        result["ehlo"] = response_detail(await client.ehlo())
        result["stage"] = "completed_without_sending"
    except Exception as exc:
        result.update(error_detail(exc))
    finally:
        await close_client(client)
    return result


async def diagnose():
    report = {"probe_id": RUN_ID, "checked_at": datetime.now(timezone.utc).isoformat(),
              "system": platform.system(), "python": platform.python_version(),
              "packages": {name: version(name) for name in ("dnspython", "aiosmtplib", "dkimpy")}}
    report["dns"] = await asyncio.gather(
        dns_lookup(DOMAIN, "A"), dns_lookup(DOMAIN, "TXT"),
        dns_lookup("morrono.com", "TXT"), dns_lookup("_dmarc."+DOMAIN, "TXT"),
        dns_lookup(SELECTOR+"._domainkey."+DOMAIN, "TXT"),
    )
    try:
        def get_http_egress():
            with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=6) as response:
                return json.load(response)["ip"]
        source_ip = await asyncio.to_thread(get_http_egress)
        ipaddress.ip_address(source_ip)
        report["http_egress_ip"] = source_ip
        report["http_egress_ptr"] = await dns_lookup(dns.reversename.from_address(source_ip), "PTR")
        report["egress_note"] = "HTTP egress IP; compare with SMTP error text before assuming the same SMTP source IP."
    except Exception as exc:
        report["egress_lookup"] = error_detail(exc)
    try:
        mx = await dns.asyncresolver.resolve("naver.com", "MX", lifetime=5)
        hosts = [str(item.exchange).rstrip(".") for item in sorted(mx, key=lambda item: item.preference)]
        report["naver_mx"] = hosts
        report["naver_checks"] = []
        # Two hosts maximum, sequentially, without sending a recipient or email.
        for host in hosts[:2]:
            if report["naver_checks"]:
                await asyncio.sleep(3)
            report["naver_checks"].append(await connection_probe(host))
    except Exception as exc:
        report["naver_error"] = error_detail(exc)
    return report


def result_path(mode):
    return STATE_DIR / (RUN_ID+"-"+mode+".json")


def read_result(mode):
    path = result_path(mode)
    return json.loads(path.read_text()) if path.exists() else None


async def published_dkim_keys():
    name = SELECTOR+"._domainkey."+DOMAIN
    try:
        records = await dns.asyncresolver.resolve(name, "TXT", lifetime=5)
        return [b"".join(record.strings) for record in records], "deployment_resolver"
    except Exception:
        # Newly added records can be hidden by a local resolver's negative cache.
        def public_lookup():
            with urllib.request.urlopen("https://dns.google/resolve?name="+name+"&type=TXT", timeout=8) as response:
                answer = json.load(response)
            values = []
            for item in answer.get("Answer", []):
                if item.get("type") == 16 and item.get("name", "").rstrip(".").lower() == name.lower():
                    text = item["data"]
                    values.append(b"".join(dns.rdata.from_text("IN", "TXT", text).strings)
                                  if text.startswith('"') else text.encode())
            return values
        return await asyncio.to_thread(public_lookup), "google_dns_over_https"


async def delivery_attempt(recipient, mode, signed_message_b64):
    previous = read_result("unsigned") or UNSIGNED_REJECTION
    if mode == "dkim" and (not previous or previous["status"] != "rejected"):
        raise HTTPException(409, "DKIM retry requires a confirmed rejection of the unsigned attempt")
    message = EmailMessage(policy=SMTP_POLICY)
    message["From"] = "Claim Web delivery test <"+SENDER+">"
    message["To"] = recipient
    message["Subject"] = "클레임웹 메일 발신 테스트 / "+mode
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain=DOMAIN)
    message.set_content("사용자 요청으로 배포 서버에서 보낸 메일 발신 테스트입니다.\n"
                        "이 메일은 테스트용 한 건이며 회신이나 링크 접속은 필요하지 않습니다.\n"
                        "Test reference: "+RUN_ID+" / "+mode+"\n", cte="quoted-printable")
    raw = message.as_bytes()
    signed = False
    if mode == "dkim":
        try:
            # The private key stays on the user's PC. Only signed message bytes arrive here.
            if len(signed_message_b64) > 30000:
                raise ValueError("Test message is too large")
            raw = base64.b64decode(signed_message_b64, validate=True)
            parsed = BytesParser(policy=SMTP_POLICY).parsebytes(raw)
            if ([address for _, address in getaddresses(parsed.get_all("From", []))] != [SENDER]
                or [address for _, address in getaddresses(parsed.get_all("To", []))] != [recipient]
                or parsed.get_all("Cc") or parsed.get_all("Bcc")):
                raise ValueError("Only the approved sender and recipient are allowed")
            message = parsed
            txt_values, dns_source = await published_dkim_keys()
            if not any(dkim.verify(raw, dnsfunc=lambda name, timeout=5, value=value: value) for value in txt_values):
                raise ValueError("Published DKIM DNS key does not verify this signature")
            signed = True
        except Exception:
            raise HTTPException(409, "An approved message with a valid DKIM signature matching the published DNS key is required") from None
    try:
        fd = os.open(str(STATE_DIR/(RUN_ID+"-"+mode+".started")), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise HTTPException(409, "This test attempt has already started; do not resend") from None
    report = {"probe_id": RUN_ID, "mode": mode, "sender": SENDER,
              "message_id": str(message["Message-ID"]), "dkim_signed": signed,
              "checked_at": datetime.now(timezone.utc).isoformat(), "stage": "dns",
              "status": "not_submitted", "smtp_accepted": False, "inbox_delivery_confirmed": False,
              "responses": {}}
    if signed:
        report["dkim_dns_verification_source"] = dns_source
    client = None
    try:
        mx = await dns.asyncresolver.resolve("gmail.com", "MX", lifetime=5)
        host = str(min(mx, key=lambda item: item.preference).exchange).rstrip(".")
        report["mx_host"] = host
        client = aiosmtplib.SMTP(hostname=host, port=25, timeout=10,
                                 start_tls=False, local_hostname=DOMAIN)
        report["stage"] = "greeting"
        report["responses"]["greeting"] = response_detail(await client.connect())
        report["stage"] = "ehlo"
        report["responses"]["ehlo"] = response_detail(await client.ehlo())
        report["stage"] = "starttls"
        if not client.supports_extension("starttls"):
            raise RuntimeError("Server did not advertise STARTTLS; stopped before transmitting recipient")
        report["responses"]["starttls"] = response_detail(await client.starttls())
        report["tls_verified"] = True
        await client.ehlo()
        report["stage"] = "mail_from"
        report["responses"]["mail_from"] = response_detail(await client.mail(SENDER))
        report["stage"] = "rcpt_to"
        report["responses"]["rcpt_to"] = response_detail(await client.rcpt(recipient))
        report["stage"] = "data"
        report["responses"]["data"] = response_detail(await client.data(raw, timeout=20))
        report.update(status="accepted_by_smtp", smtp_accepted=True, stage="completed")
    except Exception as exc:
        report.update(error_detail(exc))
        if isinstance(exc, aiosmtplib.errors.SMTPResponseException):
            report["status"] = "rejected"
        else:
            report["status"] = "delivery_unknown" if report["stage"] == "data" else "not_submitted"
    finally:
        if client is not None:
            await close_client(client)
        path = result_path(mode)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, path)
    return report


@router.get("/api/diagnostics/mail-delivery", include_in_schema=False)
async def get_diagnostic(request: Request):
    authorize(request)
    global _probe_task
    if _probe_task is None:
        _probe_task = asyncio.create_task(diagnose())
    return {"diagnostic": await asyncio.shield(_probe_task),
            "unsigned": read_result("unsigned") or UNSIGNED_REJECTION, "dkim": read_result("dkim")}


@router.post("/api/diagnostics/mail-delivery", include_in_schema=False)
async def post_diagnostic(request: Request):
    authorize(request)
    body = await request.json()
    if "private_key" in body:
        raise HTTPException(400, "Do not send private keys to this server")
    recipient = body.get("recipient", "")
    if not isinstance(recipient, str) or not secrets.compare_digest(hashlib.sha256(recipient.encode()).hexdigest(), RECIPIENT_HASH):
        raise HTTPException(400, "Only the user-authorized recipient is allowed")
    mode = body.get("mode", "unsigned")
    if mode not in ("unsigned", "dkim"):
        raise HTTPException(400, "Unsupported test mode")
    existing = read_result(mode)
    if existing:
        return existing
    if mode not in _send_tasks:
        _send_tasks[mode] = asyncio.create_task(delivery_attempt(recipient, mode, body.get("signed_message_b64", "")))
    try:
        return await asyncio.shield(_send_tasks[mode])
    except HTTPException:
        # A failed preflight transmitted no SMTP message and may be corrected safely.
        if not (STATE_DIR/(RUN_ID+"-"+mode+".started")).exists():
            _send_tasks.pop(mode, None)
        raise
