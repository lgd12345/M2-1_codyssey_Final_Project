from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from uuid import UUID, uuid4

from email_validator import EmailNotValidError, validate_email

from app.auth.service import AuthError, MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH


class AccessError(AuthError):
    def __init__(self, code='ACCESS_INVALID', message='요청을 확인해 주세요.', status=400):
        self.code, self.status_code = code, status
        super().__init__(message)


def unavailable():
    return AccessError('ACCESS_UNAVAILABLE', '인증 서비스를 준비 중입니다. 잠시 후 다시 확인해 주세요.', 503)


def invalid_code():
    return AccessError('ACCESS_CODE_INVALID', '인증번호가 올바르지 않거나 만료되었습니다.', 400)


def already_registered():
    return AccessError('REGISTRATION_EXISTS', '이미 가입된 계정입니다. 기존 계정으로 로그인해 주세요.', 409)


def email_address(value):
    try:
        # Email ownership is checked by a code, not a synchronous DNS lookup.
        return validate_email(value.strip(), check_deliverability=False,
                              allow_smtputf8=False).ascii_email.casefold()
    except (EmailNotValidError, AttributeError):
        raise AccessError(message='올바른 이메일 주소를 입력해 주세요.') from None


def company_code(value):
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,23}', value):
        raise AccessError(message='회사코드는 3~24자의 영문·숫자·하이픈으로 입력해 주세요.')
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    secret: str = field(repr=False)
    smtp_password: str = field(repr=False)
    mail_from: str
    policy: dict
    registration: bool
    smtp_host: str = 'smtp.resend.com'
    smtp_port: int = 465

    @classmethod
    def load(cls, env):
        if env.get('CUSTOMER_ACCESS_ENABLED') != '1':
            return None
        # Activation needs separate operational approval; defaults stay closed.
        if env.get('CUSTOMER_ACCESS_RELEASE_APPROVED') != '1' or env.get('APP_COOKIE_SECURE') != '1':
            return None
        try:
            db = env['DATABASE_URL'].strip()
            secret = env['CUSTOMER_ACCESS_SECRET']
            password = env['CUSTOMER_SMTP_PASSWORD']
            if not db or len(secret) < 32 or not password:
                return None
            policy = json.loads(Path(env['CUSTOMER_ACCESS_POLICY_FILE']).read_text(encoding='utf-8'))
            keys = ('version', 'purpose', 'items', 'retention', 'recipients', 'contact', 'refusal')
            if not isinstance(policy, dict) or any(not isinstance(policy.get(k), str) or not policy[k].strip() for k in keys):
                return None
            policy = {key: policy[key].strip() for key in keys}
            if len(policy['version']) > 120:
                return None
            sender = email_address(env['CUSTOMER_MAIL_FROM'])
            # Registration is initially supported only on the same explicit DSN.
            # A different auth DB must not lead to a partial two-DB account write.
            auth_db = (env.get('RAG_DATABASE_URL', '') or db).strip()
            registration = env.get('CUSTOMER_REGISTRATION_ENABLED') == '1' and auth_db == db
            return cls(db, secret, password, sender, policy, registration)
        except (KeyError, ValueError, OSError, AccessError):
            return None


@dataclass
class Challenge:
    id: UUID
    purpose: str
    proof_hash: str
    code_hash: str
    contact_id: UUID | None
    client_key: str
    email_key: str
    policy_version: str
    created_at: datetime
    expires_at: datetime
    attempts: int = 0
    state: str = 'pending'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AccessService:
    def __init__(self, settings, repository):
        self.settings, self.repository = settings, repository

    def keyed(self, value):
        return hmac.new(self.settings.secret.encode(), value.encode(), hashlib.sha256).hexdigest()

    def code_hash(self, challenge, code):
        return self.keyed(f'code|{challenge.id}|{challenge.purpose}|{challenge.contact_id}|{code}')

    def policy_check(self, version, consent):
        if consent is not True or version != self.settings.policy['version']:
            raise AccessError('ACCESS_CONSENT_REQUIRED', '현재 개인정보 안내를 확인하고 동의해 주세요.')

    def start(self, purpose, code, email, client, version, consent):
        self.policy_check(version, consent)
        if purpose not in ('register', 'guest') or (purpose == 'register' and not self.settings.registration):
            raise unavailable()
        company, email = company_code(code), email_address(email)
        proof, number = secrets.token_urlsafe(32), f'{secrets.randbelow(1000000):06d}'
        with self.repository.transaction() as work:
            now = work.now()
            registered_company = work.company_exists(company)
            client_key = self.keyed('client|' + client)
            # A typo must not impose the email resend cooldown on a corrected
            # company. All attempts still share the client's durable quota.
            email_key = self.keyed(('email|' if registered_company else 'invalid-company-email|') + email)
            work.throttle(client_key, email_key, now)
            contact = work.contact(company, email) if registered_company else None
            challenge = Challenge(uuid4(), purpose, digest(proof), '', contact['id'] if contact else None,
                                  client_key, email_key, version, now, now + timedelta(minutes=10))
            challenge.code_hash = self.code_hash(challenge, number)
            if not contact:
                challenge.state = 'dummy'
            work.add_challenge(challenge)
        # Commit rejected company attempts too, so validation cannot bypass the
        # durable issuance limit. A rejected company never reaches the mailer.
        if not registered_company:
            raise AccessError('COMPANY_NOT_FOUND', '등록되지 않은 회사코드입니다. 회사코드를 확인해 주세요.')
        if not contact:
            raise AccessError('COMPANY_EMAIL_MISMATCH', '회사에 등록된 이메일과 일치하지 않습니다. 이메일을 확인해 주세요.')
        return f'{challenge.id}.{proof}', challenge.id, contact['email'], number

    def sent(self, identity, success):
        with self.repository.transaction() as work:
            work.delivery(identity, success)

    def _authorized(self, work, cookie, purpose, number, *, count_success=True):
        try:
            identity, proof = cookie.split('.', 1)
            identity = UUID(identity)
            if len(proof) > 100:
                return None
        except (ValueError, AttributeError):
            return None
        c = work.challenge(identity)
        if (not c or c.purpose != purpose or c.state != 'sent' or c.contact_id is None
                or c.policy_version != self.settings.policy['version'] or c.expires_at <= work.now()
                or c.attempts >= 5 or not hmac.compare_digest(c.proof_hash, digest(proof))):
            return None
        if not re.fullmatch(r'[0-9]{6}', number) or not hmac.compare_digest(c.code_hash, self.code_hash(c, number)):
            work.attempt(c.id, c.attempts + 1)
            return None
        if not work.active_contact(c.contact_id):
            return None
        if count_success:
            work.attempt(c.id, c.attempts + 1)
        return c

    def verify_registration(self, cookie, number, version, consent):
        self.policy_check(version, consent)
        if not self.settings.registration:
            raise unavailable()
        result = None
        with self.repository.transaction() as work:
            challenge = self._authorized(work, cookie, 'register', number, count_success=False)
            if challenge is not None:
                existing = work.registration_exists(challenge.contact_id)
                result = {'state': 'already_registered' if existing else 'verified'}
                if existing:
                    work.consume(challenge.id)
                else:
                    result['email'] = work.contact_email(challenge.contact_id)
        if result is None:
            raise invalid_code()
        return result

    def register(self, cookie, number, password, version, consent):
        self.policy_check(version, consent)
        if not self.settings.registration:
            raise unavailable()
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise AccessError(message='비밀번호는 12~256자로 입력해 주세요.')
        error = None
        with self.repository.transaction() as work:
            challenge = self._authorized(work, cookie, 'register', number)
            if challenge is None:
                error = invalid_code()
            else:
                try:
                    work.register_customer(challenge.contact_id, password, version)
                except AuthError as exc:
                    error = exc
                else:
                    work.consume(challenge.id)
        # Raise after the transaction so wrong-code attempt counters are committed.
        if error:
            raise error
        return {'state': 'registered', 'message': '고객 회원가입이 완료되었습니다. 로그인해 주세요.'}

    def guest(self, cookie, number, version, consent):
        self.policy_check(version, consent)
        token = secrets.token_urlsafe(32)
        error = None
        with self.repository.transaction() as work:
            challenge = self._authorized(work, cookie, 'guest', number)
            if challenge is None:
                error = invalid_code()
            else:
                work.add_guest(digest(token), challenge.contact_id, work.now() + timedelta(minutes=30), version)
                work.consume(challenge.id)
        if error:
            raise error
        return token, {'authenticated': True, 'csrf_token': self.keyed('guest-csrf|' + token), 'expires_in': 1800}

    def guest_state(self, token):
        with self.repository.transaction() as work:
            session = work.guest(digest(token or ''))
            if (not session or session['expires_at'] <= work.now() or not work.active_contact(session['contact_id'])
                    or session['policy_version'] != self.settings.policy['version']):
                return {'authenticated': False}
            return {'authenticated': True, 'csrf_token': self.keyed('guest-csrf|' + token), 'expires_in': max(0, int((session['expires_at']-work.now()).total_seconds()))}

    def inquiry(self, token, title=None, body=None, csrf=None, version=None, consent=None):
        if title is not None:
            self.policy_check(version, consent)
            if not title.strip() or not body.strip() or len(title) > 120 or len(body) > 4000:
                raise AccessError(message='제목과 문의 내용을 길이에 맞게 입력해 주세요.')
            if not csrf or not hmac.compare_digest(self.keyed('guest-csrf|' + (token or '')), csrf):
                raise AccessError('BAD_CSRF', '페이지를 새로고침하고 다시 시도해 주세요.', 403)
        with self.repository.transaction() as work:
            key = digest(token or '')
            session = work.guest(key)
            if (not session or session['expires_at'] <= work.now() or not work.active_contact(session['contact_id'])
                    or session['policy_version'] != self.settings.policy['version']):
                raise AccessError('GUEST_REQUIRED', '비회원 이메일 인증이 필요합니다.', 401)
            if title is None:
                return work.get_inquiry(key)
            return work.put_inquiry(key, title.strip(), body.strip(), version)
