from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
import json
from uuid import UUID

import pytest

from app.customer_access.core import AccessError, Settings, company_code, email_address
from customer_access_fakes import POLICY, issue, service


def test_default_activation_does_not_read_policy_or_connect():
    class Forbidden(dict):
        def __getitem__(self, key): raise AssertionError('No secret/file lookup while off')
    assert Settings.load(Forbidden()) is None


@pytest.mark.parametrize('missing', ['CUSTOMER_ACCESS_RELEASE_APPROVED', 'APP_COOKIE_SECURE', 'DATABASE_URL', 'CUSTOMER_SMTP_PASSWORD', 'CUSTOMER_ACCESS_SECRET'])
def test_missing_activation_requirement_stays_closed(tmp_path, missing):
    path = tmp_path/'policy.json'; path.write_text(json.dumps(POLICY), encoding='utf-8')
    env = dict(CUSTOMER_ACCESS_ENABLED='1', CUSTOMER_ACCESS_RELEASE_APPROVED='1', APP_COOKIE_SECURE='1',
               DATABASE_URL='business', CUSTOMER_ACCESS_SECRET='s'*40, CUSTOMER_SMTP_PASSWORD='fake',
               CUSTOMER_ACCESS_POLICY_FILE=str(path), CUSTOMER_MAIL_FROM='sender@example.org')
    env.pop(missing)
    assert Settings.load(env) is None


def test_separate_auth_database_disables_registration_not_guest(tmp_path):
    path = tmp_path/'p.json'; path.write_text(json.dumps(POLICY), encoding='utf-8')
    env = dict(CUSTOMER_ACCESS_ENABLED='1', CUSTOMER_ACCESS_RELEASE_APPROVED='1', APP_COOKIE_SECURE='1', DATABASE_URL='business',
               RAG_DATABASE_URL='different-auth', CUSTOMER_REGISTRATION_ENABLED='1', CUSTOMER_ACCESS_SECRET='s'*40,
               CUSTOMER_SMTP_PASSWORD='fake', CUSTOMER_MAIL_FROM='sender@example.org', CUSTOMER_ACCESS_POLICY_FILE=str(path))
    value = Settings.load(env)
    assert value and not value.registration
    path.write_text(json.dumps({**POLICY, 'version': 'v' * 121}), encoding='utf-8')
    assert Settings.load(env) is None


@pytest.mark.parametrize('value', ['a\r\nBcc:x@example.org', 'Person <a@example.org>', 'bad', 'a@localhost'])
def test_email_rejects_headers_and_ambiguous_addresses(value):
    with pytest.raises(AccessError): email_address(value)


@pytest.mark.parametrize('consent,version', [(False,'synthetic-v1'), (True,'old-version'), ('true','synthetic-v1')])
def test_no_issuance_without_current_consent(consent, version):
    s = service()
    with pytest.raises(AccessError): s.start('guest','DEMO','contact@example.org','x',version,consent)
    assert not s.repository.challenges


def test_plaintext_code_proof_client_and_email_are_not_stored():
    s = service(); proof, identity, email, number = issue(s)
    c = s.repository.challenges[identity]
    assert c.code_hash != number and c.proof_hash != proof.split('.')[1]
    assert 'contact@example.org' not in repr(c) and 'synthetic-client' not in repr(c)
    assert c.code_hash == s.code_hash(c, number)


def test_unknown_company_or_contact_gets_dummy_not_a_valid_code():
    s = service(); proof, identity, recipient, number = issue(s, company='UNKNOWN')
    assert recipient is None and s.repository.challenges[identity].state == 'dummy'
    with pytest.raises(AccessError): s.guest(proof,number,'synthetic-v1',True)


def test_wrong_attempts_persist_and_lock_out_even_correct_code():
    s = service(); proof, identity, _, number = issue(s)
    wrong = '999999' if number != '999999' else '000000'
    for _ in range(5):
        with pytest.raises(AccessError): s.guest(proof,wrong,'synthetic-v1',True)
    assert s.repository.challenges[identity].attempts == 5
    with pytest.raises(AccessError): s.guest(proof,number,'synthetic-v1',True)


@pytest.mark.parametrize('alteration', ['expiry','contact','purpose','proof','delivery'])
def test_unusable_challenges_never_create_sessions(alteration):
    s = service(); proof, identity, _, number = issue(s, purpose='register' if alteration == 'purpose' else 'guest')
    if alteration == 'expiry': s.repository.time += timedelta(minutes=10)
    if alteration == 'contact': s.repository.contacts[UUID(int=1)]['active'] = False
    if alteration == 'proof': proof = proof.split('.')[0]+'.forged'
    if alteration == 'delivery': s.repository.challenges[identity].state = 'failed'
    with pytest.raises(AccessError): s.guest(proof,number,'synthetic-v1',True)
    assert not s.repository.sessions


def test_resend_revokes_old_code_and_late_sender_cannot_revive_it():
    s = service(); old, identity, _, code = issue(s)
    s.repository.time += timedelta(seconds=61)
    new, _, _, code2 = issue(s)
    s.sent(identity,True)
    with pytest.raises(AccessError): s.guest(old,code,'synthetic-v1',True)
    assert s.guest(new,code2,'synthetic-v1',True)[1]['authenticated']


def test_codes_are_single_use_under_concurrent_verification():
    s = service(); proof, _, _, code = issue(s)
    def verify(_):
        try: return s.guest(proof,code,'synthetic-v1',True)[1]['authenticated']
        except AccessError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: assert list(pool.map(verify,range(2))).count(True) == 1
    assert len(s.repository.sessions) == 1


def test_rate_limits_include_unknown_destinations_and_are_durable():
    s = service()
    for n in range(5): issue(s,email=f'unknown{n}@example.org')
    with pytest.raises(AccessError) as error: issue(s,email='next@example.org')
    assert error.value.status_code == 429


def test_registration_creates_only_customer_and_cannot_replay():
    s = service(); proof, _, _, code = issue(s,'register')
    s.repository.users['existing-operator']={'id':UUID(int=30),'role':'user'}
    assert s.register(proof,code,'new-customer','synthetic-password-123','synthetic-v1',True)['state']=='registered'
    assert s.repository.users['new-customer']['role']=='customer'
    with pytest.raises(AccessError): s.register(proof,code,'other-user','synthetic-password-123','synthetic-v1',True)


def test_guest_csrf_is_required_and_own_inquiry_is_idempotent():
    s=service(); proof,_,_,code=issue(s); token,state=s.guest(proof,code,'synthetic-v1',True)
    with pytest.raises(AccessError): s.inquiry(token,'제목','내용','wrong','synthetic-v1',True)
    one=s.inquiry(token,'제목','내용',state['csrf_token'],'synthetic-v1',True)
    assert s.inquiry(token,'제목','내용',state['csrf_token'],'synthetic-v1',True)==one
    with pytest.raises(AccessError) as e:s.inquiry(token,'다른 제목','내용',state['csrf_token'],'synthetic-v1',True)
    assert e.value.status_code==409
    assert s.inquiry(token)==one


def test_other_session_and_expired_or_disabled_contact_cannot_read_inquiry():
    s=service(); proof,_,_,code=issue(s); token,state=s.guest(proof,code,'synthetic-v1',True)
    s.inquiry(token,'제목','내용',state['csrf_token'],'synthetic-v1',True)
    with pytest.raises(AccessError):s.inquiry('unrelated-token')
    s.repository.contacts[UUID(int=1)]['active']=False
    assert s.guest_state(token)=={'authenticated':False}
    with pytest.raises(AccessError):s.inquiry(token)


def test_changed_policy_and_expired_session_require_reverification():
    s=service(); proof,_,_,code=issue(s); token,_=s.guest(proof,code,'synthetic-v1',True)
    s.settings=replace(s.settings,policy={**POLICY,'version':'synthetic-v2'})
    assert not s.guest_state(token)['authenticated']
    s.settings=replace(s.settings,policy=dict(POLICY));s.repository.time+=timedelta(minutes=30)
    assert not s.guest_state(token)['authenticated']
