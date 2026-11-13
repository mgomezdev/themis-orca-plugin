"""Contract tests against an Orca stub; real-host verification remains pending."""

import importlib
import json
import sys
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from themis_orca.client import Connection
from themis_orca.references import References
from themis_orca.refresh import RefreshResult


@pytest.fixture
def adapter(monkeypatch):
    class Capability:
        raw_config = '{"url":"http://themis.test","api_key":"private-key"}'

        def get_config(self):
            return self.raw_config

        def save_config(self, value):
            self.raw_config = value
            return True

    class Panel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.posts = []
            self.open = True
            self.shows = 0

        def is_open(self):
            return self.open

        def show(self):
            self.shows += 1

        def post(self, message):
            self.posts.append(message)

    class Refresh:
        busy = False
        result = None
        starts = 0
        cancellations = 0

        def start(self, settings):
            if self.busy:
                return False
            self.starts += 1
            self.settings = settings
            self.busy = True
            return True

        def poll(self):
            result, self.result = self.result, None
            return result

        def cancel(self):
            self.cancellations += 1
            self.result = None

    registrations = []
    create = Mock(side_effect=lambda **kwargs: Panel(**kwargs))
    model = SimpleNamespace(current_plate_index=Mock(return_value=2))
    host = SimpleNamespace(
        base=object, plugin=lambda cls: cls,
        script=SimpleNamespace(ScriptPluginCapabilityBase=Capability),
        host=SimpleNamespace(ui=SimpleNamespace(create_dock_panel=create), model=Mock(return_value=model)),
        request_permissions=Mock(), register_capability=registrations.append,
        ExecutionResult=SimpleNamespace(success=lambda message: ("success", message)),
    )
    monkeypatch.setitem(sys.modules, "orca", host)
    monkeypatch.delitem(sys.modules, "themis_orca.plugin", raising=False)
    plugin = importlib.import_module("themis_orca.plugin")
    monkeypatch.setattr(plugin, "BackgroundRefresh", Refresh)
    return SimpleNamespace(plugin=plugin, script=plugin.TestConnection(), host=host, create=create, registrations=registrations, model=model)


def opened(adapter):
    adapter.script.execute()
    panel = adapter.script.panel
    return panel, panel.kwargs["on_message"]


def test_registration_preserves_identity_and_requests_only_thread_permission(adapter):
    adapter.plugin.ThemisPlugin().register_capabilities()
    assert adapter.registrations == [adapter.plugin.TestConnection]
    adapter.host.request_permissions.assert_called_once_with(threading=True)
    assert adapter.script.get_name() == "Themis: Test connection"
    assert adapter.script.get_default_config() == {"url": "", "api_key": ""}


def test_open_reuses_panel_without_reading_live_model_or_starting_network(adapter):
    script = adapter.script
    assert script.execute() == ("success", "Themis panel opened.")
    panel = script.panel
    assert script.execute() == ("success", "Themis panel is already open.")
    assert script.panel is panel
    assert panel.shows == 1
    adapter.create.assert_called_once()
    assert panel.kwargs["dock"] == "right"
    assert 'type="password"' in panel.kwargs["html"]
    adapter.host.host.model.assert_not_called()
    assert script.refresh.starts == 0
    assert panel.posts == []


def test_concurrent_script_runs_open_only_one_panel(adapter):
    workers = [Thread(target=adapter.script.execute) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    adapter.create.assert_called_once()


def test_ready_and_poll_report_live_plate_without_exposing_key(adapter):
    panel, send = opened(adapter)
    send({"command": "ready"})
    state = panel.posts[-1]
    assert state["plate_index"] == 2
    assert state["configured"] and state["key_set"]
    assert state["url"] == "http://themis.test/api/v1"
    assert "private-key" not in json.dumps(state)
    adapter.model.current_plate_index.return_value = 4
    send({"command": "poll"})
    assert panel.posts[-1]["plate_index"] == 4
    assert adapter.script.refresh.starts == 0


@pytest.mark.parametrize("value", [-1, None, True])
def test_unknown_plate_is_not_displayed_as_plate_one(adapter, value):
    adapter.model.current_plate_index.return_value = value
    panel, send = opened(adapter)
    send({"command": "ready"})
    assert panel.posts[-1]["plate_index"] is None


def test_host_model_unavailable_does_not_break_settings(adapter):
    adapter.host.host.model.side_effect = RuntimeError("Not ready")
    panel, send = opened(adapter)
    send({"command": "ready"})
    assert panel.posts[-1]["plate_index"] is None
    assert panel.posts[-1]["configured"]


def test_save_keeps_existing_key_and_host_config_fields_without_connecting(adapter):
    script = adapter.script
    script.raw_config = '{"url":"http://old.test","api_key":"private-key","future_setting":true}'
    panel, send = opened(adapter)
    send({"command": "save", "url": "https://new.test/themis", "api_key": ""})
    assert json.loads(script.raw_config) == {"url": "https://new.test/themis/api/v1", "api_key": "private-key", "future_setting": True}
    assert script.refresh.starts == 0
    assert panel.posts[-1]["settings_saved"]
    assert "private-key" not in json.dumps(panel.posts[-1])


def test_save_replaces_key_and_forget_clears_it(adapter):
    panel, send = opened(adapter)
    send({"command": "save", "url": "https://new.test", "api_key": "replacement-key"})
    assert json.loads(adapter.script.raw_config)["api_key"] == "replacement-key"
    send({"command": "forget"})
    assert json.loads(adapter.script.raw_config)["api_key"] == ""
    assert not panel.posts[-1]["key_set"] and not panel.posts[-1]["configured"]
    assert not panel.posts[-1]["counts"]
    assert "replacement-key" not in json.dumps(panel.posts)


def test_invalid_url_and_failed_save_leave_settings_unchanged(adapter, monkeypatch):
    panel, send = opened(adapter)
    original = adapter.script.raw_config
    send({"command": "save", "url": "https://user:private-key@other.test", "api_key": ""})
    assert adapter.script.raw_config == original
    assert "credentials" in panel.posts[-1]["notice"]
    assert "private-key" not in json.dumps(panel.posts)
    monkeypatch.setattr(adapter.script, "save_config", lambda raw: False)
    send({"command": "save", "url": "https://new.test", "api_key": ""})
    assert adapter.script.raw_config == original
    assert "could not save" in panel.posts[-1]["notice"]


def test_refresh_is_explicit_and_protects_settings_while_busy(adapter):
    panel, send = opened(adapter)
    send({"command": "refresh"})
    assert adapter.script.refresh.starts == 1
    assert adapter.script.refresh.settings.api_key == "private-key"
    assert panel.posts[-1]["busy"]
    original = adapter.script.raw_config
    send({"command": "refresh"})
    send({"command": "save", "url": "https://other.test", "api_key": ""})
    send({"command": "forget"})
    assert adapter.script.refresh.starts == 1
    assert adapter.script.raw_config == original
    assert "Wait" in panel.posts[-1]["notice"]


def test_refresh_completion_reports_counts_partial_errors_and_scopes(adapter):
    panel, send = opened(adapter)
    refresh = adapter.script.refresh
    send({"command": "refresh"})
    refresh.busy = False
    refresh.result = RefreshResult(Connection("staff", False, ("jobs:write",)), References(
        models=[{"id": "model"}], printers=[{"id": 1}], projects=[{"id": 2}],
        catalog={"process": [{"name": "Standard"}]}, mappings={"model": [{"name": "A"}]},
        errors={"catalog": "Enable laminus:read, then refresh."},
    ))
    send({"command": "poll"})
    state = panel.posts[-1]
    assert "jobs:write" in state["status"]
    assert state["counts"]["Printer models"] == 1
    assert state["counts"]["Process presets"] == 1
    assert state["counts"]["Slicer mappings"] == 1
    assert "laminus:read" in state["errors"]["catalog"]
    assert "private-key" not in json.dumps(state)


def test_refresh_error_and_cancel_are_visible(adapter):
    panel, send = opened(adapter)
    adapter.script.refresh.result = RefreshResult(error="Check the API key.")
    send({"command": "poll"})
    assert panel.posts[-1]["status"] == "Check the API key."
    send({"command": "cancel"})
    assert "cancelled" in panel.posts[-1]["status"]
    assert adapter.script.refresh.cancellations == 1


def test_old_page_cannot_modify_or_close_reopened_panel(adapter):
    first, send_old = opened(adapter)
    first.kwargs["on_close"]()
    assert adapter.script.panel is None
    second, send_new = opened(adapter)
    original = adapter.script.raw_config
    send_old({"command": "forget"})
    first.kwargs["on_close"]()
    assert adapter.script.raw_config == original
    assert adapter.script.panel is second
    send_new({"command": "ready"})
    assert second.posts[-1]["configured"]


def test_unload_cancels_and_ignores_late_messages(adapter):
    panel, send = opened(adapter)
    adapter.script.on_unload()
    assert adapter.script.refresh.cancellations == 1
    assert adapter.script.panel is None
    send({"command": "forget"})
    assert panel.posts == []


@pytest.mark.parametrize("message", [None, [], {"command": "unsupported"}])
def test_invalid_messages_get_actionable_reply(adapter, message):
    panel, send = opened(adapter)
    send(message)
    assert "panel" in panel.posts[-1]["notice"]


def test_arbitrary_host_exceptions_cannot_expose_key(adapter, monkeypatch):
    panel, send = opened(adapter)
    monkeypatch.setattr(adapter.script, "save_config", Mock(side_effect=ValueError("private-key")))
    send({"command": "save", "url": "https://other.test", "api_key": ""})
    assert "could not complete" in panel.posts[-1]["notice"]
    assert "private-key" not in json.dumps(panel.posts)
