from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from index_org_webhook import cli
from index_org_webhook.classify import (
    ClassificationResult,
    classify_transcript,
    fallback_classify,
    note_title,
    strip_fillers,
    task_heading,
)
from index_org_webhook.settings import Settings, get_settings

WHEN = datetime(2026, 11, 14, 20, 21, tzinfo=ZoneInfo("America/Toronto"))


def _llm_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "llm_api_key": "test-api-key",
        "llm_timeout_seconds": 5.0,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type]


def _mock_client(content: str, *, status_code: int = 200, captured: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(
            status_code,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_strip_fillers_and_heuristic_helpers() -> None:
    assert strip_fillers("um, uh call the dentist") == "call the dentist"
    assert task_heading("todo call the dentist") == "Call the dentist"
    assert task_heading("Remind me to take out the compost") == "Take out the compost"
    assert note_title("Walked Arrowhead Trail. It was icy.") == "Walked Arrowhead Trail"
    long = "a " * 80
    title = note_title(long)
    assert len(title) <= 73
    assert title.endswith("…")


def test_classify_unscheduled_task() -> None:
    captured: list[httpx.Request] = []
    client = _mock_client(
        json.dumps(
            {
                "kind": "task",
                "heading": "call the dentist",
                "scheduled": None,
                "proposed_tasks": ["should be ignored"],
            }
        ),
        captured=captured,
    )
    settings = _llm_settings()
    result = classify_transcript("Remind me to call the dentist", WHEN, settings, client=client)

    assert result == ClassificationResult(
        kind="task",
        heading="Call the dentist",
        scheduled=None,
        proposed_tasks=(),
    )
    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert req.headers["Authorization"] == "Bearer test-api-key"
    body = json.loads(req.content)
    assert body["model"] == "gemini-3.8-flash"
    assert "2026-11-14 (Sat) 20:21" in body["messages"][1]["content"]
    assert "Remind me to call the dentist" in body["messages"][1]["content"]


def test_classify_scheduled_task_date_only_and_datetime() -> None:
    date_only_client = _mock_client(
        json.dumps(
            {
                "kind": "task",
                "heading": "File taxes",
                "scheduled": "2026-11-16",
                "proposed_tasks": [],
            }
        )
    )
    res_date = classify_transcript("Remind me to file taxes on Monday", WHEN, _llm_settings(), client=date_only_client)
    assert res_date == ClassificationResult(kind="task", heading="File taxes", scheduled="2026-11-16")

    datetime_client = _mock_client(
        json.dumps(
            {
                "kind": "task",
                "heading": "Call the vet",
                "scheduled": "2026-11-16 09:00",
                "proposed_tasks": [],
            }
        )
    )
    res_dt = classify_transcript(
        "Don't forget to call the vet Monday at 9am",
        WHEN,
        _llm_settings(),
        client=datetime_client,
    )
    assert res_dt == ClassificationResult(kind="task", heading="Call the vet", scheduled="2026-11-16 09:00")


def test_classify_note_without_and_with_proposed_tasks() -> None:
    plain_note_client = _mock_client(
        json.dumps(
            {
                "kind": "note",
                "heading": "Arrowhead Trail morning walk",
                "scheduled": "2026-11-16",
                "proposed_tasks": [],
            }
        )
    )
    plain = classify_transcript(
        "Walked Arrowhead Trail this morning. It was brisk.",
        WHEN,
        _llm_settings(),
        client=plain_note_client,
    )
    assert plain == ClassificationResult(
        kind="note",
        heading="Arrowhead Trail morning walk",
        scheduled=None,
        proposed_tasks=(),
    )

    action_note_client = _mock_client(
        json.dumps(
            {
                "kind": "note",
                "heading": "AC cleaning visit and filter wear",
                "scheduled": None,
                "proposed_tasks": [
                    "- [ ] Buy a replacement AC filter",
                    "[ ] Measure current filter dimensions",
                    "- Email HVAC tech receipt",
                    "   ",
                ],
            }
        )
    )
    with_actions = classify_transcript(
        "The repairman cleaned the AC and mentioned the filter looks worn out.",
        WHEN,
        _llm_settings(),
        client=action_note_client,
    )
    assert with_actions == ClassificationResult(
        kind="note",
        heading="AC cleaning visit and filter wear",
        scheduled=None,
        proposed_tasks=(
            "Buy a replacement AC filter",
            "Measure current filter dimensions",
            "Email HVAC tech receipt",
        ),
    )


def test_classify_handles_code_fences_and_local_endpoint_without_key() -> None:
    captured: list[httpx.Request] = []
    fenced = '```json\n{"kind": "note", "heading": "Sunday readings reflection", "scheduled": null, "proposed_tasks": []}\n```'
    client = _mock_client(fenced, captured=captured)
    local_settings = _llm_settings(
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_api_key="",
        llm_model="qwen2.5:7b",
    )
    assert local_settings.llm_configured is True

    result = classify_transcript("Thoughts about Sunday readings", WHEN, local_settings, client=client)
    assert result == ClassificationResult(kind="note", heading="Sunday readings reflection")
    assert "Authorization" not in captured[0].headers
    assert str(captured[0].url) == "http://127.0.0.1:11434/v1/chat/completions"


def test_classify_sanitizes_invalid_scheduled_and_empty_heading() -> None:
    client = _mock_client(
        json.dumps(
            {
                "kind": "task",
                "heading": "   ",
                "scheduled": "next Tuesday sometime",
                "proposed_tasks": [],
            }
        )
    )
    result = classify_transcript("todo call the dentist", WHEN, _llm_settings(), client=client)
    assert result == ClassificationResult(kind="task", heading="Call the dentist", scheduled=None)


def test_classify_fallbacks_on_unconfigured_http_timeout_and_bad_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transcript = "The repairman came and cleaned the AC. Everything works now."
    expected = fallback_classify(transcript)

    unconfigured = _llm_settings(llm_api_key="")
    assert unconfigured.llm_configured is False
    assert classify_transcript(transcript, WHEN, unconfigured) == expected

    http_error_client = _mock_client("bad gateway detail", status_code=502)
    with caplog.at_level("WARNING"):
        assert classify_transcript(transcript, WHEN, _llm_settings(), client=http_error_client) == expected
    assert "bad gateway detail" in caplog.text

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    timeout_client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    assert classify_transcript(transcript, WHEN, _llm_settings(), client=timeout_client) == expected

    bad_json_client = _mock_client("not valid json")
    assert classify_transcript(transcript, WHEN, _llm_settings(), client=bad_json_client) == expected

    bad_kind_client = _mock_client(json.dumps({"kind": "reminder", "heading": "Hi"}))
    assert classify_transcript(transcript, WHEN, _llm_settings(), client=bad_kind_client) == expected


def _patch_cli_llm(monkeypatch: pytest.MonkeyPatch, org_dir: Path, payload: dict[str, object]) -> None:
    monkeypatch.setenv("ORG_DIRECTORY", str(org_dir))
    monkeypatch.setenv("LLM_API_KEY", "test-api-key")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
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


def test_cli_prompts_and_prints_task_without_writing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    org_dir = tmp_path / "Org"
    org_dir.mkdir()
    _patch_cli_llm(
        monkeypatch,
        org_dir,
        {
            "kind": "task",
            "heading": "Call the dentist",
            "scheduled": "2026-11-16 09:00",
            "proposed_tasks": [],
        },
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "Remind me to call the dentist Monday at 9am")

    exit_code = cli.main([])
    get_settings.cache_clear()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "kind: task" in out
    assert "heading: Call the dentist" in out
    assert "scheduled: 2026-11-16 09:00" in out
    assert "** TODO Call the dentist" in out
    assert "SCHEDULED: <2026-11-16 Mon 09:00>" in out
    assert list(org_dir.rglob("*")) == []


def test_cli_prints_note_with_proposed_tasks_without_writing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    org_dir = tmp_path / "Org"
    org_dir.mkdir()
    _patch_cli_llm(
        monkeypatch,
        org_dir,
        {
            "kind": "note",
            "heading": "AC filter wear noted",
            "scheduled": None,
            "proposed_tasks": ["Buy replacement AC filter"],
        },
    )

    exit_code = cli.main(["The repairman cleaned the AC and said the filter is worn."])
    get_settings.cache_clear()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "kind: note" in out
    assert "heading: AC filter wear noted" in out
    assert "scheduled: (none)" in out
    assert "proposed_tasks: ['Buy replacement AC filter']" in out
    assert "** AC filter wear noted" in out
    assert "- [ ] Buy replacement AC filter" in out
    assert list(org_dir.rglob("*")) == []


def test_cli_handles_empty_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "   ")
    assert cli.main([]) == 0
    assert "No transcript provided." in capsys.readouterr().out
