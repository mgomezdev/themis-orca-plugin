from zipfile import ZipFile

import pytest

from themis_orca.snapshot import inspect_snapshot
from themis_orca.snapshot import PlateSnapshot, capture_footprint
from themis_orca.workflow import WorkflowError


def archive(tmp_path, xml):
    path = tmp_path / "export.3mf"
    with ZipFile(path, "w") as z:
        z.writestr("Metadata/model_settings.config", xml)
    return path


def instance(oid, iid, printable="1"):
    return f'<model_instance><metadata key="object_id" value="{oid}"/><metadata key="instance_id" value="{iid}"/><metadata key="printable" value="{printable}"/></model_instance>'


def test_membership_and_ids_come_from_selected_exported_plate(tmp_path):
    path = archive(tmp_path, '<config><object id="17"><metadata key="name" value="Part A"/></object>'
                   '<plate><metadata key="plater_id" value="1"/>' + instance(99, 0) + '</plate>'
                   '<plate><metadata key="plater_id" value="2"/>' + instance(17, 0) + instance(17, 1) + instance(17, 1)
                   + instance(25, 0, "0") + '</plate></config>')
    result = inspect_snapshot(path, 2)
    assert result.plate_number == 2
    assert result.objects == ({"id": "17", "name": "Part A", "instances": 2},)


@pytest.mark.parametrize("xml", ["broken", '<config/>', '<config><plate><metadata key="plater_id" value="1"/></plate></config>',
    '<config><plate><metadata key="plater_id" value="1"/>' + instance("bad", 0) + '</plate></config>'])
def test_missing_or_invalid_membership_fails_closed(tmp_path, xml):
    with pytest.raises(WorkflowError):
        inspect_snapshot(archive(tmp_path, xml), 1)


def test_footprint_uses_exported_identity_world_transforms_and_only_printable_parts(tmp_path):
    from types import SimpleNamespace as NS
    identity = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    rotate = [[0,-1,0,100],[1,0,0,100],[0,0,1,5],[0,0,0,1]]
    part = NS(is_model_part=lambda:True, matrix=lambda:identity,
              mesh=lambda:NS(vertices=lambda:[(0,0,0),(20,30,10)]))
    modifier = NS(is_model_part=lambda:False, mesh=lambda:pytest.fail("modifier read"))
    a = NS(id=lambda:101,printable=True,matrix=lambda:rotate)
    other_plate = NS(id=lambda:202,printable=True,matrix=lambda:pytest.fail("other plate read"))
    disabled = NS(id=lambda:303,printable=False,matrix=lambda:pytest.fail("disabled read"))
    model = NS(objects=lambda:[NS(instances=lambda:[a,other_plate,disabled],volumes=lambda:[part,modifier])])
    snapshot = PlateSnapshot(tmp_path/'p.3mf',1,({"id":"17","name":"Part","instances":2},),(("17","101"),("17","303")))
    result = capture_footprint(snapshot,model)
    assert result.min_bed_mm == {"x":30,"y":20,"z":15}
    assert result.objects[0]["instances"] == 1


def test_unknown_exported_identity_cannot_use_a_different_host_object(tmp_path):
    from types import SimpleNamespace as NS
    snapshot = PlateSnapshot(tmp_path/'p.3mf',1,(),(("17","101"),))
    with pytest.raises(WorkflowError,match="plate changed"):
        capture_footprint(snapshot,NS(objects=lambda:[]))
