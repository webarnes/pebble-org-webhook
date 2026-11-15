from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

from index_org_webhook.org_time import DAY_ABBR, org_active_timestamp
from index_org_webhook.settings import Settings

logger = logging.getLogger(__name__)

Kind = Literal["task", "note"]

FILLER_WORDS = frozenset({"um", "uh", "er", "ah", "umm", "uhh", "erm"})

LEADING_CUES = (
    "todo",
    "to do",
    "task",
    "remind me",
    "don't forget",
    "dont forget",
    "do not forget",
    "i need to",
    "i have to",
    "please remember",
)

_CUE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(cue) for cue in sorted(LEADING_CUES, key=len, reverse=True)) + r")\b[\s,.:;-]*",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(r"^(?:um+|uh+|er+|ah+|erm)[,\s]+", re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)
_CHECKBOX_PREFIX_RE = re.compile(r"^(?:-\s*\[\s*[xX ]?\s*\]\s*|\[\s*[xX ]?\s*\]\s*|-\s+)")

_SYSTEM_PROMPT = """You classify short voice-memo transcripts for a personal Org-mode workflow.

Return ONLY a JSON object with exactly these keys:
- "kind": "task" or "note"
- "heading": string
- "scheduled": string or null
- "proposed_tasks": array of strings

Classification rules:
1. Classify as "task" ONLY if the transcript is a clear, explicit reminder, to-do, or command to do something (e.g., "remind me to...", "todo...", "don't forget to...", "call the dentist tomorrow at 9").
   - "heading": concise imperative task title with filler words and reminder cues ("remind me to", "todo", "don't forget") stripped, first letter capitalized.
   - "scheduled": if the reminder states a CLEAR date or date and time, resolve it relative to the recording timestamp and format as "YYYY-MM-DD" (date only) or "YYYY-MM-DD HH:MM" (24-hour date and time). If there is NO clear date or time, "scheduled" MUST be null.
   - "proposed_tasks": MUST be [].

2. Otherwise classify as "note" (observations, events, ideas, reflections, journal entries, or ambiguous memos that are not clear explicit reminders).
   - "heading": succinct summary of the note (3-8 words, max 72 characters, no trailing period).
   - "scheduled": MUST be null.
   - "proposed_tasks": if the note mentions or implies any potential follow-up action items, list each as a concise imperative task string without "- [ ]" prefixes; otherwise [].
"""


@dataclass(frozen=True)
class ClassificationResult:
    kind: Kind
    heading: str
    scheduled: str | None = None
    proposed_tasks: tuple[str, ...] = ()


def strip_fillers(text: str) -> str:
    cleaned = text.strip()
    while True:
        next_cleaned = _FILLER_RE.sub("", cleaned, count=1)
        if next_cleaned == cleaned:
            words = cleaned.split()
            if words and words[0].rstrip(".,;:!?").lower() in FILLER_WORDS:
                cleaned = " ".join(words[1:])
                continue
            return cleaned
        cleaned = next_cleaned.strip()


def task_heading(transcript: str) -> str:
    cleaned = strip_fillers(transcript)
    stripped = _CUE_RE.sub("", cleaned, count=1).strip()
    stripped = re.sub(r"^to\s+", "", stripped, flags=re.IGNORECASE).strip() or cleaned
    return _capitalize_first(stripped)


def note_title(transcript: str, *, max_len: int = 72) -> str:
    cleaned = strip_fillers(transcript)
    first = re.split(r"[.!?\n]", cleaned, maxsplit=1)[0].strip()
    if ", " in first and len(first) > max_len:
        first = first.split(",", 1)[0].strip()
    if len(first) > max_len:
        clipped = first[: max_len - 1].rsplit(" ", 1)[0]
        first = (clipped or first[: max_len - 1]) + "…"
    return _capitalize_first(first) or "Voice memo"


def fallback_classify(transcript: str) -> ClassificationResult:
    cleaned = _capitalize_first(strip_fillers(transcript))
    single_line = " ".join(cleaned.split())
    heading = single_line if len(single_line) < 70 else note_title(transcript)
    return ClassificationResult(
        kind="note",
        heading=heading,
        scheduled=None,
        proposed_tasks=(),
    )


def _build_messages(transcript: str, when: datetime) -> list[dict[str, str]]:
    recorded = f"{when:%Y-%m-%d} ({DAY_ABBR[when.weekday()]}) {when:%H:%M}"
    tz_label = when.tzname() or str(when.tzinfo or "local")
    user_prompt = (
        f"Recording timestamp: {recorded} {tz_label}\n"
        f"Transcript: {transcript.strip()}"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _extract_json_object(raw_content: str) -> dict[str, Any]:
    text = raw_content.strip()
    fence_match = _FENCE_RE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON must be an object")
    return parsed


def _sanitize_heading(raw_heading: Any, kind: Kind, transcript: str) -> str:
    if isinstance(raw_heading, str):
        collapsed = " ".join(raw_heading.split()).strip()
        if collapsed:
            return _capitalize_first(collapsed)
    return task_heading(transcript) if kind == "task" else note_title(transcript)


def _sanitize_scheduled(raw_scheduled: Any, kind: Kind) -> str | None:
    if kind != "task" or not isinstance(raw_scheduled, str):
        return None
    cleaned = raw_scheduled.strip()
    if not cleaned or org_active_timestamp(cleaned) is None:
        return None
    return cleaned


def _sanitize_proposed_tasks(raw_tasks: Any, kind: Kind) -> tuple[str, ...]:
    if kind != "note" or not isinstance(raw_tasks, list):
        return ()
    cleaned_tasks: list[str] = []
    for item in raw_tasks:
        if not isinstance(item, str):
            continue
        collapsed = " ".join(item.split()).strip()
        stripped = _CHECKBOX_PREFIX_RE.sub("", collapsed).strip()
        if stripped:
            cleaned_tasks.append(stripped)
    return tuple(cleaned_tasks)


def _sanitize_result(data: dict[str, Any], transcript: str) -> ClassificationResult:
    kind = data.get("kind")
    if kind not in ("task", "note"):
        raise ValueError(f"Unexpected classification kind: {kind!r}")
    heading = _sanitize_heading(data.get("heading"), kind, transcript)
    if kind == "note":
        cleaned = _capitalize_first(strip_fillers(transcript))
        single_line = " ".join(cleaned.split())
        if len(single_line) < 70:
            heading = single_line
    return ClassificationResult(
        kind=kind,
        heading=heading,
        scheduled=_sanitize_scheduled(data.get("scheduled"), kind),
        proposed_tasks=_sanitize_proposed_tasks(data.get("proposed_tasks"), kind),
    )


def classify_transcript(
    transcript: str,
    when: datetime,
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> ClassificationResult:
    if not strip_fillers(transcript):
        return fallback_classify(transcript)
    if not settings.llm_configured:
        logger.warning(
            "LLM is not configured (LLM_API_KEY is empty); falling back to daily note"
        )
        return fallback_classify(transcript)

    url = f"{settings.llm_base_url.strip().rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key.strip():
        headers["Authorization"] = f"Bearer {settings.llm_api_key.strip()}"

    body = {
        "model": settings.llm_model,
        "messages": _build_messages(transcript, when),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        if client is None:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as http_client:
                response = http_client.post(url, headers=headers, json=body)
        else:
            response = client.post(
                url,
                headers=headers,
                json=body,
                timeout=settings.llm_timeout_seconds,
            )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("LLM message content must be a string")
        data = _extract_json_object(content)
        result = _sanitize_result(data, transcript)
        logger.info("Classified memo as %s: %s", result.kind, result.heading)
        return result
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip()
        logger.warning(
            "LLM classification failed; falling back to daily note: %s%s",
            exc,
            f" | response: {detail}" if detail else "",
        )
        return fallback_classify(transcript)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("LLM classification failed; falling back to daily note: %s", exc)
        return fallback_classify(transcript)


def _capitalize_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]
