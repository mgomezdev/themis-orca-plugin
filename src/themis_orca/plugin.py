"""Small host adapter. All network and settings logic remains host-independent."""

import orca

from .client import ThemisClient, ThemisError
from .settings import Settings


class TestConnection(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Themis: Test connection"

    def get_default_config(self):
        # The host Config tab persists this capability's settings, including the key.
        return {"url": "", "api_key": ""}

    def execute(self):
        try:
            settings = Settings.from_json(self.get_config())
            connection = ThemisClient(settings).test_connection()
        except (ValueError, ThemisError) as exc:
            return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, str(exc))
        return orca.ExecutionResult.success(connection.message())


@orca.plugin
class ThemisPlugin(orca.base):
    def register_capabilities(self):
        # Capability config is available only after registration. Network permissions
        # are therefore prompted on first use for the actual configured URL.
        # Never request wildcard or hard-coded Themis hosts at registration.
        orca.register_capability(TestConnection)
