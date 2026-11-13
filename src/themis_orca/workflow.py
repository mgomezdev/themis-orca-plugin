"""Validated requests for current Themis job/project APIs; no host imports."""

from dataclasses import dataclass
from math import isfinite


ACTIONS = {"job", "existing_plate", "existing_objects", "new_plate", "new_objects", "existing_gcode", "new_gcode"}
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

    def job_payload(self, file_id):
        common = {"print_profile": self.process, **self.filament}
        payload = {"uploaded_file_id": file_id, "plate_number": self.plate_number, "printer_configs": [], "model_targets": []}
        for key in self.target_keys:
            if key == "any" or key.startswith("model:"):
                payload["model_targets"].append({"model_uuid": None if key == "any" else key[6:], **common})
            else:
                payload["printer_configs"].append({"printer_id": int(key), **common})
        if self.overrides:
            payload["overrides"] = {k: ("1" if v else "0") if isinstance(v, bool) else str(v) for k, v in self.overrides.items()}
        return payload

    def group_payload(self):
        payload = {"targets": [{"target_key": key, "process_profile": self.process} for key in self.target_keys]}
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
                 "pack_rule": "locked"}]


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
    if quantity > 10000 or (action == "job" and quantity != 1):
        raise WorkflowError("A plate job has quantity 1; project quantities must be at most 10000.")
    from .gcode import GCodeSnapshot, eligible_model, eligible_printers
    if action.endswith("gcode"):
        if data.get("overrides") or data.get("process") or data.get("use_filament") or data.get("targets"):
            raise WorkflowError("G-code settings are already baked in. Eligibility is set automatically from the exported printer profile.")
        model = eligible_model(snapshot, references)
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
    return SendPlan(action, project_id, name, snapshot.plate_number,
                    tuple((o, known_objects[o]) for o in selected) if action.endswith("objects") else (),
                    quantity, tuple(targets), process, filament, overrides)
