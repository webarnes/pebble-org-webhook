from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from index_org_webhook.classify import classify_transcript
from index_org_webhook.deliveries import DeliveryStore
from index_org_webhook.hmac_verify import (
    WebhookAuthError,
    parse_signed_headers,
    verify_signature,
)
from index_org_webhook.org_append import (
    OrgWriteError,
    daily_path_for,
    write_daily_note,
    write_inbox_task,
)
from index_org_webhook.org_time import recorded_at_datetime
from index_org_webhook.settings import Settings, get_settings

logger = logging.getLogger("index_org_webhook")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.llm_configured:
        logger.info(
            "Index Org Webhook started. LLM enabled: model=%s base_url=%s",
            settings.llm_model,
            settings.llm_base_url,
        )
    else:
        logger.warning(
            "Index Org Webhook started. LLM DISABLED: LLM_API_KEY is not configured. All voice memos will fall back to daily notes."
        )
    yield


app = FastAPI(title="Index Org Webhook", lifespan=lifespan)


def _header_map(request: Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.headers.items()}


def _delivery_store(settings: Settings) -> DeliveryStore:
    return DeliveryStore(settings.deliveries_db)


def _check_optional_auth(request: Request, settings: Settings) -> None:
    if not settings.index_auth_token:
        return
    expected = settings.index_auth_token
    authorization = request.headers.get("authorization", "")
    token = request.headers.get("x-widget-token", "")
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    raw = authorization.strip()
    if expected not in {bearer, token, raw}:
        raise WebhookAuthError("Unauthorized", 401)


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "llm_model": settings.llm_model,
    }


@app.post("/webhook", response_model=None)
async def webhook(request: Request):
    settings = get_settings()
    raw_body = await request.body()
    headers = _header_map(request)

    try:
        _check_optional_auth(request, settings)
        signed = parse_signed_headers(
            headers,
            leeway_seconds=settings.timestamp_leeway_seconds,
            require_signature=settings.index_require_signature,
        )
        if settings.index_require_signature:
            if not settings.index_webhook_secret:
                return PlainTextResponse("Server misconfigured", status_code=500)
            verify_signature(settings.index_webhook_secret, signed, raw_body)
    except WebhookAuthError as exc:
        return PlainTextResponse(exc.message, status_code=exc.status_code)

    store = _delivery_store(settings)
    store.expire_older_than(max(settings.timestamp_leeway_seconds * 2, 600))
    if store.already_seen(signed.delivery_id):
        return PlainTextResponse("Already received", status_code=200)
    if not store.remember(signed.delivery_id):
        return PlainTextResponse("Already received", status_code=200)

    form = await request.form()
    is_test = signed.is_test or str(form.get("test", "")).lower() == "true"
    if is_test:
        return JSONResponse({"ok": True, "kind": "test"})

    transcription = str(form.get("transcription") or "").strip()
    if not transcription:
        return PlainTextResponse("Empty transcript", status_code=400)

    recorded_at = form.get("recordedAt")
    when = recorded_at_datetime(
        str(recorded_at) if recorded_at is not None else None,
        settings.timezone,
    )
    result = classify_transcript(transcription, when, settings)

    try:
        if result.kind == "task":
            write_inbox_task(
                settings.todo_path,
                transcription,
                when,
                heading=result.heading,
                scheduled=result.scheduled,
            )
        else:
            write_daily_note(
                daily_path_for(settings.daily_dir, when),
                transcription,
                when,
                settings.resolved_daily_template,
                title=result.heading,
                proposed_tasks=result.proposed_tasks,
            )
    except OrgWriteError as exc:
        store.forget(signed.delivery_id)
        return PlainTextResponse(str(exc), status_code=500)

    return JSONResponse({"ok": True, "kind": result.kind})


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "index_org_webhook.app:app",
        host=settings.bind_host,
        port=settings.bind_port,
        factory=False,
    )


def create_app() -> FastAPI:
    return app
