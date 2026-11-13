from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from themis_orca.client import MutationUncertain
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.workflow import build_plan


@pytest.mark.parametrize("action", ["job", "existing_plate", "existing_objects", "new_plate", "new_objects"])
def test_exact_api_sequence_for_each_action(action):
    snapshot = SimpleNamespace(path=Path("snapshot.3mf"), plate_number=2, objects=({"id": "17", "instances": 2},))
    refs = References(projects=[{"id": 7}])
    plan = build_plan({"action": action, "project_id": 7, "project_name": "P", "object_ids": ["17"]}, snapshot, refs)
    api = SimpleNamespace(upload=Mock(return_value={"id": 10}), write_json=Mock())
    if action == "job":
        api.write_json.side_effect = [{"id": 50}]
    elif action.startswith("new"):
        api.write_json.side_effect = [{"id": 7}, {"id": 20}, {}, {"id": 30}]
    else:
        api.write_json.side_effect = [{"id": 20}, {}, {"id": 30}]
    result = execute_send(api, snapshot, plan, "send-uuid")
    assert result["ok"]
    api.upload.assert_called_once_with(snapshot.path)
    calls = api.write_json.call_args_list
    if action == "job":
        assert calls[0].args[:2] == ("POST", "/jobs")
        assert result["created"]["job_id"] == 50
    else:
        offset = int(action.startswith("new"))
        if offset:
            assert calls[0].args[:2] == ("POST", "/projects")
            assert calls[0].kwargs == {"idempotency_key": "send-uuid"}
            assert calls[0].args[2]["stage"] == "planning"
        assert calls[offset].args[:2] == ("POST", "/projects/7/groups")
        assert calls[offset + 1].args[:2] == ("PATCH", "/projects/7/groups/20")
        assert calls[offset + 2].args[:2] == ("POST", "/projects/7/items")
        assert calls[offset + 2].args[2]["kind"] == ("3mf_object" if action.endswith("objects") else "3mf_plate")
        assert result["created"]["item_ids"] == [30]


def test_partial_import_preserves_created_ids_and_never_retries():
    snapshot = SimpleNamespace(path=Path("snapshot.3mf"), plate_number=1, objects=({"id": "1", "instances": 1}, {"id": "2", "instances": 1}))
    plan = build_plan({"action": "existing_objects", "project_id": 7, "object_ids": ["1", "2"]}, snapshot, References(projects=[{"id": 7}]))
    api = SimpleNamespace(upload=Mock(return_value={"id": 10}), write_json=Mock(side_effect=[{"id": 20}, {}, {"id": 30}, MutationUncertain("Check Themis first.")]))
    result = execute_send(api, snapshot, plan, "send-uuid")
    assert not result["ok"] and result["uncertain"]
    assert result["created"] == {"file_id": 10, "project_id": 7, "group_id": 20, "item_ids": [30]}
    assert api.write_json.call_count == 4


@pytest.mark.parametrize("supported", [False, True])
def test_project_override_support_is_checked_before_writes_and_confirmed(supported):
    snapshot = SimpleNamespace(path=Path("snapshot.3mf"), plate_number=1, objects=())
    plan = build_plan({"action": "existing_plate", "project_id": 7, "overrides": {"wall_loops": 3}}, snapshot, References(projects=[{"id": 7}]))
    api = SimpleNamespace(supports_project_overrides=Mock(return_value=supported), upload=Mock(return_value={"id": 10}),
                          write_json=Mock(side_effect=[{"id": 20}, {"overrides": {"wall_loops": "3"}}, {"id": 30}]))
    result = execute_send(api, snapshot, plan, "send-uuid")
    assert result["ok"] is supported
    if not supported:
        api.upload.assert_not_called()
        api.write_json.assert_not_called()
    else:
        assert api.write_json.call_args_list[1].args[2]["overrides"] == {"wall_loops": "3"}


def test_server_cannot_silently_ignore_project_override_field():
    snapshot = SimpleNamespace(path=Path("snapshot.3mf"), plate_number=1, objects=())
    plan = build_plan({"action": "existing_plate", "project_id": 7, "overrides": {"wall_loops": 3}}, snapshot, References(projects=[{"id": 7}]))
    api = SimpleNamespace(supports_project_overrides=Mock(return_value=True), upload=Mock(return_value={"id": 10}),
                          write_json=Mock(side_effect=[{"id": 20}, {}]))
    result = execute_send(api, snapshot, plan, "send-uuid")
    assert not result["ok"]
    assert "did not confirm" in result["message"]
    assert api.write_json.call_count == 2


def test_send_worker_runs_off_owner_thread_and_rejects_duplicate_start(monkeypatch):
    from threading import Event, get_ident
    from themis_orca.send import BackgroundSend
    import themis_orca.send as module

    entered, release = Event(), Event()
    owner = get_ident()
    def execute(*args):
        assert get_ident() != owner
        entered.set()
        assert release.wait(timeout=2)
        return {"ok": True}
    monkeypatch.setattr(module, "execute_send", execute)
    monkeypatch.setattr(module, "ThemisClient", lambda settings: None)
    sender = BackgroundSend()
    try:
        assert sender.start(None, None, None)
        assert entered.wait(timeout=2)
        assert not sender.start(None, None, None)
    finally:
        release.set()
        sender.worker.join(timeout=2)
    assert not sender.busy
    assert sender.poll() == {"ok": True}
    assert sender.poll() is None
