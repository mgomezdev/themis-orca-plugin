"""Immutable export copies shared between the slicing hook and dock panel."""

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from .workflow import WorkflowError


@dataclass(frozen=True)
class GCodeSnapshot:
    path: Path
    token: str
    name: str
    profile: str
    digest: str
    plate_number: int = 1  # A raw G-code file is one already-sliced plate.
    objects: tuple = ()
    facts: dict | None = None
    system_profile: str | None = None


def eligible_model(snapshot, references):
    """Only an exact, unambiguous Orca/Laminus machine mapping establishes eligibility."""
    if not isinstance(snapshot, GCodeSnapshot) or not snapshot.profile:
        raise WorkflowError("The export has no printer profile. Export again with a configured printer preset.")
    known = {m.get("id") for m in references.models}
    def matching(profile):
        return {model for model, rows in references.mappings.items() if model in known and any(
            r.get("provider_plugin_id") == "laminus" and r.get("machine_profile") == profile for r in rows)}
    matches = matching(snapshot.profile) or (matching(snapshot.system_profile) if snapshot.system_profile else set())
    if len(matches) != 1:
        raise WorkflowError("No unique Themis printer model matches this slice. Set an exact Laminus machine-profile mapping in Themis, then refresh.")
    model = matches.pop()
    try:
        if str(UUID(model)) != model:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise WorkflowError("The matched printer model has an invalid ID. Refresh Themis data.") from None
    return model


def eligible_printers(snapshot, references, model):
    # Match the resolved profile too: two printers of one model can have different nozzles.
    printers = [p for p in references.printers if p.get("model_uuid") == model
                and p.get("machine_profile") in {snapshot.profile,snapshot.system_profile}]
    if not printers:
        raise WorkflowError("No Themis printer uses this model and machine profile. Configure its profile/nozzle in Themis, then refresh.")
    return printers


class CaptureStore:
    """Keep at most eight exports per session, protecting a copy while it is sent."""

    def __init__(self):
        self._lock = Lock()
        self._rows = []
        self._attempted = set()
        self._active = set()

    def capture(self, source, storage, name, profile, *, facts=None):
        root = Path(storage) / "gcode-captures"
        root.mkdir(parents=True, exist_ok=True)
        path = root / (uuid4().hex + ".gcode")
        digest = sha256()
        try:
            with Path(source).open("rb") as src, path.open("xb") as dst:
                while chunk := src.read(64 * 1024):
                    dst.write(chunk)
                    digest.update(chunk)
            if path.stat().st_size == 0:
                raise WorkflowError("The exported G-code is empty. Slice and export again.")
            # Names are display text only; neither page input nor output_name becomes a file path.
            name = str(name or "Exported G-code").replace("\\", "/").rsplit("/", 1)[-1][:255]
            profile = profile if isinstance(profile, str) else ""
            row = GCodeSnapshot(path, uuid4().hex, name, profile, digest.hexdigest(),facts=facts)
            with self._lock:
                for prior in self._rows:
                    if (prior.digest, prior.profile) == (row.digest, row.profile):
                        path.unlink()
                        return prior
                while len(self._rows) >= 8:
                    old = next(r for r in self._rows if r.token not in self._active)
                    old.path.unlink(missing_ok=True)
                    self._rows.remove(old)
                    self._attempted.discard(old.token)
                self._rows.append(row)
            return row
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def entries(self):
        with self._lock:
            return [(r, r.token in self._attempted) for r in reversed(self._rows)]

    def set_system_profile(self, token, name):
        with self._lock:
            for index,row in enumerate(self._rows):
                if row.token == token:
                    self._rows[index] = replace(row,system_profile=name)
                    return self._rows[index]

    def acquire(self, token, *, allow_attempted=False):
        with self._lock:
            row = next((r for r in self._rows if r.token == token), None)
            if row is None:
                raise WorkflowError("Choose a captured G-code export. Enable Themis: Capture G-code in the process preset and export G-code first.")
            if token in self._attempted and not allow_attempted:
                raise WorkflowError("This export was already submitted. Check Themis before sending more work.")
            self._active.add(token)
            return row

    def release(self, token, *, attempted=False):
        with self._lock:
            self._active.discard(token)
            if attempted:
                self._attempted.add(token)

    def mark_attempted(self, token):
        with self._lock:
            self._attempted.add(token)

    def clear(self):
        with self._lock:
            for row in list(self._rows):
                if row.token not in self._active:
                    row.path.unlink(missing_ok=True)
                    self._rows.remove(row)
                    self._attempted.discard(row.token)
