"""Host-managed send history; source keys reveal neither local paths nor credentials to the page."""
from hashlib import sha256
from uuid import uuid4


SESSION = uuid4().hex


def source_key(url, project_path, model_id, plate):
    identity = project_path or f"unsaved:{SESSION}:{model_id}"
    return sha256(f"{url}\0{identity}\0{plate}".encode()).hexdigest()


def capture_key(url, snapshot):
    return sha256(f"{url}\0gcode\0{snapshot.digest}\0{snapshot.profile}".encode()).hexdigest()


def save_record(config, key, record):
    history = dict(config.get("send_history") or {})
    history.pop(key,None)
    history[key] = record
    config["send_history"] = dict(list(history.items())[-100:])
    return config
