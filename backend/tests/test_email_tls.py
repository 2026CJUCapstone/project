import ssl
from types import SimpleNamespace

import pytest

from app.services import email as service


def settings():
    return SimpleNamespace(SMTP_HOST='smtp.fixture.invalid',SMTP_PORT=587,
        SMTP_FROM='from@fixture.invalid',SMTP_STARTTLS=True,SMTP_USERNAME='fixture',
        SMTP_PASSWORD='not-a-real-secret',PASSWORD_RESET_BASE_URL='',PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=30)


def test_smtp_starttls_verifies_certificate_and_hostname_before_auth(monkeypatch):
    events=[]
    class SMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,*,context=None):
            assert isinstance(context,ssl.SSLContext), 'Implicit smtplib context does not verify server identity'
            assert context.verify_mode==ssl.CERT_REQUIRED
            assert context.check_hostname is True
            events.append('verified-tls')
        def login(self,*args):events.append('login')
        def send_message(self,*args):events.append('send')
    monkeypatch.setattr(service,'settings',settings())
    monkeypatch.setattr(service.smtplib,'SMTP',SMTP)
    service.send_password_reset_email('recipient@fixture.invalid','test-token')
    assert events==['verified-tls','login','send']


def test_certificate_rejection_never_authenticates_or_sends(monkeypatch):
    class SMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,*,context=None):raise ssl.SSLCertVerificationError('untrusted fixture certificate')
        def login(self,*args):pytest.fail('Credentials must not be sent after TLS verification fails')
        def send_message(self,*args):pytest.fail('Message must not be sent after TLS verification fails')
    monkeypatch.setattr(service,'settings',settings())
    monkeypatch.setattr(service.smtplib,'SMTP',SMTP)
    with pytest.raises(ssl.SSLCertVerificationError):
        service.send_password_reset_email('recipient@fixture.invalid','test-token')


@pytest.mark.parametrize('change', [
    {'SMTP_PASSWORD': ''},
    {'SMTP_USERNAME': '', 'SMTP_PASSWORD': 'orphan'},
    {'SMTP_STARTTLS': False},
    {'SMTP_FROM': 'not-a-mailbox'},
    {'SMTP_HOST': 'bad\nheader'},
])
def test_incomplete_or_unsafe_smtp_configuration_is_not_available(monkeypatch, change):
    configured = settings()
    for key, value in change.items():
        setattr(configured, key, value)
    monkeypatch.setattr(service, 'settings', configured)
    assert service.is_email_configured() is False
    with pytest.raises(service.EmailNotConfigured):
        service.send_password_reset_email('recipient@fixture.invalid', 'test-token')


def test_reset_link_preserves_existing_query_and_removes_fragment(monkeypatch):
    configured = settings()
    configured.PASSWORD_RESET_BASE_URL = 'https://frontend.fixture.invalid/reset-password?source=mail#ignored'
    monkeypatch.setattr(service, 'settings', configured)
    body = service._build_reset_body('token+/fixture')
    assert 'source=mail&resetToken=token%2B%2Ffixture' in body
    assert '#ignored' not in body


def test_recipient_header_injection_is_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(service, 'settings', settings())
    monkeypatch.setattr(service.smtplib, 'SMTP', lambda *_a, **_k: pytest.fail('must not connect'))
    with pytest.raises(service.EmailNotConfigured):
        service.send_password_reset_email('victim@example.test\nBcc: attacker@example.test', 'token')


def test_connection_probe_authenticates_and_uses_noop_without_sending(monkeypatch):
    events = []
    class SMTP:
        def __init__(self, *_args, **_kwargs): events.append('connect')
        def __enter__(self): return self
        def __exit__(self, *_args): events.append('close')
        def starttls(self, *, context): events.append('tls')
        def login(self, *_args): events.append('login')
        def noop(self): events.append('noop'); return 250, b'ok'
        def send_message(self, *_args): pytest.fail('probe must not send mail')
    monkeypatch.setattr(service, 'settings', settings())
    monkeypatch.setattr(service.smtplib, 'SMTP', SMTP)
    service.verify_smtp_connection()
    assert events == ['connect', 'tls', 'login', 'noop', 'close']


def test_connection_probe_rejects_non_success_noop(monkeypatch):
    class SMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def starttls(self, *, context): pass
        def login(self, *_args): pass
        def noop(self): return 421, b'unavailable'
    monkeypatch.setattr(service, 'settings', settings())
    monkeypatch.setattr(service.smtplib, 'SMTP', SMTP)
    with pytest.raises(service.smtplib.SMTPResponseException):
        service.verify_smtp_connection()
