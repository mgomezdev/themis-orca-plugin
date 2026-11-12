"""Orca's wheel loader imports this package to discover the plugin class.

The pure Python client can also be imported by tools without the embedded host.
"""

try:
    import orca
except ModuleNotFoundError as exc:
    if exc.name != "orca":
        raise
else:
    from .plugin import ThemisPlugin as ThemisPlugin
