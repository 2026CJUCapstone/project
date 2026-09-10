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
