"""Host adapter contract tests; this is a stub, not an Orca installation test."""

import importlib
import json
import sys
from types import SimpleNamespace


def test_discovery_configuration_and_run(monkeypatch):
    registrations = []

    class Capability:
        def get_config(self):
            return json.dumps({"url": "http://themis.test", "api_key": "a-key"})

    result = SimpleNamespace(
        success=lambda message: ("success", message),
        failure=lambda status, message: (status, message),
    )
    host = SimpleNamespace(
        base=object, plugin=lambda cls: cls,
        script=SimpleNamespace(ScriptPluginCapabilityBase=Capability),
        register_capability=registrations.append,
        ExecutionResult=result, PluginResult=SimpleNamespace(RecoverableError="recoverable"),
    )
    monkeypatch.setitem(sys.modules, "orca", host)
    # Normal tests import pure client modules before the embedded host exists.
    monkeypatch.delitem(sys.modules, "themis_orca.plugin", raising=False)
    import themis_orca
    importlib.reload(themis_orca)
    plugin = importlib.import_module("themis_orca.plugin")
    plugin.ThemisPlugin().register_capabilities()
    assert registrations == [plugin.TestConnection]
    script = plugin.TestConnection()
    assert script.get_default_config() == {"url": "", "api_key": ""}
    monkeypatch.setattr(plugin.ThemisClient, "test_connection", lambda self: SimpleNamespace(message=lambda: "Connected as staff"))
    assert script.execute() == ("success", "Connected as staff")
    monkeypatch.setattr(script, "get_config", lambda: "{}")
    status, message = script.execute()
    assert status == "recoverable"
    assert "Config tab" in message
