from types import SimpleNamespace as NS

import pytest

from themis_orca.presets import catalog_choice, diff_configs, preset_snapshot
from themis_orca.workflow import WorkflowError


def preset(name,system=False,**values):
    return NS(name=name,is_system=system,config_keys=lambda:list(values),config_value=values.get)


def test_nested_inheritance_diff_omits_unchanged_and_preserves_lists():
    base = preset("System",True,wall_loops="2",layer_height="0.2",filament_type=["PLA","PETG"])
    mid = preset("Parent",inherits="System",wall_loops="3",layer_height="0.2")
    child = preset("Mine",inherits="Parent",wall_loops="4",layer_height="0.2",filament_type=["ABS","PETG"])
    presets = {p.name:p for p in (base,mid,child)}
    result = preset_snapshot(child,NS(find_preset=presets.get))
    assert result["system"] == "System"
    assert result["overrides"] == {"wall_loops":"4"}
    assert "layer_height" not in result["diff"]
    assert result["diff"]["filament_type"] == ["ABS","PETG"]
    assert "filament_type" in result["unsupported"]
    assert catalog_choice(result,[{"name":"System"}])[0] == "System"
    assert "using catalog" in catalog_choice(result,[{"name":"System"}])[1]


def test_diff_does_not_share_mutable_values_with_preset():
    values = {"list":[1,2]}
    result = diff_configs(values,{"list":[1]})
    result["list"].append(3)
    assert values["list"] == [1,2]


def test_missing_parent_is_flagged_and_inheritance_cycles_are_rejected():
    child = preset("Mine",inherits="Missing")
    result = preset_snapshot(child,NS(find_preset=lambda name:None))
    assert result["system"] is None and result["warning"]
    child = preset("Mine",inherits="Mine")
    with pytest.raises(WorkflowError,match="cycle"):
        preset_snapshot(child,NS(find_preset=lambda name:child))


def test_unsaved_edits_to_a_system_preset_compare_against_its_stored_version():
    stored = preset("System",True,wall_loops="2")
    edited = preset("System",True,wall_loops="5")
    result = preset_snapshot(edited,NS(find_preset=lambda name:stored))
    assert result["overrides"] == {"wall_loops":"5"}
