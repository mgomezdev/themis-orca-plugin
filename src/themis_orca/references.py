"""Fetch independent picker data without discarding successful collections."""

from dataclasses import dataclass, field

from .client import Connection, ThemisClient, ThemisError


@dataclass
class References:
    models: list[dict] = field(default_factory=list)
    printers: list[dict] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    mappings: dict[str, list[dict]] = field(default_factory=dict)
    catalog: dict[str, list[dict]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _rows(value):
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ThemisError("Unexpected reference-data response. Check the Themis API version.")
    return value


def load_references(client: ThemisClient, connection: Connection, *, cancelled=lambda: False) -> References:
    """Run on a worker. Skip unauthorized collections and preserve partial results."""
    result = References()

    def fetch(name, scope, action):
        if cancelled():
            return None
        if scope in connection.missing_scopes:
            result.errors[name] = f"Enable {scope} on the API key, then refresh."
            return None
        try:
            return action()
        except (ThemisError, ValueError):
            # Never reflect arbitrary API values (including malformed UUIDs) in errors.
            result.errors[name] = f"Could not load {name}. Check connection, key scopes, and server version, then refresh."
            return None

    for name, scope, action in (
        ("models", "printers:read", client.printer_models),
        ("printers", "printers:read", client.printers),
        ("projects", "projects:read", client.projects),
    ):
        value = fetch(name, scope, lambda action=action: _rows(action()))
        if value is not None:
            setattr(result, name, value)

    def catalog():
        value = client.catalog()
        if not isinstance(value, dict):
            raise ThemisError("Unexpected catalog response.")
        return {kind: _rows(value.get(kind)) for kind in ("machine", "process", "filament")}

    value = fetch("catalog", "laminus:read", catalog)
    if value is not None:
        result.catalog = value
    for model in result.models:
        if cancelled():
            break
        model_id = model.get("id")
        if not isinstance(model_id, str):
            result.errors["mappings"] = "A model has no valid ID. Check the Themis API version."
            continue
        value = fetch("mappings", "printers:read", lambda: _rows(client.slicer_profiles(model_id)))
        if value is not None:
            result.mappings[model_id] = value
    return result
