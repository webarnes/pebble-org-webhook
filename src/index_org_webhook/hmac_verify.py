from __future__ import annotations

import hmac
import hashlib
import time
from dataclasses import dataclass


class WebhookAuthError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SignedHeaders:
    webhook_version: str
    signature: str
    timestamp: int
    delivery_id: str
    trigger: str
    is_test: bool


def parse_signed_headers(
    headers: dict[str, str],
    *,
    now: int | None = None,
    leeway_seconds: int = 300,
    require_signature: bool = True,
) -> SignedHeaders:
    version = headers.get("x-index-webhook-version", "")
    if version != "1":
        raise WebhookAuthError("Unsupported webhook version", 400)

    delivery_id = headers.get("x-index-delivery", "")
    trigger = headers.get("x-index-trigger", "")
    is_test = headers.get("x-index-test", "").lower() == "true"
    signature = headers.get("x-index-signature", "")
    timestamp_text = headers.get("x-index-timestamp", "")

    if require_signature:
        if not signature or not timestamp_text:
            raise WebhookAuthError("Missing signature", 401)
        try:
            timestamp = int(timestamp_text)
        except ValueError as exc:
            raise WebhookAuthError("Invalid timestamp", 400) from exc
        current = int(time.time() if now is None else now)
        if abs(current - timestamp) > leeway_seconds:
            raise WebhookAuthError("Expired request", 401)
    else:
        timestamp = int(timestamp_text) if timestamp_text.isdigit() else int(time.time() if now is None else now)

    if not delivery_id:
        raise WebhookAuthError("Missing delivery id", 400)

    return SignedHeaders(
        webhook_version=version,
        signature=signature,
        timestamp=timestamp,
        delivery_id=delivery_id,
        trigger=trigger,
        is_test=is_test,
    )


def signed_payload(headers: SignedHeaders, raw_body: bytes) -> bytes:
    prefix = (
        f"v{headers.webhook_version}\n"
        f"{headers.timestamp}\n"
        f"{headers.delivery_id}\n"
        f"{headers.trigger}\n"
        f"{1 if headers.is_test else 0}\n"
    )
    return prefix.encode("utf-8") + raw_body


def verify_signature(secret: str, headers: SignedHeaders, raw_body: bytes) -> None:
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload(headers, raw_body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, headers.signature):
        raise WebhookAuthError("Invalid signature", 401)


def make_signature(secret: str, headers: SignedHeaders, raw_body: bytes) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        signed_payload(headers, raw_body),
        hashlib.sha256,
    ).hexdigest()
