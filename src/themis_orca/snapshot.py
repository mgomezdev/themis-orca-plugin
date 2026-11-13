"""Plate membership uses exported 3MF IDs, never transient host object IDs."""

from dataclasses import dataclass, replace
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .workflow import WorkflowError
from .footprint import plate_footprint


@dataclass(frozen=True)
class PlateSnapshot:
    path: Path
    plate_number: int
    objects: tuple[dict, ...]
    members: tuple[tuple[str, str], ...] = ()
    min_bed_mm: dict | None = None


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
        members = []
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
            members.append((oid, values.get("identify_id", "")))
            counts[oid] = counts.get(oid, 0) + 1
        if not counts:
            raise WorkflowError("The current plate is empty. Add printable objects before sending.")
        return PlateSnapshot(Path(path), plate_number,
                             tuple({"id": oid, "name": names.get(oid, "Object " + oid), "instances": n} for oid, n in counts.items()), tuple(members))
    except (BadZipFile, KeyError, ET.ParseError, OSError):
        raise WorkflowError("Could not inspect the exported 3MF plate. Export it again from Prepare or Preview.") from None


def capture_footprint(snapshot, model):
    """UI-thread only. Match export identify_id to host instance.id; retain only plain data.

    Pinned copy export uses SplitModel|ShareMesh|Silence, not UseLoadedId. Its plate
    metadata therefore records instance.id().id as identify_id, independently of object order.
    """
    wanted = {identity: oid for oid, identity in snapshot.members}
    if "" in wanted or len(wanted) != len(snapshot.members):
        raise WorkflowError("The exported plate lacks unique instance identities. Inspect again with Orca 2.5.")
    matched, counts, vertices = set(), {}, []

    def transform(matrix, vertex):
        point = tuple(map(float, vertex)) + (1,)
        return tuple(sum(float(matrix[r][c]) * point[c] for c in range(4)) for r in range(3))

    for obj in model.objects():
        selected = [i for i in obj.instances() if str(i.id()) in wanted]
        for instance in selected:
            identity = str(instance.id())
            matched.add(identity)
            if not instance.printable:
                continue  # is_printable() also excludes oversized/out-of-bed parts; do not use it here.
            oid = wanted[identity]
            counts[oid] = counts.get(oid, 0) + 1
            outer = instance.matrix()
            for volume in obj.volumes():
                if volume.is_model_part():
                    inner = volume.matrix()
                    vertices.extend(transform(outer, transform(inner, vertex)) for vertex in volume.mesh().vertices())
    if matched != wanted.keys():
        raise WorkflowError("The plate changed while it was inspected. Inspect the current plate again.")
    footprint = plate_footprint(vertices)
    if footprint is None or footprint.x <= 0 or footprint.y <= 0:
        raise WorkflowError("The current plate has no printable geometry.")
    return replace(snapshot, min_bed_mm=footprint.min_bed_mm(),
        objects=tuple({**o, "instances": counts[o["id"]]} for o in snapshot.objects if o["id"] in counts))
