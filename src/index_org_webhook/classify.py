from __future__ import annotations

import re
from typing import Literal

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

IMPERATIVE_OPENERS = (
    "call",
    "buy",
    "email",
    "schedule",
    "book",
    "pay",
    "pick up",
    "follow up",
)

_CUE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(cue) for cue in sorted(LEADING_CUES, key=len, reverse=True)) + r")\b[\s,.:;-]*",
    re.IGNORECASE,
)
_IMPERATIVE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(opener) for opener in sorted(IMPERATIVE_OPENERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(r"^(?:um+|uh+|er+|ah+|erm)[,\s]+", re.IGNORECASE)


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


def classify(transcript: str) -> Kind:
    cleaned = strip_fillers(transcript)
    if not cleaned:
        return "note"
    if _CUE_RE.search(cleaned) or _IMPERATIVE_RE.search(cleaned):
        return "task"
    return "note"


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


def _capitalize_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]
