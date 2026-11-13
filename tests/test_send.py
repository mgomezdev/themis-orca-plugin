from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from themis_orca.client import MutationUncertain,Connection
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.workflow import build_plan

SEND = "cc3e5fea-2edc-4a44-a85a-6853e41de541"


def context(action="job"):
    snapshot = SimpleNamespace(path=Path("snapshot.3mf"),plate_number=2,objects=({"id":"17","instances":2},))
    plan = build_plan({"action":action,"project_id":7,"project_name":"P","object_ids":["17"]},snapshot,References(projects=[{"id":7}]))
    return snapshot,plan


def api(created=None):
    return SimpleNamespace(test_connection=Mock(return_value=Connection("staff",False,())),supports_slicer_sends=Mock(return_value=True),upload=Mock(return_value={"id":10}),
        write_json=Mock(return_value={"send_id":SEND,"created":created or {"job_id":50},"can_update":True,"status":"queued"}))


@pytest.mark.parametrize("action",["job","existing_plate","existing_objects","new_plate","new_objects"])
def test_each_action_commits_one_atomic_send_after_upload(action):
    snapshot,plan = context(action)
    client = api({"job_id":50} if action == "job" else {"project_id":7,"group_id":20,"item_ids":[30]})
    prepared = Mock()
    result = execute_send(client,snapshot,plan,SEND,on_prepared=prepared)
    assert result["ok"] and result["can_update"]
    client.upload.assert_called_once_with(snapshot.path)
    method,path,payload = client.write_json.call_args.args
    assert (method,path) == ("POST","/slicer-sends") and client.write_json.call_count == 1
    assert payload["send_id"] == SEND and payload["source_app"] == "orcaslicer"
    prepared.assert_called_once_with(payload)
    if action == "job":
        assert payload["kind"] == "job" and payload["job"]["plate_number"] == 2
    else:
        assert payload["kind"] == "project"
        assert payload["items"][0]["kind"] == ("3mf_object" if action.endswith("objects") else "3mf_plate")
        assert "group_id" not in payload["items"][0]
        assert payload.get("project_id") == (7 if action.startswith("existing") else None)


def test_old_server_is_rejected_before_any_write():
    snapshot,plan = context()
    client = api(); client.supports_slicer_sends.return_value = False
    result = execute_send(client,snapshot,plan,SEND)
    assert not result["ok"] and "Update Themis" in result["message"]
    client.upload.assert_not_called(); client.write_json.assert_not_called()


@pytest.mark.parametrize("connection",[Connection("admin",True,()),Connection("staff",False,("files:write",))])
def test_mutations_require_a_verified_key_and_current_scopes(connection):
    snapshot,plan = context(); client = api()
    client.test_connection.return_value = connection
    result = execute_send(client,snapshot,plan,SEND)
    assert not result["ok"]
    client.upload.assert_not_called(); client.write_json.assert_not_called()


def test_uncertain_send_has_frozen_request_and_retry_never_reuploads_or_changes_identity():
    snapshot,plan = context("new_plate")
    client = api(); client.write_json.side_effect = MutationUncertain("Retry saved send.")
    saved = []
    result = execute_send(client,snapshot,plan,SEND,on_prepared=saved.append)
    assert not result["ok"] and result["uncertain"] and len(saved) == 1
    assert client.write_json.call_count == 1
    client = api({"project_id":7,"group_id":20,"item_ids":[30]})
    assert execute_send(client,None,None,SEND,prepared=saved[0])["ok"]
    client.upload.assert_not_called()
    assert client.write_json.call_args.args[2] is saved[0]


def test_update_and_target_settings_are_in_saved_request():
    snapshot,_ = context()
    plan = build_plan({"action":"job","overrides":{"wall_loops":3},"targets":["5"],
        "target_overrides":{"5":{"layer_height":"0.1"}},"preference":["5"],"preference_strict":True},
        snapshot,References(printers=[{"id":5}]))
    client = api()
    assert execute_send(client,snapshot,plan,SEND,update=True)["ok"]
    body = client.write_json.call_args.args[2]
    assert body["update"] and body["job"]["printer_configs"][0]["overrides"] == {"layer_height":"0.1"}
    assert body["job"]["printer_preference"] == {"entries":[5],"strict":True}


@pytest.mark.parametrize("saved",[False,True])
def test_worker_waits_for_saved_identity_acknowledgement_before_posting(monkeypatch,saved):
    from themis_orca.send import BackgroundSend
    import themis_orca.send as module
    snapshot,plan = context(); client = api()
    monkeypatch.setattr(module,"ThemisClient",lambda settings:client)
    sender = BackgroundSend()
    assert sender.start(None,snapshot,plan,send_id=SEND)
    prepared = sender.results.get(timeout=2)
    assert prepared["stage"] == "prepared" and prepared["send_id"] == SEND
    client.write_json.assert_not_called()
    sender.acknowledge(saved)
    sender.worker.join(timeout=2)
    assert sender.poll()["ok"] is saved
    assert client.write_json.call_count == int(saved)
