"""End-to-end plugin payloads against the real isolated Themis API and DB."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func,select

from app.models import Job,JobPrinterConfig,ProjectItem,UploadedFile
from tests.conftest import make_3mf_bytes
from test_themis_gcode import api_for
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.workflow import build_plan
from themis_orca.presets import capture_presets
from themis_orca.material import split_material
from app.services.filament_tuple import split_type


@pytest.mark.parametrize("raw", ["PLA", "PLA+", "PLA-Silk", "PETG CF", "PA6-GF", "PC-ABS",
    "PLA High Flow", "PLA Carbon Fiber", "PLA Basic", "PLA experimental", "PETG/PLA", "", None])
def test_orca_material_translation_matches_backend_contract(raw):
    assert split_material(raw) == split_type(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("material,expected", [
    ("PLA", ("PLA", "standard")), ("PLA+", ("PLA", "plus")),
    ("PLA-Silk", ("PLA", "silk")), ("PETG-CF", ("PETG", "cf")),
    ("PC-ABS", ("PC-ABS", "standard")),
])
async def test_plate_job_footprint_target_settings_replay_and_started_job_protection(client,create_printer,session_factory,tmp_path,material,expected):
    small = await create_printer(name="Small",bed_x_mm=256,bed_y_mm=256)
    big = await create_printer(name="Big",bed_x_mm=350,bed_y_mm=350)
    refs = References(printers=(await client.get("/api/v1/printers")).json(),
        catalog={"process":[{"name":"Standard"}],"filament":[{"name":"Generic PLA"}]})
    source = tmp_path/"export.3mf"; source.write_bytes(make_3mf_bytes())
    snapshot = SimpleNamespace(path=source,plate_number=1,objects=(),min_bed_mm={"x":300,"y":300,"z":100})
    # Assume Orca slicing/host bindings supply this snapshot; keep preset capture,
    # payload building, serializers, API, eligibility and database persistence real.
    def preset(name, **values):
        return SimpleNamespace(name=name,is_system=True,config_keys=lambda:list(values),config_value=values.get)
    process, machine = preset("Standard"), preset("Machine")
    filament = preset("Generic PLA",filament_vendor=["Fixture vendor"])
    bundle = SimpleNamespace(current_process_preset=lambda:process,current_printer_preset=lambda:machine,
        prints=SimpleNamespace(find_preset=lambda name:process),printers=SimpleNamespace(find_preset=lambda name:machine),
        filaments=SimpleNamespace(find_preset=lambda name:filament,edited_preset=lambda:filament),
        current_filament_presets=lambda:[filament],
        full_config_value=lambda key:{"filament_type":[material],"filament_colour":["#112233"]}[key])
    ask = capture_presets(bundle)["filaments"][0]["ask"]
    assert (ask["filament_type"],ask["filament_subtype"]) == expected
    settings = {"action":"job","process":"Standard","targets":["any"],"target_overrides":{"any":{"wall_loops":"4"}},
        "preference":[str(big)],"filament_map":[{**ask,"filament_profile":"Generic PLA"}]}
    plan = build_plan(settings,snapshot,refs)
    api = api_for(client); sid = str(uuid4()); saved = []
    library,cache = tmp_path/"library",tmp_path/"filecache"; library.mkdir(); cache.mkdir()
    with patch("app.config.get_library_dir",return_value=library),patch("app.config.get_filecache_dir",return_value=cache):
        result = await asyncio.to_thread(execute_send,api,snapshot,plan,sid,on_prepared=saved.append)
        assert result["ok"],result
        replay = await asyncio.to_thread(execute_send,api,None,None,sid,prepared=saved[0])
        assert replay["created"] == result["created"]
        jid = result["created"]["job_id"]
        async with session_factory() as s:
            assert (await s.execute(select(func.count()).select_from(Job))).scalar() == 1
            configs = list((await s.execute(select(JobPrinterConfig).where(JobPrinterConfig.job_id == jid))).scalars())
            assert [c.printer_id for c in configs] == [big]
            assert configs[0].overrides == {"wall_loops":"4"}
            assert configs[0].filament_map[0]["filament_profile"] == "Generic PLA"
            assert configs[0].filament_map[0] == {**ask,"filament_profile":"Generic PLA","tool_index":None}
            job = await s.get(Job,jid)
            assert job.min_bed_mm == snapshot.min_bed_mm
            original_file = job.uploaded_file_id
        snapshot.min_bed_mm = {"x":200,"y":200,"z":100}
        updated = await asyncio.to_thread(execute_send,api,snapshot,build_plan(settings,snapshot,refs),sid,update=True)
        assert updated["ok"] and updated["created"]["job_id"] == jid
        async with session_factory() as s:
            assert {c.printer_id for c in (await s.execute(select(JobPrinterConfig).where(JobPrinterConfig.job_id == jid))).scalars()} == {small,big}
            assert await s.get(UploadedFile,original_file) is not None
            job = await s.get(Job,jid); job.status = "printing"; await s.commit()
        snapshot.min_bed_mm = {"x":150,"y":150,"z":100}
        refused = await asyncio.to_thread(execute_send,api,snapshot,build_plan(settings,snapshot,refs),sid,update=True)
        assert not refused["ok"] and refused["conflict"]
        async with session_factory() as s:
            assert (await s.get(Job,jid)).min_bed_mm["x"] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("action",["existing_plate","new_plate","existing_objects","new_objects"])
async def test_project_geometry_destinations_are_atomic_and_duplicate_safe(client,create_printer,session_factory,tmp_path,action):
    printer = await create_printer()
    project = (await client.post("/api/v1/projects",json={"name":"Existing"})).json()["id"]
    source = tmp_path/"export.3mf"; source.write_bytes(make_3mf_bytes())
    snapshot = SimpleNamespace(path=source,plate_number=1,objects=({"id":"17","instances":2},),min_bed_mm={"x":100,"y":100,"z":20})
    refs = References(projects=[{"id":project}],printers=[{"id":printer}],catalog={"process":[{"name":"Standard"}]})
    plan = build_plan({"action":action,"project_id":project,"project_name":"New","object_ids":["17"],
        "process":"Standard","targets":[str(printer)],"target_overrides":{str(printer):{"wall_loops":"3"}}},snapshot,refs)
    library,cache = tmp_path/"library",tmp_path/"filecache"; library.mkdir(); cache.mkdir()
    api = api_for(client); sid = str(uuid4()); saved = []
    with patch("app.config.get_library_dir",return_value=library),patch("app.config.get_filecache_dir",return_value=cache):
        result = await asyncio.to_thread(execute_send,api,snapshot,plan,sid,on_prepared=saved.append)
        assert result["ok"],result
        repeated = await asyncio.to_thread(execute_send,api,None,None,sid,prepared=saved[0])
        assert repeated["created"] == result["created"]
        async with session_factory() as s:
            items = list((await s.execute(select(ProjectItem))).scalars())
            assert len(items) == 1
            assert items[0].kind == ("3mf_object" if action.endswith("objects") else "3mf_plate")
            assert items[0].quantity == (2 if action.endswith("objects") else 1)
            assert items[0].min_bed_mm == (None if action.endswith("objects") else snapshot.min_bed_mm)
