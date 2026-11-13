import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import URLError

import pytest

from themis_orca.client import REFERENCE_SCOPES, SEND_SCOPES, ThemisClient, ThemisError
from themis_orca.settings import Settings


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        status = 200
        payload = {"role": "staff", "local": False, "scopes": sorted(REFERENCE_SCOPES | SEND_SCOPES)}
        seen = []
        routes = {}
        writes = []

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.seen.append((self.path, self.headers.get("X-Api-Key")))
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            if self.status == 302:
                self.send_header("Location", "/redirected")
            self.end_headers()
            payload = self.routes.get(self.path, self.payload)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.wfile.write(data)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            self.writes.append((self.command, self.path, dict(self.headers), body))
            self.do_GET()

        do_PATCH = do_POST

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{httpd.server_port}/api/v1"
    try:
        yield Handler, ThemisClient(Settings(url, "private-test-key"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=2)


def test_auth_request_and_success(server):
    handler, client = server
    connection = client.test_connection()
    assert handler.seen == [("/api/v1/auth/me", "private-test-key")]
    assert connection.missing_scopes == ()
    assert connection.message() == "Connected as staff. All plugin scopes are available."


def test_missing_scopes_named(server):
    handler, client = server
    handler.payload = {"role": "staff", "scopes": ["printers:read"]}
    result = client.test_connection()
    assert result.missing_scopes == tuple(sorted((REFERENCE_SCOPES | SEND_SCOPES) - {"printers:read"}))
    assert "files:write" in result.message()


def test_unauthenticated_200_is_an_error(server):
    handler, client = server
    handler.payload = {"role": None, "scopes": []}
    with pytest.raises(ThemisError, match="did not authenticate"):
        client.test_connection()


def test_local_mode_does_not_claim_key_ownership(server):
    handler, client = server
    handler.payload = {"role": "admin", "local": True, "scopes": []}
    assert "API key identity is unverified" in client.test_connection().message()


@pytest.mark.parametrize("payload", [[], {}, {"role": []}, {"role": "staff", "scopes": [None]}, b"<html>not an API</html>"])
def test_invalid_identity(server, payload):
    handler, client = server
    handler.payload = payload
    with pytest.raises(ThemisError):
        client.test_connection()


@pytest.mark.parametrize(("status", "message"), [
    (401, "rejected the API key"), (403, "lacks permission"), (404, "API was not found"),
    (413, "oversized"), (500, "HTTP 500"), (302, "redirected"),
])
def test_http_errors_are_actionable_and_do_not_echo_response(server, status, message):
    handler, client = server
    handler.status = status
    handler.payload = {"detail": "private-test-key"}
    with pytest.raises(ThemisError, match=message) as exc:
        client.test_connection()
    assert "private-test-key" not in str(exc.value)
    assert len(handler.seen) == 1  # Redirects must never receive the credential.


@pytest.mark.parametrize("error", [URLError("private-test-key"), TimeoutError("private-test-key"), PermissionError("private-test-key")])
def test_transport_failures_are_sanitized(monkeypatch, error):
    client = ThemisClient(Settings("https://themis.test/api/v1", "private-test-key"))

    def fail(*args, **kwargs):
        assert kwargs["timeout"] == 10
        raise error

    monkeypatch.setattr(client._opener, "open", fail)
    with pytest.raises(ThemisError) as exc:
        client.test_connection()
    assert "private-test-key" not in str(exc.value)
    assert "Allow network access" in str(exc.value) if isinstance(error, PermissionError) else "Cannot reach" in str(exc.value)


def test_reference_routes(server):
    handler, client = server
    model = "9d9c970e-1985-43cc-ae53-1b8899230c96"
    client.printer_models()
    client.printers()
    client.slicer_profiles(model)
    client.catalog()
    client.projects()
    assert [path for path, _ in handler.seen] == [
        "/api/v1/printer-models?enabled=true&usable=true", "/api/v1/printers",
        f"/api/v1/printer-models/{model}/slicer-profiles", "/api/v1/laminus/catalog", "/api/v1/projects",
    ]


def test_background_refresh_uses_real_http_and_collects_all_reference_data(server):
    from themis_orca.refresh import BackgroundRefresh

    handler, client = server
    model_id = "9d9c970e-1985-43cc-ae53-1b8899230c96"
    handler.routes = {
        "/api/v1/printer-models?enabled=true&usable=true": [{"id": model_id, "display_name": "P1S"}],
        "/api/v1/printers": [{"id": 10, "name": "Printer 10"}],
        "/api/v1/projects": [{"id": 5, "name": "Project 5"}],
        "/api/v1/laminus/catalog": {"machine": [], "process": [{"name": "Standard"}], "filament": []},
        f"/api/v1/printer-models/{model_id}/slicer-profiles": [{"machine_profile": "P1S 0.4"}],
    }
    refresh = BackgroundRefresh()
    assert refresh.start(client.settings)
    refresh._worker.join(timeout=2)
    assert not refresh.busy
    result = refresh.poll()
    assert result.error is None
    assert result.references.models[0]["id"] == model_id
    assert result.references.printers[0]["id"] == 10
    assert result.references.projects[0]["id"] == 5
    assert result.references.catalog["process"] == [{"name": "Standard"}]
    assert result.references.mappings[model_id] == [{"machine_profile": "P1S 0.4"}]
    assert not result.references.errors
    assert len(handler.seen) == 6
    assert all(key == "private-test-key" for _, key in handler.seen)


def test_background_refresh_with_no_read_scopes_requests_only_identity(server):
    from themis_orca.refresh import BackgroundRefresh

    handler, client = server
    handler.payload = {"role": "staff", "local": False, "scopes": []}
    refresh = BackgroundRefresh()
    refresh.start(client.settings)
    refresh._worker.join(timeout=2)
    assert not refresh.busy
    result = refresh.poll()
    assert result.error is None
    assert set(result.references.errors) == {"models", "printers", "projects", "catalog"}
    assert handler.seen == [("/api/v1/auth/me", "private-test-key")]


def test_json_write_and_multipart_upload_preserve_payload_bytes(server, tmp_path):
    from email.parser import BytesParser
    from email.policy import default

    handler, client = server
    handler.payload = {"id": 9}
    client.write_json("POST", "/projects", {"name": "Project"}, idempotency_key="send-uuid")
    method, path, headers, body = handler.writes[-1]
    assert (method, path) == ("POST", "/api/v1/projects")
    assert headers["Idempotency-Key"] == "send-uuid"
    assert json.loads(body) == {"name": "Project"}
    contents = bytes(range(256)) * 700
    artifact = tmp_path / "export.3mf"
    artifact.write_bytes(contents)
    assert client.upload(artifact) == {"id": 9}
    method, path, headers, body = handler.writes[-1]
    assert path == "/api/v1/files/upload"
    message = BytesParser(policy=default).parsebytes(('Content-Type: ' + headers["Content-Type"] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    part = list(message.iter_parts())[0]
    assert part.get_param("name", header="content-disposition") == "file"
    assert part.get_payload(decode=True) == contents


def test_unreadable_write_response_is_not_safe_to_retry(server):
    from themis_orca.client import MutationUncertain
    handler, client = server
    handler.payload = b"not-json"
    with pytest.raises(MutationUncertain, match="Check Themis"):
        client.write_json("POST", "/jobs", {"uploaded_file_id": 1})
    assert len(handler.writes) == 1


def test_project_override_schema_check_uses_deployment_root(server):
    handler, client = server
    handler.routes = {"/openapi.json": {"components": {"schemas": {"GroupPatch": {"properties": {"overrides": {}}}}}}}
    assert client.supports_project_overrides()
    assert handler.seen[-1][0] == "/openapi.json"
    handler.routes["/openapi.json"] = {"components": {"schemas": {"GroupPatch": {"properties": {}}}}}
    assert not client.supports_project_overrides()


def test_interrupted_write_is_uncertain_and_is_never_retried(monkeypatch):
    from unittest.mock import Mock
    from themis_orca.client import MutationUncertain
    client = ThemisClient(Settings("https://themis.test/api/v1", "private-key"))
    fail = Mock(side_effect=URLError("private-key"))
    monkeypatch.setattr(client._opener, "open", fail)
    with pytest.raises(MutationUncertain) as exc:
        client.write_json("POST", "/jobs", {"uploaded_file_id": 10})
    assert "private-key" not in str(exc.value)
    assert fail.call_count == 1


def test_gcode_upload_streams_original_bytes_with_model_eligibility(server, tmp_path):
    from email.parser import BytesParser
    from email.policy import default

    handler, client = server
    model = "cd1581c2-4208-41a9-8028-10da5f05aa80"
    artifact = tmp_path / "working.gcode"
    original = b"; printer_settings_id = Printer 0.4 nozzle\r\nG28\r\n" * 5000
    artifact.write_bytes(original)
    client.upload(artifact, gcode_model=model)
    method, path, headers, body = handler.writes[-1]
    assert (method, path) == ("POST", "/api/v1/files/upload")
    assert int(headers["Content-Length"]) == len(body)
    message = BytesParser(policy=default).parsebytes(('Content-Type: ' + headers["Content-Type"] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
    assert parts["eligible_model_uuids"].get_payload(decode=True).decode() == model
    assert parts["folder"].get_payload(decode=True).decode() == "/Orca G-code/" + model
    assert parts["file"].get_filename() == "orca-slice.gcode"
    assert parts["file"].get_payload(decode=True) == original
    assert artifact.read_bytes() == original
