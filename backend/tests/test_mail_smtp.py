"""The SMTP sender and the fixed message templates. No network: aiosmtplib is replaced."""
import asyncio

import aiosmtplib
import pytest

from app.mail.settings import MailSettings
from app.mail.smtp import SmtpSender, build_message
from app.mail.templates import render

SETTINGS = MailSettings.from_env({'SMTP_USERNAME': 'sender@gmail.com', 'SMTP_PASSWORD': 'abcdefghijklmnop'})
FACTS = {'number': 141, 'machine': 'VMCT-02', 'reason': '공구 교환 이상', 'note': ''}


def test_sender_uses_implicit_tls_with_certificate_validation(monkeypatch):
    seen = {}

    async def fake_send(message, **kwargs):
        seen.update(kwargs, message=message)

    monkeypatch.setattr(aiosmtplib, 'send', fake_send)
    sender = SmtpSender(SETTINGS)
    message = build_message(sender.from_address, 'customer@example.com', '제목', '본문')
    asyncio.run(sender.send(message))
    assert (seen['hostname'], seen['port'], seen['use_tls'], seen['start_tls'], seen['validate_certs']) == (
        'smtp.gmail.com', 465, True, False, True)
    assert (seen['username'], seen['password']) == ('sender@gmail.com', 'abcdefghijklmnop')
    assert seen['timeout'] <= 15 and seen['message'] is message


def test_message_is_a_plain_notification_with_no_reply_path():
    message = build_message('sender@gmail.com', 'customer@example.com', '제목', '본문입니다')
    assert (message['From'], message['To'], message['Subject']) == ('sender@gmail.com', 'customer@example.com', '제목')
    assert message['Auto-Submitted'] == 'auto-generated' and message['Reply-To'] is None
    assert message['Message-ID'].endswith('@gmail.com>')
    assert message.get_content().strip() == '본문입니다'


@pytest.mark.parametrize('field', ['recipient', 'subject'])
def test_header_injection_is_impossible(field):
    values = {'recipient': 'customer@example.com', 'subject': '제목'}
    values[field] += '\nBcc: attacker@example.com'
    with pytest.raises(ValueError):
        build_message('sender@gmail.com', values['recipient'], values['subject'], '본문')


def test_templates_are_fixed_text_with_only_request_facts():
    for kind, phrase in [('received', '접수되었습니다'), ('approved', '처리를 시작'), ('resolved', '완료되었습니다')]:
        subject, body = render(kind, FACTS)
        assert 'CLM-141' in subject and subject.startswith('[MORRONO]') and phrase in subject + body
        assert 'VMCT-02' in body and '공구 교환 이상' in body and '발신 전용' in body
        assert '\n' not in subject


def test_closure_note_is_included_only_when_present_and_the_message_text_never_is():
    assert '종결 메모' not in render('resolved', FACTS)[1]
    assert '센서를 재조임했습니다' in render('resolved', {**FACTS, 'note': '센서를 재조임했습니다'})[1]
    assert '종결 메모' not in render('received', {**FACTS, 'note': '센서를 재조임했습니다'})[1]


def test_unknown_kind_is_rejected():
    with pytest.raises(KeyError):
        render('marketing', FACTS)
