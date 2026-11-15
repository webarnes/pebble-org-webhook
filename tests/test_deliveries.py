from pathlib import Path

from index_org_webhook.deliveries import DeliveryStore


def test_remember_is_idempotent(tmp_path: Path) -> None:
    store = DeliveryStore(tmp_path / "deliveries.db")
    assert store.remember("a") is True
    assert store.remember("a") is False
    assert store.already_seen("a") is True


def test_forget_allows_retry(tmp_path: Path) -> None:
    store = DeliveryStore(tmp_path / "deliveries.db")
    store.remember("a")
    store.forget("a")
    assert store.already_seen("a") is False
    assert store.remember("a") is True


def test_expire_old_ids(tmp_path: Path) -> None:
    store = DeliveryStore(tmp_path / "deliveries.db")
    store.remember("old", now=100)
    store.remember("new", now=1000)
    store.expire_older_than(100, now=1000)
    assert store.already_seen("old") is False
    assert store.already_seen("new") is True
