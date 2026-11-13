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

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.seen.append((self.path, self.headers.get("X-Api-Key")))
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            if self.status == 302:
                self.send_header("Location", "/redirected")
            self.end_headers()
            data = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
            self.wfile.write(data)

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
