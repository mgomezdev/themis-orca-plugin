from types import SimpleNamespace
from unittest.mock import Mock

from themis_orca.client import Connection, ThemisError
from themis_orca.references import load_references


def client():
    return SimpleNamespace(
        printer_models=Mock(return_value=[{"id": "model-a", "display_name": "Model A"}]),
        printers=Mock(return_value=[{"id": 1}]), projects=Mock(return_value=[{"id": 2}]),
        catalog=Mock(return_value={"machine": [], "process": [{"name": "Standard"}], "filament": []}),
        slicer_profiles=Mock(return_value=[{"machine_profile": "A 0.4"}]),
    )


def test_reference_data_includes_per_model_mappings():
    api = client()
    data = load_references(api, Connection("staff", False, ()))
    assert data.models[0]["display_name"] == "Model A"
    assert data.printers == [{"id": 1}]
    assert data.projects == [{"id": 2}]
    assert data.catalog["process"] == [{"name": "Standard"}]
    assert data.mappings == {"model-a": [{"machine_profile": "A 0.4"}]}
    api.slicer_profiles.assert_called_once_with("model-a")
    assert not data.errors


def test_missing_read_scopes_skip_requests_but_keep_available_data():
    api = client()
    data = load_references(api, Connection("staff", False, ("printers:read", "laminus:read")))
    api.printer_models.assert_not_called()
    api.printers.assert_not_called()
    api.slicer_profiles.assert_not_called()
    api.catalog.assert_not_called()
    assert data.projects == [{"id": 2}]
    assert "printers:read" in data.errors["models"]
    assert "laminus:read" in data.errors["catalog"]


def test_failed_collection_preserves_other_results_and_hides_raw_error():
    api = client()
    api.projects.side_effect = ThemisError("secret-from-server")
    data = load_references(api, Connection("staff", False, ()))
    assert data.projects == []
    assert data.models
    assert data.catalog
    assert "projects" in data.errors
    assert "secret" not in str(data.errors)


def test_malformed_collections_and_mapping_errors_are_actionable():
    api = client()
    api.printers.return_value = {"unexpected": []}
    api.catalog.return_value = {"machine": [], "process": []}
    api.slicer_profiles.side_effect = ValueError("bad-model-id")
    data = load_references(api, Connection("staff", False, ()))
    assert set(data.errors) == {"printers", "catalog", "mappings"}
    assert data.printers == []
    assert data.catalog == {}
    assert data.models
    assert "bad-model-id" not in str(data.errors)


def test_model_without_id_is_not_requested():
    api = client()
    api.printer_models.return_value = [{"name": "No id"}]
    data = load_references(api, Connection("staff", False, ()))
    api.slicer_profiles.assert_not_called()
    assert "mappings" in data.errors


def test_cancelled_refresh_makes_no_network_requests():
    api = client()
    data = load_references(api, Connection("staff", False, ()), cancelled=lambda: True)
    for action in vars(api).values():
        action.assert_not_called()
    assert not data.errors


def test_cancel_after_first_collection_stops_remaining_requests():
    api = client()
    cancelled = False

    def models():
        nonlocal cancelled
        cancelled = True
        return [{"id": "model-a"}]

    api.printer_models.side_effect = models
    data = load_references(api, Connection("staff", False, ()), cancelled=lambda: cancelled)
    assert data.models == [{"id": "model-a"}]
    api.printers.assert_not_called()
    api.catalog.assert_not_called()
    api.projects.assert_not_called()
    api.slicer_profiles.assert_not_called()
