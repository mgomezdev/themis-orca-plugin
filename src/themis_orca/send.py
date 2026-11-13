"""Execute a reviewed send once. Never retry an ambiguous write automatically."""

from queue import Queue, Empty
from threading import Thread
from uuid import uuid4

from .client import ThemisClient, ThemisError, MutationUncertain
from .workflow import positive


def execute_send(client, snapshot, plan, send_id):
    progress = {"item_ids": []}
    try:
        if plan.action != "job" and plan.overrides and not client.supports_project_overrides():
            raise ThemisError("This Themis version cannot save project overrides. Update Themis before sending with overrides.")
        file_id = positive(client.upload(snapshot.path).get("id"), "uploaded file ID")
        progress["file_id"] = file_id
        if plan.action == "job":
            job = client.write_json("POST", "/jobs", plan.job_payload(file_id))
            progress["job_id"] = positive(job.get("id"), "created job ID")
        else:
            project_id = plan.project_id
            if project_id is None:
                project = client.write_json("POST", "/projects", {
                    "name": plan.project_name, "source_app": "orcaslicer", "external_ref": send_id,
                    "stage": "planning",
                }, idempotency_key=send_id)
                project_id = positive(project.get("id"), "created project ID")
            progress["project_id"] = project_id
            group = client.write_json("POST", f"/projects/{project_id}/groups", {"name": f"Orca plate {plan.plate_number}"})
            group_id = positive(group.get("id"), "created print group ID")
            progress["group_id"] = group_id
            configured = client.write_json("PATCH", f"/projects/{project_id}/groups/{group_id}", plan.group_payload())
            if plan.overrides and configured.get("overrides") != plan.group_payload()["overrides"]:
                raise ThemisError("Themis did not confirm the project overrides. No items were added. Check the created import group before retrying.")
            for payload in plan.item_payloads(file_id, group_id):
                item = client.write_json("POST", f"/projects/{project_id}/items", payload)
                progress["item_ids"].append(positive(item.get("id"), "created item ID"))
        return {"ok": True, "created": progress, "message": "Job queued." if plan.action == "job" else "Items added to the project. Generate/queue its work in Themis when ready."}
    except ThemisError as exc:
        return {"ok": False, "created": progress, "uncertain": isinstance(exc, MutationUncertain), "message": str(exc)}
    except Exception:
        return {"ok": False, "created": progress, "uncertain": True,
                "message": "The send did not finish. Check Themis for created work before starting another send."}


class BackgroundSend:
    def __init__(self):
        self.worker = None
        self.results = Queue()

    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def start(self, settings, snapshot, plan):
        if self.busy:
            return False
        send_id = str(uuid4())
        def run():
            try:
                result = execute_send(ThemisClient(settings), snapshot, plan, send_id)
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

    def poll(self):
        try:
            return self.results.get_nowait()
        except Empty:
            return None
