from zipfile import ZipFile

import pytest

from themis_orca.snapshot import inspect_snapshot
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
