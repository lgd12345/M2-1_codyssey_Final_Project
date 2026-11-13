from email.message import EmailMessage
from email.utils import make_msgid


async def send_message(settings, message):
    import aiosmtplib

    await aiosmtplib.send(message, hostname=settings.smtp_host, port=settings.smtp_port,
                         username=settings.smtp_username, password=settings.smtp_password, use_tls=True,
                         start_tls=False, validate_certs=True, timeout=10)


async def send_code(settings, recipient, number):
    message = EmailMessage()
    message['From'], message['To'] = settings.mail_from, recipient
    message['Subject'] = '[MORRONO] 이메일 인증번호'
    message['Message-ID'] = make_msgid(domain=settings.mail_from.split('@')[1])
    message.set_content(f'인증번호: {number}\n\n10분 안에 입력해 주세요. 한 번만 사용할 수 있습니다.\n직접 요청하지 않았다면 이 메일을 무시해 주세요.\n')
    await send_message(settings, message)


async def deliver(service, identity, recipient, number):
    success = False
    try:
        await send_code(service.settings, recipient, number)
    except Exception:
        # A timeout may mean delivery is unknown. Revoke this code; do not auto retry
        # or include SMTP exceptions/addresses/codes in application logs/responses.
        pass
    else:
        success = True
    try:
        service.sent(identity, success)
    except Exception:
        # The code remains pending/invalid and expires. Avoid chained exceptions
        # that could reveal the original SMTP recipient/response in a traceback.
        pass
