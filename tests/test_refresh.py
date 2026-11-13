from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from themis_orca.client import Connection, ThemisError
from themis_orca.references import References
from themis_orca.refresh import BackgroundRefresh
from themis_orca.settings import Settings
import themis_orca.refresh as module


SETTINGS = Settings("http://themis.test/api/v1", "private-key")


def finish(refresh):
    # Joining is test-only: production polls without waiting on the UI thread.
    refresh._worker.join(timeout=2)
    assert not refresh.busy


def test_runs_network_off_owner_thread_and_delivers_result_once(monkeypatch):
    owner = get_ident()
    connection = Connection("staff", False, ())

    def connect():
        assert get_ident() != owner
        return connection

    monkeypatch.setattr(module, "ThemisClient", lambda _: SimpleNamespace(test_connection=connect))
    monkeypatch.setattr(module, "load_references", lambda *args, **kwargs: References(projects=[{"id": 1}]))
    refresh = BackgroundRefresh()
    assert refresh.start(SETTINGS)
    finish(refresh)
    result = refresh.poll()
    assert result.connection == connection
    assert result.references.projects == [{"id": 1}]
    assert result.error is None
    assert refresh.poll() is None


def test_busy_refresh_cannot_spawn_duplicates_and_cancel_discards_completion(monkeypatch):
    entered, release = Event(), Event()
    loader = Mock()

    def connect():
        entered.set()
        assert release.wait(timeout=2)
        return Connection("staff", False, ())

    monkeypatch.setattr(module, "ThemisClient", lambda _: SimpleNamespace(test_connection=connect))
    monkeypatch.setattr(module, "load_references", loader)
    refresh = BackgroundRefresh()
    try:
        assert refresh.start(SETTINGS)
        assert entered.wait(timeout=2)
        assert refresh.busy
        assert not refresh.start(SETTINGS)
        refresh.cancel()
        assert refresh.poll() is None
    finally:
        release.set()
        finish(refresh)
    loader.assert_not_called()
    assert refresh.poll() is None


@pytest.mark.parametrize(("error", "expected"), [
    (ThemisError("Check the URL."), "Check the URL."),
    (RuntimeError("private-key"), "Could not refresh Themis. Check plugin compatibility and retry."),
])
def test_errors_are_delivered_without_worker_traceback(monkeypatch, error, expected):
    api = SimpleNamespace(test_connection=Mock(side_effect=error))
    monkeypatch.setattr(module, "ThemisClient", lambda _: api)
    refresh = BackgroundRefresh()
    refresh.start(SETTINGS)
    finish(refresh)
    assert refresh.poll().error == expected


def test_failed_thread_start_is_actionable(monkeypatch):
    monkeypatch.setattr(module.Thread, "start", Mock(side_effect=PermissionError("private-key")))
    refresh = BackgroundRefresh()
    assert refresh.start(SETTINGS)
    assert not refresh.busy
    assert refresh.poll().error == "Allow thread access for the Themis plugin in Orca, then retry."


def test_new_refresh_drops_unconsumed_old_result(monkeypatch):
    api = SimpleNamespace(test_connection=Mock(side_effect=ThemisError("old")))
    monkeypatch.setattr(module, "ThemisClient", lambda _: api)
    refresh = BackgroundRefresh()
    refresh.start(SETTINGS)
    finish(refresh)
    api.test_connection.side_effect = ThemisError("new")
    refresh.start(SETTINGS)
    finish(refresh)
    assert refresh.poll().error == "new"
    assert refresh.poll() is None
