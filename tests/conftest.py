from __future__ import annotations

from pathlib import Path

import pytest

from index_org_webhook.settings import DEFAULT_LLM_BASE_URL, get_settings

FIXTURE_TEMPLATE = Path(__file__).parent / "fixtures" / "roam.dailies.default.txt"


@pytest.fixture
def org_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    org = tmp_path / "Org"
    templates = org / "templates"
    templates.mkdir(parents=True)
    (templates / "roam.dailies.default.txt").write_text(
        FIXTURE_TEMPLATE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (org / "todo.org").write_text(
        "* Recurring Tasks\n** TODO Recurring\n\n* Inbox\n** DONE Old item\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INDEX_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("INDEX_REQUIRE_SIGNATURE", "true")
    monkeypatch.setenv("ORG_DIRECTORY", str(org))
    monkeypatch.setenv("DELIVERIES_DB", str(tmp_path / "deliveries.db"))
    monkeypatch.setenv("ORG_TIMEZONE", "America/Toronto")
    monkeypatch.setenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    yield org
    get_settings.cache_clear()
