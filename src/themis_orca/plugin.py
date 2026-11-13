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
from .snapshot import inspect_snapshot, capture_footprint
from .workflow import build_plan, WorkflowError
from .gcode import CaptureStore, eligible_model, eligible_printers
from .presets import capture_presets, catalog_choice, preset_snapshot
from .history import capture_key, source_key, save_record


_captures = CaptureStore()
_capture_error = ""


class CaptureGCode(orca.slicing.SlicingPipelineCapabilityBase):
    def get_name(self):
        return "Themis: Capture G-code"

    def execute(self, ctx):
        global _capture_error
        if ctx.step != orca.slicing.Step.psGCodePostProcess or not ctx.gcode_path:
            return orca.ExecutionResult.success("")
        try:
            # Export-time config belongs to this slice; never read the current GUI preset here.
            facts = {key:ctx.config_value(key) for key in ("printer_settings_id","printer_model","nozzle_diameter","filament_type","filament_colour")}
            _captures.capture(ctx.gcode_path, orca.host.plugin.storage(), ctx.output_name,
                              facts["printer_settings_id"],facts=facts)
            _capture_error = ""
            return orca.ExecutionResult.success("Themis captured this G-code export locally. Send it from the Themis panel.")
        except Exception:
            _capture_error = "G-code capture failed. Allow access to the exported file and plugin data folder, then export again."
            return orca.ExecutionResult.success("Themis could not capture this export. See the Themis panel.")


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
        self.gcode_inflight = None
        self.preset_data = None
        self.preset_error = ""
        self.pending_key = None
        self.history_selection = None

    def _source_key(self, config):
        url = api_base_url(config.get("url",""))
        model = orca.host.model()
        return source_key(url,orca.host.plater().project_path(),model.id(),model.current_plate_index()+1)

    def _record(self, config, key=None):
        history = config.get("send_history") or {}
        selected = self.history_selection or key
        if selected is None:
            try:
                selected = self._source_key(config)
            except Exception:
                return None,None
        selected = (config.get("send_aliases") or {}).get(selected,selected)
        record = history.get(selected)
        try:
            url = api_base_url(config.get("url",""))
        except ValueError:
            return selected,None
        if not isinstance(record,dict) or record.get("server_url") != url:
            return selected,None
        return selected,record

    @staticmethod
    def _public_record(record, key=None):
        if not record:
            return None
        return {k:record.get(k) for k in ("send_id","label","kind","created","status","can_update","state")} | {
            "key":key,"can_retry":bool(record.get("request")) and record.get("state") in {"prepared","failed","uncertain"}}

    def _store_record(self, key, record):
        config = save_record(self._config(),key,record)
        if record.get("capture_key"):
            aliases = dict(config.get("send_aliases") or {})
            aliases[record["capture_key"]] = key
            config["send_aliases"] = {alias:target for alias,target in aliases.items() if target in config["send_history"]}
        if not self.save_config(json.dumps(config)):
            raise PanelError("Orca could not save this send identity. Nothing will be submitted until it can be saved.")

    def _poll_send(self, sent):
        config = self._config()
        key = self.pending_key
        record = (config.get("send_history") or {}).get(key)
        if not record:
            self.sender.acknowledge(False)
            raise PanelError("The pending send identity is missing. Reopen the panel and recover it from Themis.")
        if sent.get("stage") == "prepared":
            record = {**record,"request":sent["request"],"state":"prepared"}
            try:
                self._store_record(key,record)
            except PanelError:
                self.sender.acknowledge(False)
                raise
            self.sender.acknowledge(True)
            return
        if sent.get("stage") == "lookup":
            if sent.get("error"):
                self.notice = sent["error"]
            elif sent.get("result"):
                found = sent["result"]
                record = {**record,"created":found["created"],"can_update":found.get("can_update") is True,
                          "status":found.get("status"),"state":"sent"}
                self.notice = "Send status refreshed."
            else:
                record = {**record,"state":"prepared","can_update":False,"status":"not found"}
                self.notice = "Themis has no committed work for this send. Retry its saved request."
        else:
            record = {**record,"outcome":sent,"state":"sent" if sent.get("ok") else "uncertain" if sent.get("uncertain") else "conflict" if sent.get("conflict") else "failed"}
            if sent.get("ok"):
                record.update(created=sent.get("created"),can_update=sent.get("can_update") is True,status=sent.get("status"))
            if sent.get("conflict"):
                record["can_update"] = False
            self.send_result = sent
            self.status = sent["message"]
        try:
            self._store_record(key,record)
        finally:
            if self.gcode_inflight is not None:
                _captures.release(self.gcode_inflight)
                self.gcode_inflight = None
            self.pending_key = None

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
        if not isinstance(config,dict):
            return {}
        if "send_history" in config and not isinstance(config["send_history"],dict):
            config["send_history"] = {}
        if "send_aliases" in config and not isinstance(config["send_aliases"],dict):
            config["send_aliases"] = {}
        return config

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
        defaults = None
        if self.preset_data and self.references:
            warnings = []
            process, warning = catalog_choice(self.preset_data["process"],self.references.catalog.get("process",[]))
            if warning:
                warnings.append(warning)
            filaments = []
            for filament in self.preset_data["filaments"]:
                profile,warning = catalog_choice(filament,self.references.catalog.get("filament",[]))
                if warning:
                    warnings.append(warning)
                filaments.append({**filament["ask"],**({"filament_profile":profile} if profile else {})})
            unsupported = sorted({key for preset in [self.preset_data["process"],*self.preset_data["filaments"]]
                                  for key in preset.get("unsupported",[])})
            overrides = dict(self.preset_data["process"]["overrides"])
            for filament in self.preset_data["filaments"]:
                # Ambiguous per-filament process keys need an explicit per-target selection.
                for key,value in filament["overrides"].items():
                    if key not in overrides:
                        overrides[key] = value
            defaults = {"process":process,"filaments":filaments,"overrides":overrides,
                        "warnings":warnings,"unsupported":unsupported}
        captures = []
        for row, attempted in _captures.entries():
            if row.system_profile is None:
                try:
                    collection = orca.host.preset_bundle().printers
                    preset = collection.find_preset(row.profile)
                    if preset is not None:
                        resolved = preset_snapshot(preset,collection)
                        row = _captures.set_system_profile(row.token,resolved["system"]) or row
                except Exception:
                    pass  # An unmatched custom preset remains available for explicit model selection.
            model, error = None, "Refresh Themis data to match the exported printer profile."
            model_id = None
            printers = []
            if self.references is not None:
                try:
                    model_id = eligible_model(row, self.references)
                    model = next(m.get("display_name", "Matched printer model") for m in self.references.models if m.get("id") == model_id)
                    error = ""
                    try:
                        printers = [p.get("name", "Unnamed printer") for p in eligible_printers(row, self.references, model_id)]
                    except WorkflowError:
                        pass
                except WorkflowError as exc:
                    error = str(exc)
            captures.append({"id": row.token, "name": row.name, "profile": row.profile,
                             "model": model, "printers": printers, "error": error, "attempted": attempted,
                             "model_id":model_id,"facts":row.facts,
                             "history":self._public_record(self._record(config,capture_key(url,row))[1],capture_key(url,row)) if url else None})
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
            "configured": configured, "plate_index": plate, "busy": self.refresh.busy or self.sender.busy or self.pending_key is not None,
            "status": ("Connection configured. Test the connection to load available data."
                       if configured and self.status == "Configure your connection to get started." else self.status),
            "notice": self.notice, "counts": counts,
            "errors": self.references.errors if self.references else {}, "settings_saved": settings_saved,
            "send_busy": self.sender.busy, "send_attempted": self.send_attempted, "send_result": self.send_result,
            "captures": captures, "capture_error": _capture_error,
            "preset_defaults":defaults,"preset_error":self.preset_error,
            "history":self._public_record(self._record(config)[1],self._record(config)[0]),"history_selected":bool(self.history_selection),
            "history_choice":self.history_selection or "",
            "history_choices":[{"key":key,"label":r.get("label","Previous send"),"send_id":r.get("send_id"),"created":r.get("created")}
                for key,r in reversed(list((config.get("send_history") or {}).items())) if isinstance(r,dict) and r.get("server_url") == url],
            "snapshot": ({"plate_number": self.snapshot.plate_number, "objects": self.snapshot.objects,
                          "min_bed_mm": self.snapshot.min_bed_mm} if self.snapshot else None),
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
            if (self.sender.busy or self.pending_key is not None) and command not in {"ready", "poll"}:
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
            elif command == "clear_captures":
                _captures.clear()
                self.notice = "Local captured exports cleared. Files already sent to Themis are retained there."
            elif command == "choose_history":
                selection = data.get("key")
                if selection and selection not in (self._config().get("send_history") or {}):
                    raise PanelError("Choose a known saved send.")
                self.history_selection = selection or None
            elif command in {"retry_send","lookup_send"}:
                key,record = self._record(self._config(),data.get("key"))
                if not record:
                    raise PanelError("Select a saved send first.")
                self.pending_key = key
                if command == "lookup_send":
                    if not self.sender.lookup(_settings(self.get_config()),record["send_id"]):
                        self.pending_key = None
                        raise PanelError("Could not start the status check. Allow thread access and retry.")
                elif not record.get("request"):
                    self.pending_key = None
                    raise PanelError("This send has no saved request. Inspect its source and send again with the same identity.")
                elif not self.sender.start(_settings(self.get_config()),None,None,send_id=record["send_id"],prepared=record["request"]):
                    self.pending_key = None
            elif command == "poll":
                result = self.refresh.poll()
                if result is not None:
                    self.references = result.references
                    self.connection = result.connection
                    self.status = result.error or result.connection.message()
                    self.notice = ""
                sent = self.sender.poll()
                if sent is not None:
                    self._poll_send(sent)
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
                    snapshot = capture_footprint(snapshot, orca.host.model())
                except WorkflowError:
                    path.unlink(missing_ok=True)
                    raise
                except Exception:
                    path.unlink(missing_ok=True)
                    raise PanelError("Orca could not export the plate. Open Prepare/Preview, allow access to the plugin data folder, and inspect again.") from None
                if self.snapshot is not None:
                    self.snapshot.path.unlink(missing_ok=True)
                self.snapshot = snapshot
                self.history_selection = None
                try:
                    self.preset_data = capture_presets(orca.host.preset_bundle())
                    self.preset_error = ""
                except Exception:
                    self.preset_data = None
                    self.preset_error = "Orca preset inheritance could not be read. Choose presets/settings manually, or Ignore them."
                self.send_attempted = False
                self.send_result = None
                self.notice = "Plate copy inspected. Review the destination and settings before sending."
            elif command == "send":
                workflow = data.get("workflow")
                gcode = isinstance(workflow, dict) and workflow.get("action") in {"gcode_job","existing_gcode", "new_gcode"}
                if self.refresh.busy or self.references is None or self.connection is None:
                    raise PanelError("Refresh Themis data before sending.")
                if self.gcode_inflight is not None:
                    raise PanelError("Wait for the previous send result before starting another send.")
                if not gcode and self.snapshot is None:
                    raise PanelError("Inspect the current plate before sending geometry.")
                if not gcode and orca.host.model().current_plate_index() + 1 != self.snapshot.plate_number:
                    raise PanelError("The selected plate changed. Inspect the current plate again before sending.")
                snapshot = _captures.acquire(workflow.get("capture_id"),allow_attempted=True) if gcode else self.snapshot
                started = False
                try:
                    plan = build_plan(workflow, snapshot, self.references)
                    scopes = {"jobs:read","files:write", "jobs:write" if plan.action in {"job","gcode_job"} else "projects:write"}
                    missing = scopes.intersection(self.connection.missing_scopes)
                    if missing:
                        raise PanelError("Enable these API key scopes before sending: " + ", ".join(sorted(missing)))
                    config = self._config()
                    url = api_base_url(config.get("url",""))
                    source = capture_key(url,snapshot) if gcode and not workflow.get("associate_plate") else self._source_key(config)
                    key,record = self._record(config,workflow.get("history_key") or source)
                    disposition = workflow.get("disposition","update" if record else "new")
                    if disposition not in {"new","update"}:
                        raise PanelError("Choose Update or Send as new; use Retry saved send for interrupted work.")
                    updating = bool(record and disposition == "update" and (record.get("request") or record.get("state") == "sent"))
                    if record and disposition == "update" and (updating or record.get("state") in {"uncertain","conflict"}) and not record.get("can_update"):
                        raise PanelError("This send cannot be updated, or its status is uncertain. Refresh its status, retry its saved request, or choose Send as new.")
                    if disposition == "new" or record is None:
                        if record:
                            self._store_record(key+":"+record["send_id"],record)
                        key = source
                        self.history_selection = None
                        record = {"send_id":str(uuid4()),"server_url":url,"kind":"job" if plan.action in {"job","gcode_job"} else "project",
                                  "label":snapshot.name if gcode else f"{Path(orca.host.plater().project_path()).name or 'Unsaved project'}, plate {snapshot.plate_number}","state":"preparing"}
                    if gcode:
                        record["capture_key"] = capture_key(url,snapshot)
                    self._store_record(key,record)  # Stable UUID is saved BEFORE upload begins.
                    self.pending_key = key
                    if self.sender.start(_settings(self.get_config()), snapshot, plan,send_id=record["send_id"],update=updating):
                        started = True
                        self.send_result = None
                        if gcode:
                            self.gcode_inflight = snapshot.token
                            _captures.mark_attempted(snapshot.token)
                        else:
                            self.send_attempted = True
                        self.status = "Sending the captured G-code to Themis…" if gcode else "Sending the inspected plate copy to Themis…"
                        self.notice = "This send has a saved identity. Use Retry saved send if the connection is interrupted."
                    else:
                        self.pending_key = None
                finally:
                    if not started:
                        self.pending_key = None
                    if gcode and not started:
                        _captures.release(snapshot.token)
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
            self.sender.acknowledge(False)
            self.panel = None

    def on_unload(self):
        self._generation += 1
        self.refresh.cancel()
        self.sender.acknowledge(False)
        self.panel = None
        _captures.clear()


@orca.plugin
class ThemisPlugin(orca.base):
    def register_capabilities(self):
        # Network targets come from capability config after discovery. The worker
        # is needed only for network work initiated by the panel's UI callbacks.
        orca.request_permissions(threading=True)
        orca.register_capability(TestConnection)
        orca.register_capability(CaptureGCode)
