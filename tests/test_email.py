class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent_message = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent_message = message


def test_send_password_reset_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()

    from app.core.email import send_password_reset_email

    send_password_reset_email("user@example.com", "http://x/reset-password?token=abc")

    assert len(_FakeSMTP.instances) == 1
    fake = _FakeSMTP.instances[0]
    assert fake.host == "smtp.example.com"
    assert fake.port == 2525
    assert fake.started_tls is True
    assert fake.login_args == ("bot@example.com", "secret")
    assert fake.sent_message["To"] == "user@example.com"
    assert "reset-password?token=abc" in fake.sent_message.get_payload()

    get_settings.cache_clear()
