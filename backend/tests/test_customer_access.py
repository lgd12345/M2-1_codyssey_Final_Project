from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from dataclasses import replace
import json
from uuid import UUID
from unittest.mock import Mock

import pytest

from app.customer_access.core import AccessError, Settings, company_code, email_address
from customer_access_fakes import POLICY, issue, service


def test_default_activation_does_not_read_policy_or_connect():
    class Forbidden(dict):
        def __getitem__(self, key): raise AssertionError('No secret/file lookup while off')
    assert Settings.load(Forbidden()) is None


@pytest.mark.parametrize('field',['version','purpose','items','retention','recipients','contact','refusal'])
@pytest.mark.parametrize('invalid',[None,'','   '])
def test_incomplete_actual_policy_cannot_enable_collection(tmp_path,field,invalid):
    policy={**POLICY,field:invalid}
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy),encoding='utf-8')
    env=dict(CUSTOMER_ACCESS_ENABLED='1',CUSTOMER_ACCESS_RELEASE_APPROVED='1',APP_COOKIE_SECURE='1',
             DATABASE_URL='synthetic',CUSTOMER_ACCESS_SECRET='s'*40,CUSTOMER_SMTP_PASSWORD='s'*16,
             CUSTOMER_SMTP_USERNAME='sender@example.org',
             CUSTOMER_MAIL_FROM='sender@example.org',CUSTOMER_ACCESS_POLICY_FILE=str(path))
    assert Settings.load(env) is None


def test_complete_policy_retains_refusal_notice_and_missing_legacy_field_stays_closed(tmp_path):
    path=tmp_path/'policy.json'
    env=dict(CUSTOMER_ACCESS_ENABLED='1',CUSTOMER_ACCESS_RELEASE_APPROVED='1',APP_COOKIE_SECURE='1',
             DATABASE_URL='synthetic',CUSTOMER_ACCESS_SECRET='s'*40,CUSTOMER_SMTP_PASSWORD='s'*16,
             CUSTOMER_SMTP_USERNAME='sender@example.org',
             CUSTOMER_MAIL_FROM='sender@example.org',CUSTOMER_ACCESS_POLICY_FILE=str(path))
    legacy={key:value for key,value in POLICY.items() if key!='refusal'}
    path.write_text(json.dumps(legacy),encoding='utf-8');assert Settings.load(env) is None
    path.write_text(json.dumps(POLICY),encoding='utf-8')
    assert Settings.load(env).policy['refusal']==POLICY['refusal']


@pytest.mark.parametrize('missing', ['CUSTOMER_ACCESS_RELEASE_APPROVED', 'APP_COOKIE_SECURE', 'DATABASE_URL', 'CUSTOMER_SMTP_USERNAME', 'CUSTOMER_SMTP_PASSWORD', 'CUSTOMER_ACCESS_SECRET'])
def test_missing_activation_requirement_stays_closed(tmp_path, missing):
    path = tmp_path/'policy.json'; path.write_text(json.dumps(POLICY), encoding='utf-8')
    env = dict(CUSTOMER_ACCESS_ENABLED='1', CUSTOMER_ACCESS_RELEASE_APPROVED='1', APP_COOKIE_SECURE='1',
               DATABASE_URL='business', CUSTOMER_ACCESS_SECRET='s'*40, CUSTOMER_SMTP_PASSWORD='s'*16,
               CUSTOMER_SMTP_USERNAME='sender@example.org',
               CUSTOMER_ACCESS_POLICY_FILE=str(path), CUSTOMER_MAIL_FROM='sender@example.org')
    env.pop(missing)
    assert Settings.load(env) is None


def test_separate_auth_database_disables_registration_not_guest(tmp_path):
    path = tmp_path/'p.json'; path.write_text(json.dumps(POLICY), encoding='utf-8')
    env = dict(CUSTOMER_ACCESS_ENABLED='1', CUSTOMER_ACCESS_RELEASE_APPROVED='1', APP_COOKIE_SECURE='1', DATABASE_URL='business',
               RAG_DATABASE_URL='different-auth', CUSTOMER_REGISTRATION_ENABLED='1', CUSTOMER_ACCESS_SECRET='s'*40,
               CUSTOMER_SMTP_PASSWORD='s'*16, CUSTOMER_SMTP_USERNAME='sender@example.org',
               CUSTOMER_MAIL_FROM='sender@example.org', CUSTOMER_ACCESS_POLICY_FILE=str(path))
    value = Settings.load(env)
    assert value and not value.registration
    path.write_text(json.dumps({**POLICY, 'version': 'v' * 121}), encoding='utf-8')
    assert Settings.load(env) is None


def gmail_environment(tmp_path):
    path = tmp_path/'policy.json'
    path.write_text(json.dumps(POLICY), encoding='utf-8')
    return dict(CUSTOMER_ACCESS_ENABLED='1', CUSTOMER_ACCESS_RELEASE_APPROVED='1', APP_COOKIE_SECURE='1',
                DATABASE_URL='synthetic', CUSTOMER_ACCESS_SECRET='s'*40,
                CUSTOMER_SMTP_USERNAME='sender@example.org', CUSTOMER_SMTP_PASSWORD='abcdefghijklmnop',
                CUSTOMER_ACCESS_POLICY_FILE=str(path))


@pytest.mark.parametrize('sender', [None, '', '   ', ' Sender@EXAMPLE.ORG '])
def test_gmail_from_defaults_to_authenticated_account_and_normalizes_display_spaces(tmp_path, sender):
    env = gmail_environment(tmp_path)
    env['CUSTOMER_SMTP_USERNAME'] = ' Sender@EXAMPLE.ORG '
    env['CUSTOMER_SMTP_PASSWORD'] = 'abcd efgh ijkl mnop'
    if sender is not None:
        env['CUSTOMER_MAIL_FROM'] = sender
    settings = Settings.load(env)
    assert settings and settings.smtp_username == settings.mail_from == 'sender@example.org'
    assert settings.smtp_password == 'abcdefghijklmnop'
    assert settings.smtp_host == 'smtp.gmail.com' and settings.smtp_port == 465
    assert settings.smtp_password not in repr(settings) and env['CUSTOMER_ACCESS_SECRET'] not in repr(settings)


@pytest.mark.parametrize('field,value', [
    ('CUSTOMER_SMTP_USERNAME', ''), ('CUSTOMER_SMTP_USERNAME', 'resend'),
    ('CUSTOMER_SMTP_USERNAME', 'sender@example.org\r\nBcc:other@example.org'),
    ('CUSTOMER_SMTP_PASSWORD', ''), ('CUSTOMER_SMTP_PASSWORD', 'short'),
    ('CUSTOMER_SMTP_PASSWORD', 'a'*17), ('CUSTOMER_SMTP_PASSWORD', 'abcdefghijklmnop\n'),
    ('CUSTOMER_SMTP_PASSWORD', 'abcd\tefghijklmnop'), ('CUSTOMER_SMTP_PASSWORD', '가'*16),
    ('CUSTOMER_MAIL_FROM', 'different@example.org'),
    ('CUSTOMER_MAIL_FROM', 'Name <sender@example.org>'),
])
def test_invalid_google_configuration_stays_closed(tmp_path, field, value):
    env = gmail_environment(tmp_path)
    env[field] = value
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


def test_unknown_contact_is_rejected_and_cannot_receive_or_use_a_code():
    s = service()
    with pytest.raises(AccessError) as error: issue(s, email='unknown@example.org')
    assert error.value.code == 'COMPANY_EMAIL_MISMATCH'
    challenge = next(iter(s.repository.challenges.values()))
    assert challenge.contact_id is None and challenge.state == 'dummy'
    with pytest.raises(AccessError): s.guest(None,'123456','synthetic-v1',True)


@pytest.mark.parametrize('inactive', [False, True])
def test_unknown_or_inactive_company_is_rejected_before_contact_lookup(inactive):
    s = service()
    if inactive: s.repository.contacts[UUID(int=1)]['company_active'] = False
    s.repository.contact = Mock(side_effect=AssertionError('No contact lookup for invalid company'))
    with pytest.raises(AccessError) as error: issue(s, company='DEMO' if inactive else 'UNKNOWN')
    assert error.value.code == 'COMPANY_NOT_FOUND'
    assert len(s.repository.challenges) == 1
    assert next(iter(s.repository.challenges.values())).state == 'dummy'
    s.repository.contact.assert_not_called()


def test_invalid_company_attempts_cannot_bypass_issuance_rate_limit():
    s = service()
    for n in range(5):
        with pytest.raises(AccessError) as error: issue(s, company='UNKNOWN', email=f'unknown{n}@example.org')
        assert error.value.code == 'COMPANY_NOT_FOUND'
    with pytest.raises(AccessError) as error: issue(s, company='UNKNOWN', email='next@example.org')
    assert error.value.status_code == 429


def test_company_typo_can_be_corrected_without_email_resend_delay():
    s = service()
    with pytest.raises(AccessError): issue(s, company='UNKNOWN')
    proof, identity, recipient, code = issue(s, company='DEMO')
    assert recipient == 'contact@example.org' and len(s.repository.challenges) == 2
    assert s.repository.challenges[identity].state == 'sent'




@pytest.mark.parametrize('condition', ['missing', 'wrong_code', 'wrong_purpose', 'expired', 'revoked', 'consumed', 'contact_disabled'])
def test_unverified_email_verification_never_queries_account_existence(condition):
    s = service(); proof, identity, _, code = issue(s, 'guest' if condition == 'wrong_purpose' else 'register')
    s.repository.registration_exists = Mock(side_effect=AssertionError('No unauthenticated account lookup'))
    if condition == 'missing': proof = None
    if condition == 'wrong_code': code = '999999' if code != '999999' else '000000'
    if condition == 'expired': s.repository.time += timedelta(minutes=10)
    if condition in ('revoked', 'consumed'): s.repository.challenges[identity].state = condition
    if condition == 'contact_disabled': s.repository.contacts[UUID(int=1)]['active'] = False
    with pytest.raises(AccessError): s.verify_registration(proof, code, 'synthetic-v1', True)
    s.repository.registration_exists.assert_not_called()
    if condition == 'wrong_code': assert s.repository.challenges[identity].attempts == 1






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
    for n in range(5):
        with pytest.raises(AccessError) as error: issue(s,email=f'unknown{n}@example.org')
        assert error.value.code == 'COMPANY_EMAIL_MISMATCH'
    with pytest.raises(AccessError) as error: issue(s,email='next@example.org')
    assert error.value.status_code == 429


def test_registration_verification_routes_existing_contact_without_account_lookup_or_changes():
    s = service(); proof, identity, _, code = issue(s, 'register')
    original = {'id':UUID(int=77),'role':'customer','contact':UUID(int=1),'password_hash':'synthetic-original-hash'}
    s.repository.users['existing-customer'] = original.copy()
    wrong = '999999' if code != '999999' else '000000'
    with pytest.raises(AccessError): s.verify_registration(proof, wrong, 'synthetic-v1', True)
    assert s.repository.challenges[identity].state == 'sent'
    assert s.verify_registration(proof, code, 'synthetic-v1', True) == {'state':'already_registered'}
    assert s.repository.challenges[identity].state == 'consumed'
    assert s.repository.users == {'existing-customer':original}


def test_new_contact_registers_only_with_the_verified_email():
    s = service(); proof, _, _, code = issue(s, 'register')
    assert s.verify_registration(proof, code, 'synthetic-v1', True) == {'state':'verified','email':'contact@example.org'}
    assert s.register(proof, code, 'synthetic-password-123', 'synthetic-v1', True)['state']=='registered'
    with pytest.raises(AccessError): s.verify_registration(proof, code, 'synthetic-v1', True)


def test_email_verified_after_four_wrong_attempts_can_still_finish_registration():
    s=service();proof,identity,_,code=issue(s,'register')
    wrong='999999' if code!='999999' else '000000'
    for _ in range(4):
        with pytest.raises(AccessError):s.verify_registration(proof,wrong,'synthetic-v1',True)
    assert s.verify_registration(proof,code,'synthetic-v1',True)['state']=='verified'
    assert s.repository.challenges[identity].attempts==4
    assert s.register(proof,code,'synthetic-password-123','synthetic-v1',True)['state']=='registered'


def test_email_race_never_overwrites_an_existing_identity():
    s=service();proof,_,_,code=issue(s,'register')
    assert s.verify_registration(proof,code,'synthetic-v1',True)['state']=='verified'
    original={'id':UUID(int=77),'role':'user','password_hash':'synthetic-original'}
    s.repository.users['contact@example.org']=original.copy()
    with pytest.raises(AccessError) as error:s.register(proof,code,'synthetic-password-123','synthetic-v1',True)
    assert error.value.code=='REGISTRATION_EXISTS' and s.repository.users=={'contact@example.org':original}


def test_same_email_in_another_company_does_not_move_account_or_grant_membership():
    s=service();proof,_,_,code=issue(s,'register')
    s.register(proof,code,'synthetic-password-123','synthetic-v1',True)
    original=s.repository.users['contact@example.org'].copy()
    s.repository.contacts[UUID(int=2)]={'id':UUID(int=2),'code':'OTHER','email':'contact@example.org','active':True,'company_id':UUID(int=20)}
    s.repository.time+=timedelta(seconds=61)
    proof,_,_,code=issue(s,'register',company='OTHER')
    assert s.verify_registration(proof,code,'synthetic-v1',True)=={'state':'already_registered'}
    assert s.repository.users['contact@example.org']==original




def test_existing_customer_may_still_use_guest_inquiry():
    s=service();s.repository.users['customer']={'id':UUID(int=77),'contact':UUID(int=1),'role':'customer'}
    proof,_,_,code=issue(s)
    token,state=s.guest(proof,code,'synthetic-v1',True)
    assert s.inquiry(token,'합성 문의','가입된 고객의 비회원 문의',state['csrf_token'],'synthetic-v1',True)['title']=='합성 문의'


def test_registration_creates_only_customer_and_cannot_replay():
    s = service(); proof, _, _, code = issue(s,'register')
    s.repository.users['existing-operator']={'id':UUID(int=30),'role':'user'}
    assert s.register(proof,code,'synthetic-password-123','synthetic-v1',True)['state']=='registered'
    assert s.repository.users['contact@example.org']['role']=='customer'
    with pytest.raises(AccessError): s.register(proof,code,'synthetic-password-123','synthetic-v1',True)


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
