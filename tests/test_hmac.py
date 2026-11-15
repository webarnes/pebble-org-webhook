from __future__ import annotations

import time

import pytest

from index_org_webhook.hmac_verify import (
    SignedHeaders,
    WebhookAuthError,
    make_signature,
    parse_signed_headers,
    verify_signature,
)

SECRET = "test-secret"


def _headers(*, ts: int | None = None, signature: str = "abc", test: bool = False) -> dict[str, str]:
    timestamp = str(int(time.time() if ts is None else ts))
    values = {
        "x-index-webhook-version": "1",
        "x-index-signature": signature,
        "x-index-timestamp": timestamp,
        "x-index-delivery": "delivery-1",
        "x-index-trigger": "single-click-hold",
    }
    if test:
        values["x-index-test"] = "true"
    return values


def test_signature_round_trip() -> None:
    raw = b"multipart-body"
    parsed = parse_signed_headers(_headers())
    signature = make_signature(SECRET, parsed, raw)
    headers = _headers(signature=signature, ts=parsed.timestamp)
    verified = parse_signed_headers(headers)
    verify_signature(SECRET, verified, raw)


def test_wrong_signature_is_rejected() -> None:
    parsed = parse_signed_headers(_headers(signature="deadbeef"))
    with pytest.raises(WebhookAuthError) as exc:
        verify_signature(SECRET, parsed, b"body")
    assert exc.value.status_code == 401


def test_expired_timestamp_is_rejected() -> None:
    with pytest.raises(WebhookAuthError) as exc:
        parse_signed_headers(_headers(ts=int(time.time()) - 301))
    assert exc.value.status_code == 401
    assert "Expired" in exc.value.message


def test_unsupported_version() -> None:
    headers = _headers()
    headers["x-index-webhook-version"] = "2"
    with pytest.raises(WebhookAuthError) as exc:
        parse_signed_headers(headers)
    assert exc.value.status_code == 400


def test_test_flag_changes_signed_bytes() -> None:
    raw = b"body"
    recording = SignedHeaders("1", "", 1_700_000_000, "d1", "single-click-hold", False)
    test = SignedHeaders("1", "", 1_700_000_000, "d1", "test-event", True)
    assert make_signature(SECRET, recording, raw) != make_signature(SECRET, test, raw)
