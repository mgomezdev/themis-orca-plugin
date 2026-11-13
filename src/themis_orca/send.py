"""Execute a reviewed send once. Never retry an ambiguous write automatically."""

from queue import Queue, Empty
from threading import Event, Thread
from uuid import uuid4

from .client import ThemisClient, ThemisError, MutationUncertain, SendConflict
from .workflow import positive


def execute_send(client, snapshot, plan, send_id, *, update=False, prepared=None, on_prepared=lambda payload:None):
    progress = {"item_ids": []}
    try:
        connection = client.test_connection()
        if connection.local:
            raise ThemisError("Themis accepted local access but did not verify this API key. Paste a valid key in Connection settings and test again.")
        job = prepared.get("kind") == "job" if prepared else plan.action in {"job","gcode_job"}
        required = {"jobs:read","jobs:write" if job else "projects:write"}
        if prepared is None:
            required.add("files:write")
        missing = required.intersection(connection.missing_scopes)
        if missing:
            raise ThemisError("Enable these API key scopes before sending: "+", ".join(sorted(missing)))
        if not client.supports_slicer_sends():
            raise ThemisError("Update Themis to support atomic slicer sends before sending. Nothing was uploaded.")
        if prepared is None:
            uploaded = client.upload(snapshot.path, gcode_model=plan.gcode_model) if plan.gcode_model else client.upload(snapshot.path)
            file_id = positive(uploaded.get("id"), "uploaded file ID")
            progress["file_id"] = file_id
            if plan.gcode_model and uploaded.get("eligibility") != {"known": True, "model_uuids": [plan.gcode_model]}:
                raise ThemisError("Themis did not confirm the G-code printer eligibility. No project items were added.")
            payload = {"source_app":"orcaslicer","send_id":send_id,"update":update}
            if plan.action in {"job","gcode_job"}:
                payload.update(kind="job",job=plan.job_payload(file_id))
            else:
                items = [{k:v for k,v in item.items() if k != "group_id"} for item in plan.item_payloads(file_id,1)]
                destination = {"project_id":plan.project_id} if plan.project_id else {"project_name":plan.project_name}
                payload.update(kind="project",group={"name":f"Orca plate {plan.plate_number}",**plan.group_payload()},items=items,**destination)
            on_prepared(payload)  # BackgroundSend waits for UI-thread persistence before POST.
        else:
            payload = prepared
            files = {payload["job"]["uploaded_file_id"]} if payload.get("kind") == "job" else {item["file_id"] for item in payload.get("items",[])}
            if len(files) == 1:
                progress["file_id"] = files.pop()
        result = client.write_json("POST","/slicer-sends",payload)
        if not isinstance(result,dict) or result.get("send_id") != send_id or not isinstance(result.get("created"),dict):
            raise MutationUncertain("Themis returned an unexpected result. Retry the saved send to recover it.")
        progress.update(result["created"])
        return {"ok":True,"send_id":send_id,"created":progress,"can_update":result.get("can_update") is True,
                "status":result.get("status"),"message":"Job queued." if progress.get("job_id") else "Items added to the project. Generate/queue its work in Themis when ready."}
    except ThemisError as exc:
        return {"ok": False, "send_id":send_id,"created": progress,"conflict":isinstance(exc,SendConflict),
                "uncertain": isinstance(exc, MutationUncertain), "message": str(exc)}
    except Exception:
        return {"ok": False,"send_id":send_id,"created": progress, "uncertain": True,
                "message": "The send did not finish. Check Themis for created work before starting another send."}


class BackgroundSend:
    def __init__(self):
        self.worker = None
        self.results = Queue()
        self._prepared = Event()
        self._accepted = False

    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self, settings, snapshot, plan, *, send_id=None, update=False, prepared=None):
        if self.busy:
            return False
        send_id = send_id or str(uuid4())
        self._prepared.clear()
        self._accepted = False
        def persist(payload):
            self.results.put({"stage":"prepared","send_id":send_id,"request":payload})
            if not self._prepared.wait(timeout=60) or not self._accepted:
                raise ThemisError("The send identity could not be saved. Reopen the panel and retry the saved send.")
        def run():
            try:
                result = execute_send(ThemisClient(settings), snapshot, plan, send_id,update=update,prepared=prepared,on_prepared=persist)
            except Exception:
                result = {"ok": False, "uncertain": True, "created": {}, "message": "Send failed. Check Themis before trying again."}
            self.results.put(result)
        self.worker = Thread(target=run, name="themis-send", daemon=True)
        try:
            self.worker.start()
        except Exception:
            self.worker = None
            self.results.put({"ok": False, "created": {}, "message": "Allow thread access for the plugin, then inspect the plate again."})
        return True

    def acknowledge(self, accepted):
        self._accepted = accepted
        self._prepared.set()

    def lookup(self, settings, send_id):
        if self.busy:
            return False
        def run():
            try:
                result = ThemisClient(settings).lookup_send(send_id)
                self.results.put({"stage":"lookup","send_id":send_id,"result":result})
            except ThemisError as exc:
                self.results.put({"stage":"lookup","send_id":send_id,"error":str(exc)})
            except Exception:
                self.results.put({"stage":"lookup","send_id":send_id,"error":"Could not read this send's status. Check the saved identity and connection."})
        self.worker = Thread(target=run,name="themis-send-status",daemon=True)
        try:
            self.worker.start()
        except Exception:
            self.worker = None
            return False
        return True

    def poll(self):
        try:
            return self.results.get_nowait()
        except Empty:
            return None
