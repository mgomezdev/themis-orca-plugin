from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from themis_orca.gcode import CaptureStore, GCodeSnapshot
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.workflow import build_plan, WorkflowError


MODEL = "cd1581c2-4208-41a9-8028-10da5f05aa80"
OTHER = "cc3e5fea-2edc-4a44-a85a-6853e41de541"
PROFILE = "Printer 0.4 nozzle"


def references():
    return References(projects=[{"id": 7}], models=[{"id": MODEL, "display_name": "Printer"}, {"id": OTHER}],
        mappings={MODEL: [{"provider_plugin_id": "laminus", "machine_profile": PROFILE}]},
        printers=[{"id": 5, "name": "P", "model_uuid": MODEL, "machine_profile": PROFILE},
                  {"id": 6, "model_uuid": MODEL, "machine_profile": "Printer 0.6 nozzle"},
                  {"id": 8, "model_uuid": OTHER, "machine_profile": PROFILE}])


def snapshot():
    return GCodeSnapshot(Path("captured.gcode"), "token", "part.gcode", PROFILE, "digest")


def test_capture_is_immutable_streamed_and_never_edits_the_export(tmp_path):
    store = CaptureStore()
    source = tmp_path / "working.gcode"
    original = b"; original\r\nG28\r\n" * 10000
    source.write_bytes(original)
    row = store.capture(source, tmp_path / "storage", "C:\\exports\\part.gcode", PROFILE)
    assert source.read_bytes() == original
    source.write_bytes(b"new contents")
    assert row.path.read_bytes() == original
    assert row.name == "part.gcode"
    assert row.path.parent == tmp_path / "storage" / "gcode-captures"
    assert store.entries() == [(row, False)]


def test_repeated_export_hook_deduplicates_without_enabling_resubmission(tmp_path):
    store = CaptureStore()
    source = tmp_path / "working.gcode"
    source.write_bytes(b"G28\n")
    row = store.capture(source, tmp_path / "storage", "part.gcode", PROFILE)
    assert store.acquire(row.token) == row
    store.mark_attempted(row.token)
    store.release(row.token)
    assert store.capture(source, tmp_path / "storage", "upload.gcode", PROFILE) == row
    assert len(list(row.path.parent.iterdir())) == 1
    with pytest.raises(WorkflowError, match="already submitted"):
        store.acquire(row.token)


def test_bounded_capture_retention_and_clear_protect_inflight_file(tmp_path):
    store = CaptureStore()
    source = tmp_path / "working.gcode"
    source.write_bytes(b"G28\n")
    active = store.capture(source, tmp_path / "storage", "active.gcode", PROFILE)
    store.acquire(active.token)
    for number in range(10):
        source.write_bytes(f"G1 X{number}\n".encode())
        store.capture(source, tmp_path / "storage", "part.gcode", PROFILE)
    assert len(store.entries()) == 8
    assert active.path.exists()
    store.clear()
    assert store.entries() == [(active, False)]
    store.release(active.token)
    store.clear()
    assert not active.path.exists()
    assert source.exists()


def test_failed_capture_leaves_no_partial_file(tmp_path):
    store = CaptureStore()
    source = tmp_path / "empty.gcode"
    source.touch()
    with pytest.raises(WorkflowError, match="empty"):
        store.capture(source, tmp_path / "storage", "empty.gcode", PROFILE)
    assert not list((tmp_path / "storage" / "gcode-captures").iterdir())
    assert store.entries() == []


@pytest.mark.parametrize("failure", ["missing", "ambiguous", "provider", "substring", "missing_profile", "invalid_model", "no_printer"])
def test_unproven_gcode_eligibility_blocks_the_send(failure):
    refs, row = references(), snapshot()
    if failure == "missing":
        refs.mappings = {}
    elif failure == "ambiguous":
        refs.mappings[OTHER] = refs.mappings[MODEL]
    elif failure == "provider":
        refs.mappings[MODEL][0]["provider_plugin_id"] = "other"
    elif failure == "substring":
        refs.mappings[MODEL][0]["machine_profile"] = "Printer"
    elif failure == "missing_profile":
        row = GCodeSnapshot(row.path, row.token, row.name, "", row.digest)
    elif failure == "invalid_model":
        refs.models = [{"id": "invalid"}]
        refs.mappings = {"invalid": refs.mappings[MODEL]}
    elif failure == "no_printer":
        refs.printers = []
    with pytest.raises(WorkflowError):
        build_plan({"action": "existing_gcode", "project_id": 7}, row, refs)


@pytest.mark.parametrize("action", ["existing_gcode", "new_gcode"])
def test_gcode_project_sequence_sets_file_and_group_eligibility_before_items(action):
    plan = build_plan({"action": action, "project_id": 7, "project_name": "Sliced", "quantity": 3}, snapshot(), references())
    assert plan.gcode_model == MODEL
    assert plan.group_payload() == {"targets": [{"target_key": "5", "process_profile": ""}]}
    assert plan.item_payloads(10, 20) == [{"file_id": 10, "group_id": 20, "kind": "gcode", "source_ref": "1",
                                        "quantity": 3, "pack_rule": "locked"}]
    created_project = [{"id": 7}] if action == "new_gcode" else []
    api = SimpleNamespace(upload=Mock(return_value={"id": 10, "eligibility": {"known": True, "model_uuids": [MODEL]}}),
        write_json=Mock(side_effect=[*created_project, {"id": 20}, plan.group_payload(), {"id": 30}]))
    result = execute_send(api, snapshot(), plan, "send-id")
    assert result["ok"], result
    api.upload.assert_called_once_with(snapshot().path, gcode_model=MODEL)
    assert api.write_json.call_args_list[-1].args == ("POST", "/projects/7/items", plan.item_payloads(10, 20)[0])
    assert all(call.args[1] != "/jobs" for call in api.write_json.call_args_list)


@pytest.mark.parametrize("confirmed", [False, "wrong_model", "group"])
def test_eligibility_must_be_confirmed_before_adding_gcode_to_project(confirmed):
    plan = build_plan({"action": "new_gcode", "project_name": "Sliced"}, snapshot(), references())
    eligibility = {"known": True, "model_uuids": [MODEL]} if confirmed == "group" else {
        "known": confirmed is not False, "model_uuids": [OTHER]}
    api = SimpleNamespace(upload=Mock(return_value={"id": 10, "eligibility": eligibility}),
                          write_json=Mock(side_effect=[{"id": 7}, {"id": 20}, {}]))
    result = execute_send(api, snapshot(), plan, "send-id")
    assert not result["ok"] and "confirm" in result["message"]
    assert not any(c.args[1].endswith("/items") for c in api.write_json.call_args_list)
    if confirmed != "group":
        api.write_json.assert_not_called()


@pytest.mark.parametrize("settings", [{"targets": ["any"]}, {"overrides": {"layer_height": 0.2}},
                                     {"process": "Standard"}, {"use_filament": True}])
def test_gcode_cannot_be_retargeted_or_resliced_by_hidden_geometry_settings(settings):
    with pytest.raises(WorkflowError, match="already baked"):
        build_plan({"action": "existing_gcode", "project_id": 7, **settings}, snapshot(), references())


def test_gcode_bytes_cannot_be_sent_as_geometry():
    with pytest.raises(WorkflowError, match="geometry plate"):
        build_plan({"action": "job"}, snapshot(), references())
