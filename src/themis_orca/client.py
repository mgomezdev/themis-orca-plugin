"""Read-only Themis API client with no runtime dependencies or Orca imports."""

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .settings import Settings

# Current Themis routes; sending scopes are listed separately until sending exists.
REFERENCE_SCOPES = frozenset({"printers:read", "projects:read", "laminus:read"})
SEND_SCOPES = frozenset({"files:write", "jobs:read", "jobs:write", "projects:write"})


class ThemisError(Exception):
    """A credential-free, operator-facing error safe for host result dialogs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A reverse proxy redirect must never forward X-Api-Key to another URL.
        return None


@dataclass(frozen=True)
class Connection:
    role: str
    local: bool
    missing_scopes: tuple[str, ...]

    def message(self) -> str:
        identity = f"Connected as {self.role}"
        if self.local:
            identity += " via local-network access (API key identity is unverified)"
        if self.missing_scopes:
            return identity + ". Missing scopes: " + ", ".join(self.missing_scopes) + ". Update the key in Themis."
        return identity + ". All plugin scopes are available."


class ThemisClient:
    def __init__(self, settings: Settings, *, timeout: float = 10):
        self.settings = settings
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _get(self, path: str):
        request = Request(self.settings.url + path, headers={
            "X-Api-Key": self.settings.api_key,
            "Accept": "application/json",
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            status = exc.code
            exc.close()
            messages = {
                401: "Themis rejected the API key. Replace it in the plugin Config tab.",
                403: "The API key lacks permission. Check the key scopes in Themis.",
                404: "Themis API was not found. Check the deployment URL and /api/v1 path.",
                413: "Themis rejected an oversized request. Check the server upload limit.",
            }
            if 300 <= status < 400:
                raise ThemisError("Themis redirected the request. Configure the final URL, including HTTPS if required.") from None
            raise ThemisError(messages.get(status, f"Themis returned HTTP {status}. Check the server and try again.")) from None
        except PermissionError:
            raise ThemisError("Allow network access to the configured Themis URL in Orca, then retry.") from None
        except (URLError, OSError, TimeoutError):
            raise ThemisError("Cannot reach Themis. Check the URL, network, TLS certificate, and server availability.") from None
        try:
            return json.loads(payload)
        except (ValueError, UnicodeError):
            raise ThemisError("Themis returned invalid JSON. Check that the URL points to the API.") from None

    def test_connection(self) -> Connection:
        me = self._get("/auth/me")
        if not isinstance(me, dict):
            raise ThemisError("Unexpected identity response. Check the Themis API version.")
        role = me.get("role")
        if role is None:
            # Themis returns 200 with role=null for unauthenticated callers.
            raise ThemisError("Themis did not authenticate the key. Replace it in the plugin Config tab.")
        scopes = me.get("scopes")
        if not isinstance(role, str) or role not in {"staff", "admin", "customer"} or not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            raise ThemisError("Unexpected identity response. Check the Themis API version.")
        return Connection(role, me.get("local") is True, tuple(sorted((REFERENCE_SCOPES | SEND_SCOPES) - set(scopes))))

    def printer_models(self):
        return self._get("/printer-models?enabled=true&usable=true")

    def printers(self):
        return self._get("/printers")

    def slicer_profiles(self, model_uuid: str):
        model_uuid = str(UUID(model_uuid))
        return self._get(f"/printer-models/{model_uuid}/slicer-profiles")

    def projects(self):
        return self._get("/projects")

    def catalog(self):
        return self._get("/laminus/catalog")
