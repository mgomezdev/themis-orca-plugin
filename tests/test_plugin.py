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
def adapter(monkeypatch, tmp_path):
    from zipfile import ZipFile
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

    class Sender:
        busy = False
        starts = 0
        result = None

        def start(self, settings, snapshot, plan):
            self.starts += 1
            self.plan = plan
            self.busy = True
            return True

        def poll(self):
            result, self.result = self.result, None
            return result

    def export(path):
        with ZipFile(path, "w") as z:
            z.writestr("Metadata/model_settings.config", '<config><object id="17"><metadata key="name" value="Part"/></object>'
                '<plate><metadata key="plater_id" value="3"/><model_instance><metadata key="object_id" value="17"/>'
                '<metadata key="instance_id" value="0"/></model_instance></plate></config>')

    registrations = []
    create = Mock(side_effect=lambda **kwargs: Panel(**kwargs))
    model = SimpleNamespace(current_plate_index=Mock(return_value=2))
    host = SimpleNamespace(
        base=object, plugin=lambda cls: cls,
        script=SimpleNamespace(ScriptPluginCapabilityBase=Capability),
        slicing=SimpleNamespace(SlicingPipelineCapabilityBase=Capability, Step=SimpleNamespace(psGCodePostProcess="export")),
        host=SimpleNamespace(ui=SimpleNamespace(create_dock_panel=create), model=Mock(return_value=model),
                             plugin=SimpleNamespace(storage=lambda: str(tmp_path)), plater=lambda: SimpleNamespace(export_3mf_copy=export)),
        request_permissions=Mock(), register_capability=registrations.append,
        ExecutionResult=SimpleNamespace(success=lambda message: ("success", message)),
    )
    monkeypatch.setitem(sys.modules, "orca", host)
    monkeypatch.delitem(sys.modules, "themis_orca.plugin", raising=False)
    plugin = importlib.import_module("themis_orca.plugin")
    monkeypatch.setattr(plugin, "BackgroundRefresh", Refresh)
    monkeypatch.setattr(plugin, "BackgroundSend", Sender)
    return SimpleNamespace(plugin=plugin, script=plugin.TestConnection(), host=host, create=create, registrations=registrations, model=model)


def opened(adapter):
    adapter.script.execute()
    panel = adapter.script.panel
    return panel, panel.kwargs["on_message"]


def test_registration_preserves_identity_and_requests_only_thread_permission(adapter):
    adapter.plugin.ThemisPlugin().register_capabilities()
    assert adapter.registrations == [adapter.plugin.TestConnection, adapter.plugin.CaptureGCode]
    adapter.host.request_permissions.assert_called_once_with(threading=True)
    assert adapter.script.get_name() == "Themis: Test connection"
    assert adapter.script.get_default_config() == {"url": "", "api_key": ""}


def test_export_hook_captures_export_time_profile_and_bytes_without_ui_or_network(adapter, tmp_path):
    source = tmp_path / "export.gcode"
    source.write_bytes(b"; sliced\r\nG28\r\n")
    ctx = SimpleNamespace(step="export", gcode_path=str(source), output_name="part.gcode",
                          config_value=Mock(return_value="Printer 0.4 nozzle"))
    result = adapter.plugin.CaptureGCode().execute(ctx)
    assert "captured" in result[1]
    ctx.config_value.assert_called_once_with("printer_settings_id")
    [(row, attempted)] = adapter.plugin._captures.entries()
    assert row.profile == "Printer 0.4 nozzle" and not attempted
    assert row.path.read_bytes() == source.read_bytes()
    adapter.create.assert_not_called()
    adapter.host.host.model.assert_not_called()
    assert adapter.script.sender.starts == 0
    # Other slicing seams must not read paths, config, UI, or live graph handles.
    adapter.plugin.CaptureGCode().execute(SimpleNamespace(step="geometry"))
    assert len(adapter.plugin._captures.entries()) == 1


def test_capture_failure_is_safe_and_does_not_break_export(adapter):
    result = adapter.plugin.CaptureGCode().execute(SimpleNamespace(step="export", gcode_path="missing-private-path",
        output_name="part.gcode", config_value=lambda _: "P"))
    assert result[0] == "success"
    panel, send = opened(adapter)
    send({"command": "ready"})
    assert "capture failed" in panel.posts[-1]["capture_error"]
    assert "missing-private-path" not in json.dumps(panel.posts[-1])


def test_gcode_send_uses_capture_without_reading_current_plate_and_cannot_repeat(adapter, tmp_path):
    from test_gcode import references, PROFILE
    script = adapter.script
    script.references = references()
    script.connection = Connection("staff", False, ())
    source = tmp_path / "export.gcode"
    source.write_bytes(b"G28\n")
    row = adapter.plugin._captures.capture(source, tmp_path / "storage", "part.gcode", PROFILE)
    panel, send = opened(adapter)
    adapter.model.current_plate_index.side_effect = RuntimeError("no current plate")
    send({"command": "send", "workflow": {"action": "new_gcode", "project_name": "Sliced", "capture_id": row.token}})
    assert script.sender.starts == 1
    assert script.sender.plan.target_keys == ("5",)
    assert panel.posts[-1]["plate_index"] is None
    assert panel.posts[-1]["captures"][0]["printers"] == ["P"]
    assert str(row.path) not in json.dumps(panel.posts[-1])
    send({"command": "clear_captures"})
    assert row.path.exists() and "in progress" in panel.posts[-1]["notice"]
    script.sender.busy = False
    script.sender.result = {"ok": True, "message": "Added.", "created": {"project_id": 7, "item_ids": [30]}}
    send({"command": "poll"})
    assert script.gcode_inflight is None
    send({"command": "send", "workflow": {"action": "new_gcode", "project_name": "Sliced", "capture_id": row.token}})
    assert script.sender.starts == 1
    assert "already submitted" in panel.posts[-1]["notice"]
    send({"command": "clear_captures"})
    assert panel.posts[-1]["captures"] == [] and not row.path.exists()
    assert source.exists()


def test_gcode_validation_failure_releases_capture_for_corrected_retry(adapter, tmp_path):
    from test_gcode import references, PROFILE
    script = adapter.script
    script.references = references()
    script.references.mappings = {}
    script.connection = Connection("staff", False, ())
    source = tmp_path / "export.gcode"
    source.write_bytes(b"G28\n")
    row = adapter.plugin._captures.capture(source, tmp_path / "storage", "part.gcode", PROFILE)
    panel, send = opened(adapter)
    request = {"command": "send", "workflow": {"action": "existing_gcode", "project_id": 7, "capture_id": row.token}}
    send(request)
    assert script.sender.starts == 0 and "No unique" in panel.posts[-1]["notice"]
    script.references = references()
    send(request)
    assert script.sender.starts == 1


def test_gcode_requires_write_scopes_and_accepts_only_host_capture_tokens(adapter, tmp_path):
    from test_gcode import references, PROFILE
    script = adapter.script
    script.references = references()
    script.connection = Connection("staff", False, ("projects:write",))
    source = tmp_path / "export.gcode"
    source.write_bytes(b"G28\n")
    row = adapter.plugin._captures.capture(source, tmp_path / "storage", "part.gcode", PROFILE)
    panel, send = opened(adapter)
    request = {"command": "send", "workflow": {"action": "new_gcode", "project_name": "Sliced", "capture_id": row.token}}
    send(request)
    assert script.sender.starts == 0 and "projects:write" in panel.posts[-1]["notice"]
    request["workflow"]["capture_id"] = str(source)
    script.connection = Connection("staff", False, ())
    send(request)
    assert script.sender.starts == 0 and "Choose a captured" in panel.posts[-1]["notice"]
    request["workflow"]["capture_id"] = row.token
    send(request)
    assert script.sender.starts == 1


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


def test_inspect_export_and_send_are_explicit_and_use_frozen_plate_copy(adapter):
    panel, send = opened(adapter)
    send({"command": "inspect"})
    state = panel.posts[-1]
    assert state["snapshot"]["plate_number"] == 3
    assert state["snapshot"]["objects"][0]["id"] == "17"
    assert "path" not in state["snapshot"]
    script = adapter.script
    script.references = References(projects=[{"id": 7}])
    script.connection = Connection("staff", False, ())
    send({"command": "send", "workflow": {"action": "existing_objects", "project_id": 7, "object_ids": ["17"]}})
    assert script.sender.starts == 1
    assert script.sender.plan.objects == (("17", 1),)
    assert panel.posts[-1]["send_busy"]
    send({"command": "send", "workflow": {"action": "job"}})
    assert script.sender.starts == 1
    script.sender.busy = False
    script.sender.result = {"ok": True, "message": "Done", "created": {"project_id": 7, "item_ids": [30]}}
    send({"command": "poll"})
    assert panel.posts[-1]["send_result"]["created"]["item_ids"] == [30]
    send({"command": "send", "workflow": {"action": "job"}})
    assert script.sender.starts == 1
    assert "already submitted" in panel.posts[-1]["notice"]


def test_send_blocks_changed_plate_missing_scopes_and_preserves_project_overrides(adapter):
    panel, send = opened(adapter)
    send({"command": "inspect"})
    script = adapter.script
    script.references = References()
    script.connection = Connection("staff", False, ("files:write",))
    send({"command": "send", "workflow": {"action": "job"}})
    assert "files:write" in panel.posts[-1]["notice"]
    script.connection = Connection("staff", False, ())
    adapter.model.current_plate_index.return_value = 1
    send({"command": "send", "workflow": {"action": "job"}})
    assert "plate changed" in panel.posts[-1]["notice"]
    adapter.model.current_plate_index.return_value = 2
    send({"command": "send", "workflow": {"action": "new_plate", "project_name": "P", "overrides": {"wall_loops": 3}}})
    assert script.sender.starts == 1
    assert script.sender.plan.group_payload()["overrides"] == {"wall_loops": "3"}
