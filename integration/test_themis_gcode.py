"""Run with Themis's test environment and fixtures; see integration/README.md."""

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.models import Job, JobModelTarget, JobPrinterConfig, UploadedFile
from tests.fake_providers import FakeProjectConstructor
from themis_orca.client import ThemisClient
from themis_orca.gcode import CaptureStore
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.settings import Settings
from themis_orca.workflow import build_plan


def api_for(client):
    loop = asyncio.get_running_loop()
    api = ThemisClient(Settings("http://test/api/v1","fixture-transport"))
    def request(method,route,body=None,headers=None,**options):
        from themis_orca.client import SendConflict,ThemisError
        content = body if isinstance(body,(bytes,type(None))) else b"".join(body)
        result = asyncio.run_coroutine_threadsafe(client.request(method,("" if options.get("deployment_root") else "/api/v1")+route,
            content=content,headers=headers),loop).result(timeout=15)
        if result.status_code == 409:
            raise SendConflict("Started or shared work cannot be updated")
        if result.status_code >= 300:
            raise ThemisError(result.text)
        return result.json()
    api._request = request
    return api


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["gcode_job", "existing_gcode", "new_gcode"])
async def test_send_to_real_themis_routes_and_generate_fixed_jobs(
        client, create_printer, model_uuid_of, session_factory, tmp_path, action):
    profile = "Orca contract 0.4 nozzle"
    printer = await create_printer(printer_type="elegoo_centauri", machine_profile_override=profile)
    model = await model_uuid_of(printer)
    path = f"/api/v1/printer-models/{model}/slicer-profiles"
    response = await client.post(path, json={"provider_plugin_id": "laminus", "machine_profile": profile,
                                            "nozzle_diameter_mm": 0.4, "flow": "standard"})
    assert response.status_code == 201, response.text
    project = (await client.post("/api/v1/projects", json={"name": "Existing"})).json()["id"]
    refs = References(projects=[{"id": project}], models=[{"id": model}],
                      mappings={model: (await client.get(path)).json()},
                      printers=(await client.get("/api/v1/printers")).json())
    source = tmp_path / "export.gcode"
    original = b"; estimated printing time (normal mode) = 1m 0s\r\nG28\r\nG1 X5 Y5\r\n"
    source.write_bytes(original)
    captured = CaptureStore().capture(source, tmp_path / "storage", "part.gcode", profile)
    plan = build_plan({"action": action, "project_id": project, "project_name": "New",
                       "quantity": 1 if action == "gcode_job" else 2}, captured, refs)

    # Keep the real multipart/JSON serializers and execute_send. Only replace network transport
    # with Themis's isolated ASGI app, using its real auth, routes, DB, and artifact store.
    api = api_for(client)
    library, cache = tmp_path / "library", tmp_path / "filecache"
    library.mkdir(); cache.mkdir()
    constructor = FakeProjectConstructor()
    with patch("app.config.get_library_dir", return_value=library), \
         patch("app.config.get_filecache_dir", return_value=cache), \
         patch("app.api.routes.projects.get_project_constructor", return_value=constructor):
        from uuid import uuid4
        send_id = str(uuid4())
        saved = []
        result = await asyncio.to_thread(execute_send, api, captured, plan, send_id,on_prepared=saved.append)
        assert result["ok"], result
        replay = await asyncio.to_thread(execute_send,api,None,None,send_id,prepared=saved[0])
        assert replay["ok"] and replay["created"] == result["created"]
        created = result["created"]
        if action == "gcode_job":
            async with session_factory() as session:
                job = await session.get(Job, created["job_id"])
                assert job.uploaded_file_id == created["file_id"] and job.plate_number == 1
                targets = (await session.execute(select(JobModelTarget).where(JobModelTarget.job_id == job.id))).scalars().all()
                assert [t.model_uuid for t in targets] == [model]
                configs = (await session.execute(select(JobPrinterConfig).where(JobPrinterConfig.job_id == job.id))).scalars().all()
                assert [c.printer_id for c in configs] == [printer]
                uploaded = await session.get(UploadedFile, created["file_id"])
                assert (library / uploaded.relative_path).read_bytes() == original
            assert saved[0]["job"]["printer_configs"] == []
            assert constructor.calls == [] and source.read_bytes() == original
            return
        items = (await client.get(f"/api/v1/projects/{created['project_id']}/items")).json()
        assert [(i["kind"], i["quantity"], i["pack_rule"]) for i in items] == [("gcode", 2, "locked")]
        response = await client.post(f"/api/v1/projects/{created['project_id']}/generate", json={})
        assert response.status_code == 200, response.text
        assert len(response.json()["jobs"]) == 2
        assert constructor.calls == []  # G-code must never be packed/re-sliced.
        async with session_factory() as session:
            uploaded = await session.get(UploadedFile, created["file_id"])
            assert (library / uploaded.relative_path).read_bytes() == original
            jobs = (await session.execute(select(Job).where(Job.project_id == created["project_id"]))).scalars().all()
            assert [(j.uploaded_file_id, j.plate_number, j.overrides) for j in jobs] == [(created["file_id"], 1, None)] * 2
            configs = (await session.execute(select(JobPrinterConfig))).scalars().all()
            assert [(c.printer_id, c.print_profile) for c in configs] == [(printer, "")] * 2
    assert source.read_bytes() == original
