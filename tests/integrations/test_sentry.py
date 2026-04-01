"""Tests for integrations/sentry.py"""
import hashlib
import hmac
import pytest

from integrations.sentry import parse_event, verify_signature


def _make_signature(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# verify_signature
# ---------------------------------------------------------------------------

def test_verify_signature_valid():
    payload = b'{"id": "123"}'
    secret = "my-secret"
    sig = _make_signature(secret, payload)
    assert verify_signature(payload, sig, secret) is True


def test_verify_signature_invalid():
    payload = b'{"id": "123"}'
    assert verify_signature(payload, "badhex", "my-secret") is False


def test_verify_signature_wrong_secret():
    payload = b'{"id": "123"}'
    sig = _make_signature("correct-secret", payload)
    assert verify_signature(payload, sig, "wrong-secret") is False


# ---------------------------------------------------------------------------
# parse_event
# ---------------------------------------------------------------------------

RAW_PAYLOAD = {
    "id": "evt-001",
    "message": "KeyError: 'item_id'",
    "project_slug": "backend",
    "url": "https://sentry.io/issues/1",
    "event": {
        "event_id": "evt-001",
        "level": "error",
        "platform": "python",
        "culprit": "checkout.process",
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": "'item_id'",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "checkout.py",
                                "lineno": 42,
                                "function": "process",
                                "context_line": "    item = cart[item_id]",
                            }
                        ]
                    },
                }
            ]
        },
    },
}


def test_parse_event_basic_fields():
    event = parse_event(RAW_PAYLOAD)
    assert event.event_id == "evt-001"
    assert event.project_slug == "backend"
    assert event.level == "error"
    assert event.platform == "python"
    assert event.culprit == "checkout.process"


def test_parse_event_stack_trace_extracted():
    event = parse_event(RAW_PAYLOAD)
    assert event.stack_trace is not None
    assert "checkout.py" in event.stack_trace
    assert "KeyError" in event.stack_trace
    assert "cart[item_id]" in event.stack_trace


def test_parse_event_no_exception_returns_none_stack_trace():
    payload = {
        "id": "evt-002",
        "message": "Something broke",
        "event": {"event_id": "evt-002", "level": "error"},
    }
    event = parse_event(payload)
    assert event.stack_trace is None


def test_parse_event_no_frames_returns_none_stack_trace():
    payload = {
        "id": "evt-003",
        "event": {
            "event_id": "evt-003",
            "exception": {"values": [{"type": "Error", "value": "oops", "stacktrace": {"frames": []}}]},
        },
    }
    event = parse_event(payload)
    assert event.stack_trace is None


def test_parse_event_falls_back_to_logentry_for_title():
    payload = {
        "event": {
            "event_id": "evt-004",
            "logentry": {"formatted": "Log message title", "message": "raw msg"},
        },
    }
    event = parse_event(payload)
    assert event.title == "Log message title"
    assert event.message == "raw msg"


def test_parse_event_raw_preserved():
    event = parse_event(RAW_PAYLOAD)
    assert event.raw == RAW_PAYLOAD
