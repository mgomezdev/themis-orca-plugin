"""Run with Themis's test environment and fixtures; see integration/README.md."""

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.models import Job, JobPrinterConfig, UploadedFile
from tests.fake_providers import FakeProjectConstructor
from themis_orca.client import ThemisClient
from themis_orca.gcode import CaptureStore
from themis_orca.references import References
from themis_orca.send import execute_send
from themis_orca.settings import Settings
from themis_orca.workflow import build_plan


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["existing_gcode", "new_gcode"])
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
    plan = build_plan({"action": action, "project_id": project, "project_name": "New", "quantity": 2}, captured, refs)

    # Keep the real multipart/JSON serializers and execute_send. Only replace network transport
    # with Themis's isolated ASGI app, using its real auth, routes, DB, and artifact store.
    loop = asyncio.get_running_loop()
    api = ThemisClient(Settings("http://test/api/v1", "fixture-transport"))

    def request(method, route, body=None, headers=None, **_):
        content = body if isinstance(body, (bytes, type(None))) else b"".join(body)
        result = asyncio.run_coroutine_threadsafe(client.request(method, "/api/v1" + route,
            content=content, headers=headers), loop).result(timeout=15)
        assert result.status_code < 300, result.text
        return result.json()

    api._request = request
    library, cache = tmp_path / "library", tmp_path / "filecache"
    library.mkdir(); cache.mkdir()
    constructor = FakeProjectConstructor()
    with patch("app.config.get_library_dir", return_value=library), \
         patch("app.config.get_filecache_dir", return_value=cache), \
         patch("app.api.routes.projects.get_project_constructor", return_value=constructor):
        result = await asyncio.to_thread(execute_send, api, captured, plan, "contract-send")
        assert result["ok"], result
        created = result["created"]
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
