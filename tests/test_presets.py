from types import SimpleNamespace as NS

import pytest

from themis_orca.presets import capture_presets, catalog_choice, diff_configs, preset_snapshot
from themis_orca.material import split_material
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


@pytest.mark.parametrize("raw,expected", [
    ("PLA", ("PLA", "standard")), ("PLA+", ("PLA", "plus")),
    ("PLA Silk", ("PLA", "silk")), ("PA6-CF", ("PA6", "cf")),
    ("PETG-GF", ("PETG", "gf")), ("PLA High Flow", ("PLA", "hf")),
    ("PLA Carbon Fiber", ("PLA", "cf")), ("PLA Basic", ("PLA", "standard")),
    ("PC-ABS", ("PC-ABS", "standard")), ("PETG/PLA", ("PETG/PLA", "standard")),
    (" PLA_Matte ", ("PLA", "matte")), ("PLA Experimental", ("PLA", "experimental")),
    ("", (None, None)), (None, (None, None)),
])
def test_material_field_uses_explicit_variants_and_preserves_blends(raw, expected):
    assert split_material(raw) == expected


def test_capture_preserves_slot_order_and_edited_values_without_guessing_from_names():
    process = preset("Process", True)
    machine = preset("Machine", True)
    saved = [preset("PLA Silk display name", True, filament_vendor=["Vendor A"]),
             preset("Other", True, filament_vendor=["Vendor B"])]
    edited = preset("Other", True, filament_vendor=["Edited vendor"])
    bundle = NS(current_process_preset=lambda:process, current_printer_preset=lambda:machine,
                prints=NS(find_preset=lambda name:process), printers=NS(find_preset=lambda name:machine),
                filaments=NS(find_preset=lambda name:next(p for p in saved if p.name == name), edited_preset=lambda:edited),
                current_filament_presets=lambda:saved,
                full_config_value=lambda key:{"filament_type":["PLA", "PETG-CF"],
                                              "filament_colour":["#112233", "#445566"]}[key])
    rows = capture_presets(bundle)["filaments"]
    assert [r["ask"] for r in rows] == [
        {"model_filament":1, "filament_type":"PLA", "filament_subtype":"standard",
         "filament_color":"#112233", "filament_manufacturer":"Vendor A"},
        {"model_filament":2, "filament_type":"PETG", "filament_subtype":"cf",
         "filament_color":"#445566", "filament_manufacturer":"Edited vendor"},
    ]
    # An incomplete host snapshot must not borrow another slot or invent a wildcard.
    bundle.full_config_value = lambda key:[]
    rows = capture_presets(bundle)["filaments"]
    assert all(r["ask"]["filament_type"] == r["ask"]["filament_subtype"] == "" for r in rows)
    assert all("Review type/subtype" in r["material_warning"] for r in rows)
