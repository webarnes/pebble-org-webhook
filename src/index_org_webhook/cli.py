from __future__ import annotations

import argparse
from collections.abc import Sequence

from index_org_webhook.classify import ClassificationResult, classify_transcript
from index_org_webhook.org_append import inbox_entry, log_entry
from index_org_webhook.org_time import recorded_at_datetime
from index_org_webhook.settings import get_settings


def _render_preview(transcript: str, when, result: ClassificationResult) -> str:
    if result.kind == "task":
        return inbox_entry(
            transcript,
            when,
            heading=result.heading,
            scheduled=result.scheduled,
        )
    return log_entry(
        transcript,
        when,
        title=result.heading,
        proposed_tasks=result.proposed_tasks,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Prompt for or read a transcript, classify it, and print the result without modifying files."""
    parser = argparse.ArgumentParser(
        description="Test LLM transcript classification without writing Org files.",
    )
    parser.add_argument(
        "transcript",
        nargs="*",
        help="Optional transcript text. If omitted, prompts interactively.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    transcript = " ".join(args.transcript).strip()
    if not transcript:
        try:
            transcript = input("Note or reminder: ").strip()
        except EOFError:
            print("No transcript provided.")
            return 0

    if not transcript:
        print("No transcript provided.")
        return 0

    settings = get_settings()
    if not settings.llm_configured:
        print("Warning: LLM is not configured; using fallback classifier.")

    when = recorded_at_datetime(None, settings.timezone)
    result = classify_transcript(transcript, when, settings)
    preview = _render_preview(transcript, when, result)

    print(f"kind: {result.kind}")
    print(f"heading: {result.heading}")
    print(f"scheduled: {result.scheduled or '(none)'}")
    print(f"proposed_tasks: {list(result.proposed_tasks)}")
    print()
    print("--- Org preview (no files modified) ---")
    print(preview, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
