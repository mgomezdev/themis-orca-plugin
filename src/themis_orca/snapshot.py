"""Plate membership uses exported 3MF IDs, never transient host object IDs."""

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .workflow import WorkflowError


@dataclass(frozen=True)
class PlateSnapshot:
    path: Path
    plate_number: int
    objects: tuple[dict, ...]


def inspect_snapshot(path, plate_number):
    try:
        with ZipFile(path) as archive:
            info = archive.getinfo("Metadata/model_settings.config")
            if info.file_size > 10 * 1024 * 1024:
                raise WorkflowError("Plate metadata is too large to inspect safely.")
            root = ET.fromstring(archive.read(info))
        def metadata(node):
            return {m.get("key"): m.get("value", "") for m in node.findall("metadata")}
        names = {o.get("id"): metadata(o).get("name", "Object " + o.get("id", "")) for o in root.findall("object")}
        plates = [p for p in root.findall("plate") if metadata(p).get("plater_id") == str(plate_number)]
        if len(plates) != 1:
            raise WorkflowError("The exported file does not identify the current plate uniquely. Reinspect it.")
        counts = {}
        seen = set()
        for instance in plates[0].findall("model_instance"):
            values = metadata(instance)
            if values.get("printable", "1").lower() in {"0", "false"}:
                continue
            oid = values.get("object_id")
            iid = values.get("instance_id")
            if not oid or not oid.isdigit() or int(oid) < 1 or iid is None or not iid.isdigit():
                raise WorkflowError("The exported plate has invalid object membership. Reinspect it.")
            if (oid, iid) in seen:
                continue
            seen.add((oid, iid))
            counts[oid] = counts.get(oid, 0) + 1
        if not counts:
            raise WorkflowError("The current plate is empty. Add printable objects before sending.")
        return PlateSnapshot(Path(path), plate_number,
                             tuple({"id": oid, "name": names.get(oid, "Object " + oid), "instances": n} for oid, n in counts.items()))
    except (BadZipFile, KeyError, ET.ParseError, OSError):
        raise WorkflowError("Could not inspect the exported 3MF plate. Export it again from Prepare or Preview.") from None
