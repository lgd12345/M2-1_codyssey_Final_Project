"""Mail configuration: Gmail SMTP with an app password, off unless fully configured, never shown in output."""
import pytest

from app.config import startup_notes
from app.mail.settings import MailConfigError, MailSettings

ENV = {'SMTP_USERNAME': 'sender@gmail.com', 'SMTP_PASSWORD': 'abcdefghijklmnop'}


def test_not_configured_means_mail_is_off_not_an_error():
    assert MailSettings.from_env({}) is None
    assert MailSettings.from_env({'SMTP_USERNAME': '', 'SMTP_PASSWORD': ''}) is None


def test_defaults_target_gmail_over_implicit_tls_and_sender_is_the_account():
    settings = MailSettings.from_env(ENV)
    assert (settings.host, settings.port) == ('smtp.gmail.com', 465)
    assert settings.username == settings.mail_from == 'sender@gmail.com'


def test_app_password_display_spaces_are_removed():
    assert MailSettings.from_env({**ENV, 'SMTP_PASSWORD': 'abcd efgh ijkl mnop'}).password == 'abcdefghijklmnop'


@pytest.mark.parametrize('change', [
    {'SMTP_PASSWORD': ''},                               # half configured
    {'SMTP_USERNAME': ''},
    {'SMTP_PASSWORD': 'short'},
    {'SMTP_PASSWORD': 'abcdefghijklmnop\n'},
    {'SMTP_PASSWORD': 'abcdefghijklmno!'},
    {'SMTP_USERNAME': 'not-an-address'},
    {'MAIL_FROM': 'someone.else@gmail.com'},             # only the authenticated account may be the sender
    {'SMTP_PORT': 'abc'},
])
def test_invalid_or_partial_configuration_is_rejected(change):
    with pytest.raises(MailConfigError):
        MailSettings.from_env({**ENV, **change})


def test_secrets_never_appear_in_repr_or_error_messages():
    settings = MailSettings.from_env(ENV)
    assert 'abcdefghijklmnop' not in repr(settings) and 'abcdefghijklmnop' not in str(settings)
    with pytest.raises(MailConfigError) as error:
        MailSettings.from_env({**ENV, 'SMTP_PASSWORD': 'abcdefghijklmno!'})
    assert 'abcdefghijklmno' not in str(error.value)


def test_startup_notes_say_only_whether_mail_is_on_and_stay_silent_when_unconfigured():
    base = {'DATABASE_URL': 'postgresql://u:p@h/db'}
    assert not any('mail' in message.lower() for _, message in startup_notes(base))
    notes = [message for _, message in startup_notes({**base, **ENV})]
    assert any('mail notifications: on' in message for message in notes)
    assert all('abcdefghijklmnop' not in message and 'sender@gmail.com' not in message for message in notes)
    bad = startup_notes({**base, **ENV, 'SMTP_PASSWORD': 'x'})
    assert any(level == 'warning' and 'mail' in message.lower() for level, message in bad)
    assert all('SMTP_PASSWORD=x' not in message for _, message in bad)
