"""Validated requests for current Themis job/project APIs; no host imports."""

from dataclasses import dataclass, field
from math import isfinite


ACTIONS = {"job", "gcode_job", "existing_plate", "existing_objects", "new_plate", "new_objects", "existing_gcode", "new_gcode"}
OVERRIDE_KEYS = frozenset({"enable_support", "support_type", "support_threshold_angle", "support_on_build_plate_only",
    "raft_layers", "brim_type", "brim_width", "sparse_infill_density", "sparse_infill_pattern", "wall_loops",
    "top_shell_layers", "bottom_shell_layers", "layer_height", "ironing_type"})


class WorkflowError(ValueError):
    pass


def positive(value, label):
    if isinstance(value, bool):
        raise WorkflowError(f"Choose a valid {label}.")
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        raise WorkflowError(f"Choose a valid {label}.") from None
    if str(number) != str(value) or number < 1:
        raise WorkflowError(f"Choose a valid {label}.")
    return number


@dataclass(frozen=True)
class SendPlan:
    action: str
    project_id: int | None
    project_name: str
    plate_number: int
    objects: tuple[tuple[str, int], ...]
    quantity: int
    target_keys: tuple[str, ...]
    process: str
    filament: dict
    overrides: dict
    gcode_model: str | None = None
    min_bed_mm: dict | None = None
    filament_map: list | None = None
    target_overrides: dict = field(default_factory=dict)
    printer_preference: dict | None = None

    def job_payload(self, file_id):
        common = {"print_profile": self.process, **self.filament}
        if self.filament_map:
            common["filament_map"] = self.filament_map
        payload = {"uploaded_file_id": file_id, "plate_number": self.plate_number, "printer_configs": [], "model_targets": []}
        for key in self.target_keys:
            if key == "any" or key.startswith("model:"):
                payload["model_targets"].append({"model_uuid": None if key == "any" else key[6:], **common,
                    **({"overrides":self.target_overrides[key]} if key in self.target_overrides else {})})
            else:
                payload["printer_configs"].append({"printer_id": int(key), **common,
                    **({"overrides":self.target_overrides[key]} if key in self.target_overrides else {})})
        if self.overrides:
            payload["overrides"] = {k: ("1" if v else "0") if isinstance(v, bool) else str(v) for k, v in self.overrides.items()}
        if self.min_bed_mm:
            payload["min_bed_mm"] = self.min_bed_mm
        if self.printer_preference:
            payload["printer_preference"] = self.printer_preference
        return payload

    def group_payload(self):
        payload = {"targets": [{"target_key": key, "process_profile": self.process,
            **({"overrides":self.target_overrides[key]} if key in self.target_overrides else {}),
            **({"filament_map":self.filament_map} if self.filament_map else {})} for key in self.target_keys]}
        if self.printer_preference:
            payload["printer_preference"] = self.printer_preference
        if self.overrides:
            payload["overrides"] = {k: ("1" if v else "0") if isinstance(v, bool) else str(v) for k, v in self.overrides.items()}
        return payload

    def item_payloads(self, file_id, group_id):
        common = {"file_id": file_id, "group_id": group_id, **self.filament}
        if self.gcode_model:
            return [{**common, "kind": "gcode", "source_ref": "1", "quantity": self.quantity, "pack_rule": "locked"}]
        if self.action.endswith("objects"):
            return [{**common, "kind": "3mf_object", "source_ref": object_id, "quantity": copies * self.quantity}
                    for object_id, copies in self.objects]
        return [{**common, "kind": "3mf_plate", "source_ref": str(self.plate_number), "quantity": self.quantity,
                 "pack_rule": "locked", **({"min_bed_mm": self.min_bed_mm} if self.min_bed_mm else {})}]


def build_plan(data, snapshot, references):
    if not isinstance(data, dict) or not isinstance(data.get("action"), str) or data.get("action") not in ACTIONS:
        raise WorkflowError("Choose a send action.")
    action = data["action"]
    project_id = None
    name = ""
    if action.startswith("existing"):
        project_id = positive(data.get("project_id"), "project")
        if project_id not in {p.get("id") for p in references.projects}:
            raise WorkflowError("Refresh projects and choose an existing project.")
    if action.startswith("new"):
        name = data.get("project_name", "")
        if not isinstance(name, str) or not name.strip() or len(name) > 255:
            raise WorkflowError("Enter a project name of 1 to 255 characters.")
        name = name.strip()
    quantity = positive(data.get("quantity", 1), "quantity")
    if quantity > 10000 or (action in {"job","gcode_job"} and quantity != 1):
        raise WorkflowError("A plate job has quantity 1; project quantities must be at most 10000.")
    from .gcode import GCodeSnapshot, eligible_model, eligible_printers
    if action.endswith("gcode") or action == "gcode_job":
        if not isinstance(snapshot,GCodeSnapshot):
            raise WorkflowError("Choose a captured G-code export for this action.")
        if data.get("overrides") or data.get("target_overrides") or data.get("filament_map") or data.get("process") or data.get("use_filament") or data.get("targets"):
            raise WorkflowError("G-code settings are already baked in. Eligibility is set automatically from the exported printer profile.")
        model = data.get("gcode_model") or eligible_model(snapshot, references)
        if not isinstance(model,str) or model not in {m.get("id") for m in references.models}:
            raise WorkflowError("Choose a known printer model for this G-code.")
        if action == "gcode_job" or data.get("gcode_model"):
            targets = ("model:"+model,)
        else:
            targets = tuple(str(positive(p.get("id"), "eligible printer")) for p in eligible_printers(snapshot, references, model))
        return SendPlan(action, project_id, name, 1, (), quantity, targets, "", {}, {}, model)
    if isinstance(snapshot, GCodeSnapshot):
        raise WorkflowError("Inspect a geometry plate for this action, or choose a G-code project action.")
    known_objects = {o["id"]: o["instances"] for o in snapshot.objects}
    selected = data.get("object_ids", [])
    if not isinstance(selected, list) or not all(isinstance(o, str) for o in selected):
        raise WorkflowError("Choose valid objects from the inspected plate.")
    if action.endswith("objects") and (not selected or len(set(selected)) != len(selected) or not set(selected) <= known_objects.keys()):
        raise WorkflowError("Choose at least one object from the inspected plate, without duplicates.")
    targets = data.get("targets", ["any"])
    valid = {"any"} | {str(p["id"]) for p in references.printers} | {"model:" + str(m["id"]) for m in references.models}
    if not isinstance(targets, list) or not targets or not all(isinstance(t, str) and t in valid for t in targets):
        raise WorkflowError("Choose eligible printers or models from the refreshed list.")
    if len(set(targets)) != len(targets) or ("any" in targets and len(targets) > 1):
        raise WorkflowError("Choose either Any printer or specific printers/models, without duplicates.")
    process = data.get("process", "")
    if not isinstance(process, str) or (process and process not in {p.get("name") for p in references.catalog.get("process", [])}):
        raise WorkflowError("Choose a process preset from the refreshed catalog, or let Themis decide.")
    filament = {}
    if data.get("use_filament"):
        for key in ("filament_type", "filament_subtype", "filament_color", "filament_manufacturer"):
            value = data.get(key, "")
            if not isinstance(value, str) or len(value) > 255:
                raise WorkflowError("Filament fields must be text of at most 255 characters.")
            if value.strip():
                filament[key] = value.strip()
        if filament.get("filament_type") and not filament.get("filament_subtype"):
            raise WorkflowError("A filament type needs a subtype, such as standard or any.")
    overrides = data.get("overrides", {})
    if not isinstance(overrides, dict) or not set(overrides) <= OVERRIDE_KEYS:
        raise WorkflowError("Overrides must use the supported process setting names listed below the field.")
    if any(not isinstance(v, (str, int, float, bool)) or v is None for v in overrides.values()):
        raise WorkflowError("Override values must be text, numbers, or booleans.")
    if any(isinstance(v, float) and not isfinite(v) for v in overrides.values()):
        raise WorkflowError("Override numbers must be finite.")
    target_overrides = data.get("target_overrides",{})
    if not isinstance(target_overrides,dict) or not set(target_overrides) <= set(targets):
        raise WorkflowError("Target overrides must name eligible selected printers/models.")
    for values in target_overrides.values():
        if not isinstance(values,dict) or not set(values) <= OVERRIDE_KEYS or any(
            not isinstance(v,(str,int,float,bool)) or isinstance(v,float) and not isfinite(v) for v in values.values()):
            raise WorkflowError("Target overrides must use supported keys and finite scalar values.")
    preference = None
    keys = data.get("preference",[])
    if not isinstance(keys,list) or not all(isinstance(k,str) for k in keys) or len(keys) != len(set(keys)) or any(k == "any" or k not in valid for k in keys):
        raise WorkflowError("Choose distinct known printers/models in preference order.")
    if keys:
        preference = {"entries":[k[6:] if k.startswith("model:") else int(k) for k in keys],"strict":data.get("preference_strict") is True}
    elif data.get("preference_strict"):
        raise WorkflowError("Add at least one printer/model before choosing Only these.")
    filament_map = data.get("filament_map")
    if filament_map is not None:
        if not isinstance(filament_map,list) or not filament_map or len(filament_map) > 64:
            raise WorkflowError("Filament requirements must be a non-empty list of at most 64 entries.")
        # A per-model map takes precedence in Themis. Carry common requirements
        # into each entry so enabling presets does not silently discard the rule.
        filament_map = [{**filament, **entry} if isinstance(entry,dict) else entry for entry in filament_map]
        seen = set()
        for entry in filament_map:
            if not isinstance(entry,dict) or set(entry)-{"model_filament","filament_type","filament_subtype","filament_color","filament_manufacturer","filament_profile"}:
                raise WorkflowError("Filament entries must name model_filament and supported material/preset fields.")
            number = positive(entry.get("model_filament"),"model filament number")
            if number > 64 or number in seen:
                raise WorkflowError("Model filament numbers must be distinct and from 1 to 64.")
            seen.add(number)
            if entry.get("filament_type") and not entry.get("filament_subtype"):
                raise WorkflowError("Each filament type needs a subtype, such as standard or any.")
            if any(not isinstance(v,str) or len(v)>255 for k,v in entry.items() if k != "model_filament"):
                raise WorkflowError("Filament fields must be short text values.")
            if entry.get("filament_profile") and entry["filament_profile"] not in {p.get("name") for p in references.catalog.get("filament",[])}:
                raise WorkflowError("Choose filament preset names from the refreshed catalog.")
    requirement = getattr(snapshot, "min_bed_mm", None)
    try:
        margin = float(data.get("margin_mm", 0))
    except (ValueError, TypeError):
        raise WorkflowError("Bed margin must be a finite number from 0 to 100 mm.") from None
    if not isfinite(margin) or not 0 <= margin <= 100:
        raise WorkflowError("Bed margin must be a finite number from 0 to 100 mm.")
    if requirement and not action.endswith("objects"):
        requirement = {**requirement, "x": requirement["x"] + 2 * margin, "y": requirement["y"] + 2 * margin}
    else:
        requirement = None
    return SendPlan(action, project_id, name, snapshot.plate_number,
                    tuple((o, known_objects[o]) for o in selected) if action.endswith("objects") else (),
                    quantity, tuple(targets), process, filament, overrides, min_bed_mm=requirement,
                    filament_map=filament_map,target_overrides=target_overrides,printer_preference=preference)
