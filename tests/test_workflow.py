from types import SimpleNamespace

import pytest

from themis_orca.references import References
from themis_orca.workflow import build_plan, WorkflowError


@pytest.fixture
def context():
    return (SimpleNamespace(plate_number=2, objects=({"id": "17", "instances": 2}, {"id": "25", "instances": 1})),
            References(projects=[{"id": 7}], printers=[{"id": 5}], models=[{"id": "model-a"}],
                       catalog={"process": [{"name": "Standard"}]}))


@pytest.mark.parametrize("action", ["job", "existing_plate", "existing_objects", "new_plate", "new_objects"])
def test_all_requested_destinations(context, action):
    snapshot, refs = context
    plan = build_plan({"action": action, "project_id": 7, "project_name": "My project", "object_ids": ["17"]}, snapshot, refs)
    assert plan.plate_number == 2
    if action == "job":
        assert plan.job_payload(10) == {"uploaded_file_id": 10, "plate_number": 2, "printer_configs": [],
                                       "model_targets": [{"model_uuid": None, "print_profile": ""}]}
    else:
        items = plan.item_payloads(10, 20)
        assert items[0]["kind"] == ("3mf_object" if action.endswith("objects") else "3mf_plate")
        assert items[0]["source_ref"] == ("17" if action.endswith("objects") else "2")
        assert items[0]["group_id"] == 20
        assert plan.project_id == (7 if action.startswith("existing") else None)


def test_target_settings_reach_job_and_import_group(context):
    plan = build_plan({"action": "job", "targets": ["5", "model:model-a"], "process": "Standard",
                       "use_filament": True, "filament_type": "PLA", "filament_subtype": "standard",
                       "filament_color": "red", "filament_manufacturer": "Vendor",
                       "overrides": {"layer_height": 0.2, "enable_support": False}}, *context)
    payload = plan.job_payload(10)
    assert payload["printer_configs"][0]["printer_id"] == 5
    assert payload["model_targets"][0]["model_uuid"] == "model-a"
    assert payload["model_targets"][0]["filament_type"] == "PLA"
    assert payload["printer_configs"][0]["print_profile"] == "Standard"
    assert payload["overrides"] == {"layer_height": "0.2", "enable_support": "0"}
    assert plan.group_payload() == {"targets": [{"target_key": "5", "process_profile": "Standard"},
                                                {"target_key": "model:model-a", "process_profile": "Standard"}],
                                    "overrides": {"layer_height": "0.2", "enable_support": "0"}}


def test_object_quantities_include_only_selected_plate_instances(context):
    plan = build_plan({"action": "new_objects", "project_name": "Parts", "object_ids": ["17", "25"], "quantity": 3}, *context)
    assert [item["quantity"] for item in plan.item_payloads(1, 2)] == [6, 3]


def test_ignored_filament_fields_are_omitted(context):
    plan = build_plan({"action": "new_plate", "project_name": "P", "use_filament": False, "filament_type": "PLA"}, *context)
    assert "filament_type" not in plan.item_payloads(1, 2)[0]


def test_plate_action_ignores_hidden_object_selection(context):
    plan = build_plan({"action": "job", "object_ids": ["old-object-id"]}, *context)
    assert plan.objects == ()


@pytest.mark.parametrize("changes", [
    {"action": "unknown"}, {"action": []}, {"action": "existing_plate", "project_id": 99},
    {"action": "new_plate", "project_name": ""}, {"quantity": 0}, {"quantity": True}, {"quantity": 2},
    {"targets": []}, {"targets": ["any", "5"]}, {"targets": ["99"]}, {"process": "Unknown"},
    {"use_filament": True, "filament_type": "PLA"}, {"overrides": {"unrecognized_key": 1}},
    {"overrides": {"layer_height": float("nan")}},
    {"action": "new_objects", "project_name": "P", "object_ids": []},
    {"action": "new_objects", "project_name": "P", "object_ids": ["99"]},
    {"action": "new_objects", "project_name": "P", "object_ids": ["17", "17"]},
])
def test_invalid_workflows_are_rejected_before_writes(context, changes):
    with pytest.raises(WorkflowError):
        build_plan({"action": "job", **changes}, *context)


def test_project_overrides_are_preserved_in_group_request(context):
    plan = build_plan({"action": "new_plate", "project_name": "P", "overrides": {"wall_loops": 3}}, *context)
    assert plan.group_payload()["overrides"] == {"wall_loops": "3"}
