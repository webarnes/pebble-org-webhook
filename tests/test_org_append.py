from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from index_org_webhook.org_append import (
    INBOX_HEADING,
    LOG_HEADING,
    append_under_heading,
    bootstrap_daily,
    insert_after_heading,
    write_daily_note,
    write_inbox_task,
)
from index_org_webhook.org_time import org_active_timestamp, org_inactive_timestamp

WHEN = datetime(2026, 11, 14, 20, 21, tzinfo=ZoneInfo("America/Toronto"))
TEMPLATE = Path(__file__).parent / "fixtures" / "roam.dailies.default.txt"


def test_insert_after_inbox_newest_first() -> None:
    content = "* Recurring Tasks\n** TODO Recurring\n\n* Inbox\n** DONE Old item\n"
    block = "** TODO Call the dentist\n"
    updated = insert_after_heading(content, INBOX_HEADING, block)
    inbox_at = updated.index("* Inbox\n")
    new_at = updated.index("** TODO Call the dentist\n")
    old_at = updated.index("** DONE Old item\n")
    assert inbox_at < new_at < old_at
    assert updated.startswith("* Recurring Tasks")


def test_append_under_log_chronological() -> None:
    content = "* Log\n\n** Walked\n[2026-11-14 Sat 11:51]\n\nNice day\n"
    block = "** AC Repair\n[2026-11-14 Sat 14:51]\n\nRepairman came.\n"
    updated = append_under_heading(content, LOG_HEADING, block)
    assert updated.index("** Walked") < updated.index("** AC Repair")
    assert updated.endswith("Repairman came.\n")


def test_org_active_timestamp_formats() -> None:
    assert org_active_timestamp("2026-11-16") == "<2026-11-16 Mon>"
    assert org_active_timestamp("2026-11-16 09:30") == "<2026-11-16 Mon 09:30>"
    assert org_active_timestamp("2026-11-16T09:30") == "<2026-11-16 Mon 09:30>"
    assert org_active_timestamp(None) is None
    assert org_active_timestamp("   ") is None
    assert org_active_timestamp("next Monday") is None
    assert org_active_timestamp("2026-99-99") is None


def test_write_inbox_task_file(tmp_path: Path) -> None:
    todo = tmp_path / "todo.org"
    todo.write_text("* Recurring Tasks\n\n* Inbox\n** DONE Old\n", encoding="utf-8")
    write_inbox_task(todo, "todo call the dentist", WHEN)
    text = todo.read_text(encoding="utf-8")
    stamp = org_inactive_timestamp(WHEN)
    assert text.index("* Inbox") < text.index("** TODO Call the dentist") < text.index("** DONE Old")
    assert "SCHEDULED:" not in text
    assert f'- Task created on {stamp} from voice recording: "todo call the dentist"' in text
    assert ":LOGBOOK:" in text


def test_write_inbox_task_file_scheduled_and_custom_heading(tmp_path: Path) -> None:
    todo = tmp_path / "todo.org"
    todo.write_text("* Inbox\n** DONE Old\n", encoding="utf-8")
    write_inbox_task(
        todo,
        "remind me to\ncall the dentist on Monday at 9am",
        WHEN,
        heading="Call the dentist",
        scheduled="2026-11-16 09:00",
    )
    text = todo.read_text(encoding="utf-8")
    stamp = org_inactive_timestamp(WHEN)
    expected = (
        "* Inbox\n"
        "** TODO Call the dentist\n"
        "SCHEDULED: <2026-11-16 Mon 09:00>\n"
        ":LOGBOOK:\n"
        f'- Task created on {stamp} from voice recording: "remind me to call the dentist on Monday at 9am"\n'
        ":END:\n"
        "** DONE Old\n"
    )
    assert text == expected


def test_write_daily_creates_from_template(tmp_path: Path) -> None:
    daily = tmp_path / "2026-11-14.org"
    write_daily_note(daily, "The repairman came and cleaned the AC.", WHEN, TEMPLATE)
    text = daily.read_text(encoding="utf-8")
    assert text.startswith(":PROPERTIES:")
    assert ":ID:" in text
    assert "#+title: 2026-11-14" in text
    assert "* Log" in text
    assert "** The repairman came and cleaned the AC" in text
    assert "The repairman came and cleaned the AC." in text


def test_write_daily_note_with_summary_and_proposed_tasks(tmp_path: Path) -> None:
    daily = tmp_path / "2026-11-14.org"
    transcript = "  The repairman cleaned the AC, and we probably need a new filter soon.  "
    write_daily_note(
        daily,
        transcript,
        WHEN,
        TEMPLATE,
        title="AC cleaning and filter check",
        proposed_tasks=("Buy replacement AC filter", "Check filter size"),
    )
    text = daily.read_text(encoding="utf-8")
    stamp = org_inactive_timestamp(WHEN)
    expected_tail = (
        "* Log\n\n"
        "** AC cleaning and filter check\n"
        f"{stamp}\n\n"
        "The repairman cleaned the AC, and we probably need a new filter soon.\n\n"
        "- [ ] Buy replacement AC filter\n"
        "- [ ] Check filter size\n"
    )
    assert text.endswith(expected_tail)


def test_write_daily_note_strips_fillers_from_body(tmp_path: Path) -> None:
    daily = tmp_path / "2026-11-14.org"
    transcript = "um, uh, the repairman came and cleaned the AC."
    write_daily_note(daily, transcript, WHEN, TEMPLATE)
    text = daily.read_text(encoding="utf-8")
    assert "** The repairman came and cleaned the AC" in text
    assert "\nThe repairman came and cleaned the AC.\n" in text
    assert "um" not in text
    assert "uh" not in text


def test_bootstrap_daily_adds_id_and_date() -> None:
    text = bootstrap_daily(TEMPLATE.read_text(encoding="utf-8"), WHEN)
    assert "#+title: 2026-11-14" in text
    assert "%<" not in text
    assert ":ID:" in text
