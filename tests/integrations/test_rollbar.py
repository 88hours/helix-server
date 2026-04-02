"""Tests for integrations/rollbar.py"""
import hashlib
import hmac
import pytest

from integrations.rollbar import parse_event, verify_signature


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
    "event_name": "new_item",
    "data": {
        "item": {
            "id": 12345,
            "title": "KeyError: 'item_id'",
            "level": "error",
            "environment": "production",
            "project_id": 654321,
            "last_occurrence": {
                "id": "occ-uuid-001",
                "language": "python",
                "context": "checkout.process",
                "body": {
                    "trace": {
                        "frames": [
                            {
                                "filename": "checkout.py",
                                "lineno": 42,
                                "method": "process",
                                "code": "    item = cart[item_id]",
                            }
                        ],
                        "exception": {
                            "class": "KeyError",
                            "message": "'item_id'",
                        },
                    }
                },
            },
        }
    },
}


def test_parse_event_basic_fields():
    event = parse_event(RAW_PAYLOAD)
    assert event.item_id == "12345"
    assert event.occurrence_id == "occ-uuid-001"
    assert event.title == "KeyError: 'item_id'"
    assert event.level == "error"
    assert event.environment == "production"
    assert event.language == "python"
    assert event.culprit == "checkout.process"
    assert event.project_id == 654321


def test_parse_event_stack_trace_extracted():
    event = parse_event(RAW_PAYLOAD)
    assert event.stack_trace is not None
    assert "checkout.py" in event.stack_trace
    assert "KeyError" in event.stack_trace
    assert "cart[item_id]" in event.stack_trace


def test_parse_event_no_frames_returns_none_stack_trace():
    payload = {
        "event_name": "new_item",
        "data": {
            "item": {
                "id": 999,
                "title": "Something broke",
                "level": "error",
                "last_occurrence": {
                    "id": "occ-002",
                    "body": {"trace": {"frames": [], "exception": {"class": "Error", "message": "oops"}}},
                },
            }
        },
    }
    event = parse_event(payload)
    assert event.stack_trace is None


def test_parse_event_no_occurrence_returns_none_stack_trace():
    payload = {
        "event_name": "new_item",
        "data": {
            "item": {
                "id": 888,
                "title": "Silent failure",
                "level": "warning",
                "last_occurrence": {"id": "occ-003", "body": {}},
            }
        },
    }
    event = parse_event(payload)
    assert event.stack_trace is None


def test_parse_event_raw_preserved():
    event = parse_event(RAW_PAYLOAD)
    assert event.raw == RAW_PAYLOAD


def test_parse_event_missing_data_uses_defaults():
    event = parse_event({})
    assert event.item_id == ""
    assert event.title == "Unknown error"
    assert event.stack_trace is None
