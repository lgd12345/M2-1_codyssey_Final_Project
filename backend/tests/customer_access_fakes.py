from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import UUID, uuid4

from app.auth.service import DuplicateUser
from app.customer_access.core import AccessError, AccessService, Settings

POLICY = dict(version='synthetic-v1', purpose='합성 검증', items='합성 데이터', retention='테스트 종료까지',
              recipients='외부 전달 없음', contact='합성 테스트 담당자')


class MemoryRepository:
    def __init__(self):
        self.time = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.lock = RLock()
        self.contacts = {UUID(int=1): {'id': UUID(int=1), 'code': 'DEMO', 'email': 'contact@example.org', 'active': True, 'company_id': UUID(int=10)}}
        self.challenges, self.sessions, self.inquiries, self.users = {}, {}, {}, {}

    @contextmanager
    def transaction(self):
        with self.lock:
            snapshot = deepcopy((self.challenges, self.sessions, self.inquiries, self.users))
            try:
                yield self
            except Exception:
                self.challenges, self.sessions, self.inquiries, self.users = snapshot
                raise

    def now(self): return self.time

    def throttle(self, client, email, now):
        recent = [c for c in self.challenges.values() if c.created_at > now - timedelta(minutes=10)]
        if (sum(c.client_key == client for c in recent) >= 5 or sum(c.email_key == email for c in recent) >= 5
                or any(c.email_key == email and c.created_at > now - timedelta(seconds=60) for c in recent)):
            raise AccessError('ACCESS_RATE_LIMIT', status=429)

    def contact(self, company, email):
        return next((c for c in self.contacts.values() if c['code'] == company and c['email'] == email and c['active']), None)

    def active_contact(self, identity): return bool(self.contacts.get(identity, {}).get('active'))

    def add_challenge(self, c):
        for old in self.challenges.values():
            if old.email_key == c.email_key and old.purpose == c.purpose and old.state in ('pending', 'sent'):
                old.state = 'revoked'
        self.challenges[c.id] = c

    def delivery(self, identity, success):
        c = self.challenges[identity]
        if c.state == 'pending': c.state = 'sent' if success else 'failed'

    def challenge(self, identity): return self.challenges.get(identity)
    def attempt(self, identity, n): self.challenges[identity].attempts = n
    def consume(self, identity): self.challenges[identity].state = 'consumed'

    def register_customer(self, contact, login, password, version):
        if login in self.users: raise DuplicateUser()
        if any(u.get('contact') == contact for u in self.users.values()): raise DuplicateUser()
        self.users[login] = {'id': uuid4(), 'contact': contact, 'role': 'customer', 'version': version}

    def add_guest(self, key, contact, expires, version):
        self.sessions[key] = {'contact_id': contact, 'expires_at': expires, 'policy_version': version}

    def guest(self, key): return self.sessions.get(key)
    def get_inquiry(self, key): return self.inquiries.get(key)

    def put_inquiry(self, key, title, body, version):
        old = self.inquiries.get(key)
        if old:
            if (old['title'], old['body']) != (title, body): raise AccessError('INQUIRY_CONFLICT', status=409)
            return old
        value = dict(id=str(uuid4()), title=title, body=body, created_at=self.time.isoformat())
        self.inquiries[key] = value
        return value

    def customer_profile(self, identity):
        return next(({'id': str(self.contacts[u['contact']]['company_id']), 'name': '합성 고객사'}
                     for u in self.users.values() if u['id'] == identity and self.active_contact(u['contact'])), None)


def service():
    settings = Settings('synthetic-dsn', 'synthetic-secret-is-at-least-32-characters', 'synthetic-smtp-password',
                        'sender@example.org', dict(POLICY), True)
    return AccessService(settings, MemoryRepository())


def issue(s, purpose='guest', email='contact@example.org', company='DEMO', client='synthetic-client'):
    proof, identity, recipient, number = s.start(purpose, company, email, client, 'synthetic-v1', True)
    s.sent(identity, True)
    return proof, identity, recipient, number
