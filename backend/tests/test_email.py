"""Outbound email — SPEC+, see docs/spec-deviations.md #15.

ResendEmailSender is tested against a mocked transport, never the real
Resend API — same precedent as the other infra-dependent backends
(ArqQueue, S3Storage, the redis rate limiter): no live network call from
the test suite.

app.email reads settings.email_backend at import time (like app.db reads
settings.database_url — see test_password_reset.py), and conftest's
_isolated_environment fixture only points that at test config, and
force-reloads app.*, once its setup actually runs — which happens after
collection. So every import of app.email here is function-local, never at
this file's top level, or it would bind to a stale pre-reload module.
"""
import logging

import httpx


def test_console_sender_does_not_raise(caplog):
    from app.email import ConsoleEmailSender

    # pytest's default capture level is WARNING; the console sender logs at
    # INFO, so this has to be raised explicitly rather than relying on
    # whatever the app's own runtime logging config happens to be.
    caplog.set_level(logging.INFO, logger="stylesignal.email")
    ConsoleEmailSender().send_password_reset("user@example.com", "123456")
    assert "123456" in caplog.text
    assert "user@example.com" in caplog.text


def test_resend_sender_posts_the_expected_request():
    from app.email import RESEND_API_URL, ResendEmailSender

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read()
        return httpx.Response(200, json={"id": "email-id-123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ResendEmailSender("re_test_key", "StyleSignal <test@example.com>", client=client)

    sender.send_password_reset("user@example.com", "654321")

    assert captured["url"] == RESEND_API_URL
    assert captured["auth"] == "Bearer re_test_key"
    assert b"654321" in captured["body"]
    assert b"user@example.com" in captured["body"]
    assert b"test@example.com" in captured["body"]


def test_resend_sender_logs_but_does_not_raise_on_failure(caplog):
    from app.email import ResendEmailSender

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from address"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ResendEmailSender("re_test_key", "bad-from", client=client)

    # Must not raise — a provider outage is not the caller's problem (the
    # reset code is already persisted regardless).
    sender.send_password_reset("user@example.com", "111111")
    assert "invalid from address" in caplog.text


def test_get_email_sender_defaults_to_console(monkeypatch):
    from app import email

    monkeypatch.setattr(email.settings, "email_backend", "console")
    assert isinstance(email.get_email_sender(), email.ConsoleEmailSender)


def test_get_email_sender_falls_back_to_console_without_an_api_key(monkeypatch, caplog):
    from app import email

    monkeypatch.setattr(email.settings, "email_backend", "resend")
    monkeypatch.setattr(email.settings, "resend_api_key", None)
    assert isinstance(email.get_email_sender(), email.ConsoleEmailSender)
    assert "no STYLESIGNAL_RESEND_API_KEY" in caplog.text


def test_get_email_sender_returns_resend_when_configured(monkeypatch):
    from app import email

    monkeypatch.setattr(email.settings, "email_backend", "resend")
    monkeypatch.setattr(email.settings, "resend_api_key", "re_test_key")
    assert isinstance(email.get_email_sender(), email.ResendEmailSender)
