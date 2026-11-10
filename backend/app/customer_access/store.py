from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import hashlib

import psycopg
from psycopg.rows import dict_row

from app.auth.service import create_user
from app.customer_access.core import AccessError, Challenge

MIGRATION = Path(__file__).parent / 'migrations' / '001_initial.sql'
ROLE_MIGRATION = Path(__file__).parent / 'migrations' / '002_customer_role.sql'


def migration_checksum():
    # Text-mode universal newlines give the same checksum on Windows and Linux.
    return hashlib.sha256(MIGRATION.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


class PostgresRepository:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.dsn, connect_timeout=3) as connection:
            connection.execute("SET LOCAL statement_timeout = '3s'")
            connection.execute("SET LOCAL lock_timeout = '1s'")
            yield Work(connection)

    def ready(self, registration):
        try:
            with psycopg.connect(self.dsn, connect_timeout=3) as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                connection.execute("SET LOCAL statement_timeout = '2s'")
                row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('001',)).fetchone()
                if row is None or row[0] != migration_checksum():
                    return False
                if registration and connection.execute("SELECT to_regclass('app_user')").fetchone()[0] is None:
                    return False
                if registration:
                    role_row = connection.execute('SELECT checksum FROM claim_access.schema_version WHERE version=%s', ('002',)).fetchone()
                    expected = hashlib.sha256(ROLE_MIGRATION.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
                    if role_row is None or role_row[0] != expected:
                        return False
                return True
        except (psycopg.Error, OSError):
            return False


class Work:
    def __init__(self, connection):
        self.connection = connection

    def one(self, query, params=()):
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(query, params).fetchone()

    def now(self):
        return self.one('SELECT now() AS value')['value']

    def throttle(self, client, email, now):
        # Serialize issuance per client and per email across all web instances.
        for key in sorted(('client:' + client, 'email:' + email)):
            self.connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (key,))
        row = self.one("""SELECT count(*) FILTER(WHERE client_key=%s) AS client_count,
            count(*) FILTER(WHERE email_key=%s) AS email_count,
            count(*) FILTER(WHERE email_key=%s AND created_at>%s-interval '60 seconds') AS recent
            FROM claim_access.challenge WHERE created_at>%s-interval '10 minutes'
            AND (client_key=%s OR email_key=%s)""", (client, email, email, now, now, client, email))
        if row['client_count'] >= 5 or row['email_count'] >= 5 or row['recent']:
            raise AccessError('ACCESS_RATE_LIMIT', '요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)

    def contact(self, company, email):
        return self.one('''SELECT c.id,c.email FROM claim_access.contact c
            JOIN claim_access.company p ON p.id=c.company_id
            WHERE p.code=%s AND c.email=%s AND p.is_active AND c.is_active FOR SHARE OF c,p''', (company, email))

    def active_contact(self, identity):
        return self.one('''SELECT c.id FROM claim_access.contact c JOIN claim_access.company p ON p.id=c.company_id
            WHERE c.id=%s AND c.is_active AND p.is_active FOR SHARE OF c,p''', (identity,)) is not None

    def add_challenge(self, challenge):
        # Only expired transient codes; never customer accounts or inquiry history.
        self.connection.execute('''DELETE FROM claim_access.challenge WHERE id IN
            (SELECT id FROM claim_access.challenge WHERE expires_at<now()
             ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)''')
        self.connection.execute("UPDATE claim_access.challenge SET state='revoked' WHERE email_key=%s AND purpose=%s AND state IN ('pending','sent')", (challenge.email_key, challenge.purpose))
        values = asdict(challenge)
        # Fixed identifiers; all externally influenced values are parameters.
        self.connection.execute('''INSERT INTO claim_access.challenge
            (id,purpose,proof_hash,code_hash,contact_id,client_key,email_key,policy_version,created_at,expires_at,attempts,state)
            VALUES (%(id)s,%(purpose)s,%(proof_hash)s,%(code_hash)s,%(contact_id)s,%(client_key)s,%(email_key)s,
                    %(policy_version)s,%(created_at)s,%(expires_at)s,%(attempts)s,%(state)s)''', values)

    def delivery(self, identity, success):
        self.connection.execute("UPDATE claim_access.challenge SET state=%s WHERE id=%s AND state='pending'", ('sent' if success else 'failed', identity))

    def challenge(self, identity):
        row = self.one('SELECT * FROM claim_access.challenge WHERE id=%s FOR UPDATE', (identity,))
        return Challenge(**row) if row else None

    def attempt(self, identity, attempts):
        self.connection.execute('UPDATE claim_access.challenge SET attempts=%s WHERE id=%s', (attempts, identity))

    def consume(self, identity):
        self.connection.execute("UPDATE claim_access.challenge SET state='consumed' WHERE id=%s", (identity,))

    def register_customer(self, contact, login_id, password, version):
        # Nested transaction keeps a duplicate user's failure from aborting the
        # attempt counter transaction. Existing credentials are never overwritten.
        with self.connection.transaction():
            if self.one('SELECT id FROM claim_access.registration WHERE contact_id=%s', (contact,)):
                raise AccessError('REGISTRATION_EXISTS', '이 연락처의 가입 신청을 확인해 주세요.', 409)
            user = create_user(self.connection, login_id, password, role='customer')
            self.connection.execute('INSERT INTO claim_access.registration(app_user_id,contact_id,policy_version) VALUES (%s,%s,%s)', (user.id, contact, version))

    def customer_profile(self, identity):
        row = self.one('''SELECT p.id,p.name FROM claim_access.registration r
            JOIN claim_access.contact c ON c.id=r.contact_id JOIN claim_access.company p ON p.id=c.company_id
            WHERE r.app_user_id=%s AND c.is_active AND p.is_active''', (identity,))
        return {'id': str(row['id']), 'name': row['name']} if row else None

    def add_guest(self, key, contact, expires, version):
        self.connection.execute('INSERT INTO claim_access.guest_session(token_hash,contact_id,expires_at,policy_version) VALUES (%s,%s,%s,%s)', (key, contact, expires, version))

    def guest(self, key):
        return self.one('SELECT * FROM claim_access.guest_session WHERE token_hash=%s FOR UPDATE', (key,))

    def get_inquiry(self, key):
        row = self.one('SELECT id,title,body,created_at FROM claim_access.inquiry WHERE guest_key=%s', (key,))
        if not row:
            return None
        return {**row, 'id': str(row['id']), 'created_at': row['created_at'].isoformat()}

    def put_inquiry(self, key, title, body, version):
        existing = self.get_inquiry(key)
        if existing:
            if existing['title'] != title or existing['body'] != body:
                raise AccessError('INQUIRY_CONFLICT', '이미 접수된 문의가 있습니다. 기존 내용을 확인해 주세요.', 409)
            return existing
        self.connection.execute('INSERT INTO claim_access.inquiry(guest_key,title,body,policy_version) VALUES (%s,%s,%s,%s)', (key, title, body, version))
        return self.get_inquiry(key)
