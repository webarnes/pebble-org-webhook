from __future__ import annotations

import fcntl
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from index_org_webhook.classify import note_title, task_heading
from index_org_webhook.org_time import org_inactive_timestamp

INBOX_HEADING = "* Inbox"
LOG_HEADING = "* Log"


class OrgWriteError(Exception):
    pass


def _ensure_newline(text: str) -> str:
    if not text.endswith("\n"):
        return text + "\n"
    return text


def atomic_update(path: Path, transform: Callable[[str], str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+", encoding="utf-8") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = transform(original)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, path)


def insert_after_heading(content: str, heading: str, block: str) -> str:
    lines = content.splitlines(keepends=True)
    block_text = _ensure_newline(block)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == heading:
            return "".join(lines[: i + 1]) + block_text + "".join(lines[i + 1 :])
    prefix = _ensure_newline(content) if content else ""
    return prefix + heading + "\n" + block_text


def append_under_heading(content: str, heading: str, block: str) -> str:
    lines = content.splitlines(keepends=True)
    block_text = _ensure_newline(block)
    heading_index = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n") == heading),
        None,
    )
    if heading_index is None:
        prefix = _ensure_newline(content) if content else ""
        return prefix + heading + "\n\n" + block_text

    next_top = None
    for i in range(heading_index + 1, len(lines)):
        stripped = lines[i].rstrip("\n")
        if stripped.startswith("* ") and not stripped.startswith("**"):
            next_top = i
            break
    insert_at = len(lines) if next_top is None else next_top
    prefix = "".join(lines[:insert_at])
    suffix = "".join(lines[insert_at:])
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + block_text + suffix


def inbox_entry(transcript: str, when: datetime) -> str:
    heading = task_heading(transcript)
    stamp = org_inactive_timestamp(when)
    return (
        f"** TODO {heading}\n"
        f":LOGBOOK:\n"
        f"- Task created on {stamp} from Index 01\n"
        f":END:\n"
    )


def log_entry(transcript: str, when: datetime) -> str:
    title = note_title(transcript)
    stamp = org_inactive_timestamp(when)
    body = transcript.strip()
    return f"** {title}\n{stamp}\n\n{body}\n"


def bootstrap_daily(template_text: str, when: datetime) -> str:
    date = when.strftime("%Y-%m-%d")
    text = template_text.replace("%<%Y-%m-%d>", date)
    if not text.lstrip().startswith(":PROPERTIES:"):
        ident = str(uuid.uuid4()).upper()
        text = f":PROPERTIES:\n:ID:       {ident}\n:END:\n{text}"
    text = _ensure_newline(text)
    headings = {line.rstrip() for line in text.splitlines()}
    if LOG_HEADING not in headings:
        text += f"\n{LOG_HEADING}\n"
    return text


def write_inbox_task(todo_path: Path, transcript: str, when: datetime) -> None:
    block = inbox_entry(transcript, when)

    def transform(content: str) -> str:
        headings = {line.rstrip() for line in content.splitlines()}
        if INBOX_HEADING not in headings:
            content = _ensure_newline(content) if content else ""
            content += f"{INBOX_HEADING}\n"
        return insert_after_heading(content, INBOX_HEADING, block)

    atomic_update(todo_path, transform)


def write_daily_note(
    daily_path: Path,
    transcript: str,
    when: datetime,
    template_path: Path,
) -> None:
    block = log_entry(transcript, when)

    def transform(content: str) -> str:
        if not content:
            if not template_path.exists():
                raise OrgWriteError(f"Daily template not found: {template_path}")
            content = bootstrap_daily(template_path.read_text(encoding="utf-8"), when)
        return append_under_heading(content, LOG_HEADING, block)

    atomic_update(daily_path, transform)


def daily_path_for(daily_dir: Path, when: datetime) -> Path:
    return daily_dir / f"{when:%Y-%m-%d}.org"
