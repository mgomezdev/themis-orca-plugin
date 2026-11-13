"""Plain-data snapshots of Orca preset inheritance; no live handles escape the callback."""
from copy import deepcopy
import json

from .workflow import OVERRIDE_KEYS, WorkflowError


def diff_configs(current, parent):
    return {k:deepcopy(v) for k,v in current.items() if k not in {"inherits","name","version","setting_id"} and parent.get(k) != v}


def config(preset):
    return {k:preset.config_value(k) for k in preset.config_keys()}


def parent_name(value):
    if isinstance(value,list):
        return str(value[0]) if value else ""
    if not isinstance(value,str):
        return ""
    try:
        decoded = json.loads(value)
        if isinstance(decoded,str):
            return decoded
    except ValueError:
        pass
    return value.strip()


def preset_snapshot(preset, collection):
    own = config(preset)
    current, seen, chain = preset,set(),[]
    while current is not None:
        if current.name in seen or len(seen) >= 32:
            raise WorkflowError("Preset inheritance has a cycle. Repair it in Orca before using preset differences.")
        seen.add(current.name)
        chain.append(current.name)
        if current.is_system:
            stored = collection.find_preset(current.name) or current
            changes = diff_configs(own,config(stored))
            return {"name":preset.name,"system":current.name,"chain":chain,"values":own,"diff":changes,
                    "overrides":{k:v for k,v in changes.items() if k in OVERRIDE_KEYS},
                    "unsupported":sorted(k for k in changes if k not in OVERRIDE_KEYS)}
        current = collection.find_preset(parent_name(current.config_value("inherits")))
    return {"name":preset.name,"system":None,"chain":chain,"values":own,"diff":{},"overrides":{},
            "unsupported":[],"warning":"No system parent found. Choose a catalog preset manually or Ignore."}


def split_values(value):
    if isinstance(value,list):
        return value
    return [p.strip().strip('"') for p in str(value or "").split(";")]


def capture_presets(bundle):
    process = preset_snapshot(bundle.current_process_preset(),bundle.prints)
    machine = preset_snapshot(bundle.current_printer_preset(),bundle.printers)
    colors = split_values(bundle.full_config_value("filament_colour"))
    types = split_values(bundle.full_config_value("filament_type"))
    filaments = []
    for index,preset in enumerate(bundle.current_filament_presets()):
        if preset is None:
            raise WorkflowError("A filament slot has no preset. Repair the slot in Orca before loading defaults.")
        edited = bundle.filaments.edited_preset()
        if edited.name == preset.name:
            preset = edited
        row = preset_snapshot(preset,bundle.filaments)
        values = row["values"]
        row["model_filament"] = index+1
        row["ask"] = {"model_filament":index+1,"filament_type":types[index] if index < len(types) else "",
                      "filament_subtype":"any","filament_color":colors[index] if index < len(colors) else "",
                      "filament_manufacturer":split_values(values.get("filament_vendor"))[0]}
        filaments.append(row)
    return {"machine":machine,"process":process,"filaments":filaments}


def catalog_choice(preset, rows):
    known = {row.get("name") for row in rows}
    for name in preset.get("chain",[]):
        if name in known:
            return name, "" if name == preset["name"] else f"{preset['name']}: using catalog system/parent preset {name}."
    return "",f"{preset.get('name','Preset')}: no catalog match; choose a preset manually or Ignore."
