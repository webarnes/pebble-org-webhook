from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from index_org_webhook.app import app
from index_org_webhook.hmac_verify import SignedHeaders, make_signature
from index_org_webhook.settings import get_settings

SECRET = "test-secret"
BOUNDARY = "----IndexBoundary"


def _multipart(fields: dict[str, str]) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{BOUNDARY}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n"
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(f"--{BOUNDARY}--\r\n".encode("utf-8"))
    return b"".join(parts)


def _signed_post(
    client: TestClient,
    fields: dict[str, str],
    *,
    delivery: str = "delivery-1",
    trigger: str = "single-click-hold",
    is_test: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> object:
    body = _multipart(fields)
    timestamp = int(time.time())
    headers_obj = SignedHeaders("1", "", timestamp, delivery, trigger, is_test)
    signature = make_signature(SECRET, headers_obj, body)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
        "X-Index-Webhook-Version": "1",
        "X-Index-Delivery": delivery,
        "X-Index-Trigger": trigger,
        "X-Index-Timestamp": str(timestamp),
        "X-Index-Signature": signature,
    }
    if is_test:
        headers["X-Index-Test"] = "true"
    if extra_headers:
        headers.update(extra_headers)
    return client.post("/webhook", content=body, headers=headers)


def _patch_llm_response(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object] | Exception) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def fake_client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("index_org_webhook.classify.httpx.Client", fake_client)


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_scheduled_task_goes_to_inbox(org_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm_response(
        monkeypatch,
        {
            "kind": "task",
            "heading": "Call the dentist",
            "scheduled": "2026-11-16 09:00",
            "proposed_tasks": [],
        },
    )
    transcript = "Remind me to call the dentist Monday at 9am"
    with TestClient(app) as client:
        response = _signed_post(
            client,
            {
                "transcription": transcript,
                "recordedAt": "1763169660000",
                "client": "ring",
            },
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "task"
    todo = (org_env / "todo.org").read_text(encoding="utf-8")
    assert "** TODO Call the dentist\nSCHEDULED: <2026-11-16 Mon 09:00>\n:LOGBOOK:\n" in todo
    assert f'from Index 01: "{transcript}"' in todo
    inbox_at = todo.index("* Inbox")
    assert todo.index("** TODO Call the dentist") > inbox_at


def test_note_with_proposed_task_goes_to_daily(org_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm_response(
        monkeypatch,
        {
            "kind": "note",
            "heading": "AC cleaning and filter check",
            "scheduled": None,
            "proposed_tasks": ["Buy replacement AC filter"],
        },
    )
    transcript = "The repairman came and cleaned the AC, and said the filter is getting old."
    with TestClient(app) as client:
        response = _signed_post(
            client,
            {
                "transcription": transcript,
                "recordedAt": "1763169660000",
                "client": "ring",
            },
            delivery="delivery-note",
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "note"
    dailies = list((org_env / "roam" / "daily").glob("*.org"))
    assert len(dailies) == 1
    text = dailies[0].read_text(encoding="utf-8")
    assert "* Log" in text
    assert "** AC cleaning and filter check" in text
    assert f"{transcript}\n\n- [ ] Buy replacement AC filter\n" in text


def test_unconfigured_or_failing_llm_falls_back_to_daily_note(
    org_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = "Remember to pick up the dry cleaning. It closes at five."
    with TestClient(app) as client:
        unconfigured_resp = _signed_post(
            client,
            {
                "transcription": transcript,
                "recordedAt": "1763169660000",
                "client": "ring",
            },
            delivery="delivery-unconfigured",
        )
    assert unconfigured_resp.status_code == 200
    assert unconfigured_resp.json()["kind"] == "note"

    _patch_llm_response(monkeypatch, httpx.ConnectError("connection refused"))
    with TestClient(app) as client:
        failing_resp = _signed_post(
            client,
            {
                "transcription": "Another voice note while offline.",
                "recordedAt": "1763169660000",
                "client": "ring",
            },
            delivery="delivery-offline",
        )
    assert failing_resp.status_code == 200
    assert failing_resp.json()["kind"] == "note"

    dailies = list((org_env / "roam" / "daily").glob("*.org"))
    assert len(dailies) == 1
    text = dailies[0].read_text(encoding="utf-8")
    assert "** Remember to pick up the dry cleaning" in text
    assert transcript in text
    assert "** Another voice note while offline" in text


def test_duplicate_delivery_is_idempotent(org_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm_response(
        monkeypatch,
        {
            "kind": "task",
            "heading": "Buy milk",
            "scheduled": None,
            "proposed_tasks": [],
        },
    )
    fields = {"transcription": "todo buy milk", "recordedAt": "1763169660000", "client": "ring"}
    with TestClient(app) as client:
        first = _signed_post(client, fields, delivery="same-id")
        second = _signed_post(client, fields, delivery="same-id")
    assert first.status_code == 200
    assert first.json()["kind"] == "task"
    assert second.status_code == 200
    assert second.text == "Already received"
    todo = (org_env / "todo.org").read_text(encoding="utf-8")
    assert todo.count("** TODO Buy milk") == 1


def test_test_event_does_not_write(org_env: Path) -> None:
    before = (org_env / "todo.org").read_text(encoding="utf-8")
    with TestClient(app) as client:
        response = _signed_post(
            client,
            {"transcription": "Index webhook test", "test": "true", "client": "ring"},
            trigger="test-event",
            is_test=True,
            delivery="test-delivery",
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "test"
    assert (org_env / "todo.org").read_text(encoding="utf-8") == before
    assert not (org_env / "roam" / "daily").exists() or not list((org_env / "roam" / "daily").glob("*.org"))


def test_empty_transcript_is_400(org_env: Path) -> None:
    with TestClient(app) as client:
        response = _signed_post(
            client,
            {"transcription": "   ", "recordedAt": "1763169660000", "client": "ring"},
            delivery="empty",
        )
    assert response.status_code == 400


def test_bad_signature_is_401(org_env: Path) -> None:
    body = _multipart({"transcription": "call the dentist", "client": "ring"})
    timestamp = int(time.time())
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
                "X-Index-Webhook-Version": "1",
                "X-Index-Delivery": "bad-sig",
                "X-Index-Trigger": "single-click-hold",
                "X-Index-Timestamp": str(timestamp),
                "X-Index-Signature": "00" * 32,
            },
        )
    assert response.status_code == 401
    get_settings.cache_clear()
