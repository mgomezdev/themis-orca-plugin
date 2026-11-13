"""Small host adapter. All network and settings logic remains host-independent."""

import json
from importlib.resources import files
from threading import Lock
from pathlib import Path
from uuid import uuid4

import orca

from .refresh import BackgroundRefresh
from .settings import Settings, api_base_url
from .send import BackgroundSend
from .snapshot import inspect_snapshot
from .workflow import build_plan, WorkflowError


class PanelError(Exception):
    """An operator-facing message authored by this adapter."""


def _settings(raw):
    try:
        return Settings.from_json(raw)
    except ValueError as exc:
        raise PanelError(str(exc)) from None


class TestConnection(orca.script.ScriptPluginCapabilityBase):
    def __init__(self):
        super().__init__()
        self.panel = None
        self.refresh = BackgroundRefresh()
        self.references = None
        self.status = "Configure your connection to get started."
        self.notice = ""
        self._generation = 0
        self._open_lock = Lock()
        self.sender = BackgroundSend()
        self.snapshot = None
        self.connection = None
        self.send_attempted = False
        self.send_result = None

    def get_name(self):
        # Preserve the identity used by existing host-stored configuration.
        return "Themis: Test connection"

    def get_default_config(self):
        # The host Config tab persists this capability's settings, including the key.
        return {"url": "", "api_key": ""}

    def execute(self):
        # Script execution is on the host worker. These UI methods marshal to
        # the UI thread; read live model state only from page callbacks below.
        with self._open_lock:
            return self._open_panel()

    def _open_panel(self):
        if self.panel is not None and self.panel.is_open():
            self.panel.show()
            return orca.ExecutionResult.success("Themis panel is already open.")
        self._generation += 1
        generation = self._generation
        self.panel = orca.host.ui.create_dock_panel(
            html=files("themis_orca").joinpath("panel.html").read_text(encoding="utf-8"),
            title="Themis", width=360, height=600, dock="right",
            on_message=lambda data: self.on_message(data, generation),
            on_close=lambda: self.on_close(generation),
        )
        # The page asks for its first state after its listener is ready.
        return orca.ExecutionResult.success("Themis panel opened.")

    def _config(self):
        try:
            config = json.loads(self.get_config())
        except (ValueError, TypeError):
            return {}
        return config if isinstance(config, dict) else {}

    def _state(self, *, settings_saved=False):
        config = self._config()
        try:
            url = api_base_url(config.get("url", ""))
        except ValueError:
            url = ""
        try:
            Settings.from_json(json.dumps(config))
            configured = True
        except ValueError:
            configured = False
        try:
            plate = orca.host.model().current_plate_index()
            if not isinstance(plate, int) or isinstance(plate, bool) or plate < 0:
                plate = None
        except RuntimeError:
            plate = None
        counts = None
        if self.references is not None:
            data = self.references
            counts = {
                "Printer models": len(data.models), "Printers": len(data.printers),
                "Slicer mappings": sum(map(len, data.mappings.values())),
                "Machine presets": len(data.catalog.get("machine", [])),
                "Process presets": len(data.catalog.get("process", [])),
                "Filament presets": len(data.catalog.get("filament", [])), "Projects": len(data.projects),
            }
        return {
            "type": "state", "url": url, "key_set": bool(config.get("api_key")),
            "configured": configured, "plate_index": plate, "busy": self.refresh.busy or self.sender.busy,
            "status": ("Connection configured. Test the connection to load available data."
                       if configured and self.status == "Configure your connection to get started." else self.status),
            "notice": self.notice, "counts": counts,
            "errors": self.references.errors if self.references else {}, "settings_saved": settings_saved,
            "send_busy": self.sender.busy, "send_attempted": self.send_attempted, "send_result": self.send_result,
            "snapshot": ({"plate_number": self.snapshot.plate_number, "objects": self.snapshot.objects} if self.snapshot else None),
            "choices": ({
                "projects": [{"id": p.get("id"), "name": p.get("name", "Unnamed project")} for p in self.references.projects],
                "printers": [{"id": p.get("id"), "name": p.get("name", "Unnamed printer")} for p in self.references.printers],
                "models": [{"id": m.get("id"), "name": m.get("display_name", "Unnamed model")} for m in self.references.models],
                "processes": [p.get("name", "") for p in self.references.catalog.get("process", [])],
            } if self.references else None),
        }

    def on_message(self, data, generation):
        if generation != self._generation or self.panel is None:
            return
        saved = False
        try:
            if not isinstance(data, dict):
                raise PanelError("Themis received an invalid panel message. Reopen the panel.")
            command = data.get("command")
            if self.sender.busy and command not in {"ready", "poll"}:
                raise PanelError("A send is in progress. Wait for its result before changing this panel.")
            if command == "save":
                if self.refresh.busy:
                    raise PanelError("Wait for the current refresh to finish before changing settings.")
                config = self._config()
                key = data.get("api_key", "")
                if key == "":
                    key = config.get("api_key", "")
                settings = _settings(json.dumps({"url": data.get("url"), "api_key": key}))
                config.update(url=settings.url, api_key=settings.api_key)
                if not self.save_config(json.dumps(config)):
                    raise PanelError("Orca could not save the settings. Check write access and retry.")
                self.refresh.cancel()
                self.references = None
                self.connection = None
                self.status = "Settings saved. Test the connection to load available data."
                self.notice = ""
                saved = True
            elif command == "forget":
                if self.refresh.busy:
                    raise PanelError("Wait for the current refresh to finish before removing the key.")
                config = self._config()
                config["api_key"] = ""
                if not self.save_config(json.dumps(config)):
                    raise PanelError("Orca could not remove the stored key. Retry in the Config tab.")
                self.refresh.cancel()
                self.references = None
                self.connection = None
                self.status = "API key removed. Enter a key in Connection settings to reconnect."
                self.notice = ""
                saved = True
            elif command == "refresh":
                settings = _settings(self.get_config())
                if self.refresh.start(settings):
                    self.references = None
                    self.connection = None
                    self.status = "Connecting to Themis and loading reference data…"
                    self.notice = ""
            elif command == "cancel":
                self.refresh.cancel()
                self.status = "Refresh cancelled. Any current request will finish before you can refresh again."
                self.notice = ""
            elif command == "poll":
                result = self.refresh.poll()
                if result is not None:
                    self.references = result.references
                    self.connection = result.connection
                    self.status = result.error or result.connection.message()
                    self.notice = ""
                sent = self.sender.poll()
                if sent is not None:
                    self.send_result = sent
                    self.status = sent["message"]
            elif command == "inspect":
                if self.refresh.busy:
                    raise PanelError("Wait for the connection refresh before inspecting the plate.")
                plate = orca.host.model().current_plate_index()
                if not isinstance(plate, int) or isinstance(plate, bool) or plate < 0:
                    raise PanelError("Open a plate in Prepare or Preview before inspecting it.")
                path = Path(orca.host.plugin.storage()) / ("orca-plate-" + uuid4().hex + ".3mf")
                try:
                    orca.host.plater().export_3mf_copy(str(path))
                    snapshot = inspect_snapshot(path, plate + 1)
                except WorkflowError:
                    path.unlink(missing_ok=True)
                    raise
                except Exception:
                    path.unlink(missing_ok=True)
                    raise PanelError("Orca could not export the plate. Open Prepare/Preview, allow access to the plugin data folder, and inspect again.") from None
                if self.snapshot is not None:
                    self.snapshot.path.unlink(missing_ok=True)
                self.snapshot = snapshot
                self.send_attempted = False
                self.send_result = None
                self.notice = "Plate copy inspected. Review the destination and settings before sending."
            elif command == "send":
                if self.refresh.busy or self.snapshot is None or self.references is None or self.connection is None:
                    raise PanelError("Refresh Themis data and inspect the current plate before sending.")
                if self.send_attempted:
                    raise PanelError("This plate copy was already submitted. Check Themis before inspecting and sending another copy.")
                if orca.host.model().current_plate_index() + 1 != self.snapshot.plate_number:
                    raise PanelError("The selected plate changed. Inspect the current plate again before sending.")
                plan = build_plan(data.get("workflow"), self.snapshot, self.references)
                scopes = {"files:write", "jobs:write" if plan.action == "job" else "projects:write"}
                missing = scopes.intersection(self.connection.missing_scopes)
                if missing:
                    raise PanelError("Enable these API key scopes before sending: " + ", ".join(sorted(missing)))
                if self.sender.start(_settings(self.get_config()), self.snapshot, plan):
                    self.send_attempted = True
                    self.status = "Sending the inspected plate copy to Themis…"
                    self.notice = "Do not repeat this send if the connection is interrupted; inspect Themis first."
            elif command != "ready":
                raise PanelError("Unknown panel action. Reopen the Themis panel.")
        except (PanelError, WorkflowError) as exc:
            self.notice = str(exc)
        except Exception:
            # Host callbacks are logged if they escape. Never expose raw config,
            # network exception bodies, or arbitrary exception text there.
            self.notice = "Themis could not complete this action. Reopen the panel and retry."
        try:
            self.panel.post(self._state(settings_saved=saved))
        except Exception:
            # Teardown can race a page poll. Host owns the panel's lifetime.
            pass

    def on_close(self, generation):
        if generation == self._generation:
            if self.refresh.busy:
                self.status = "Refresh cancelled. Test the connection to reload reference data."
            self.refresh.cancel()
            self.panel = None

    def on_unload(self):
        self._generation += 1
        self.refresh.cancel()
        self.panel = None


@orca.plugin
class ThemisPlugin(orca.base):
    def register_capabilities(self):
        # Network targets come from capability config after discovery. The worker
        # is needed only for network work initiated by the panel's UI callbacks.
        orca.request_permissions(threading=True)
        orca.register_capability(TestConnection)
