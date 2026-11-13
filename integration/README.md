# Themis API contract verification

This optional suite runs the plugin's real multipart/JSON serializers and send executor against Themis's isolated
ASGI app, auth, database, artifact store and project generation routes. It needs Themis's development dependencies,
not a deployed server or printer. Geometry cases cover the five destinations, transformed bed requirements,
target overrides, filament presets, preference storage, replay, queued updates and started-job conflicts.
G-code project destinations generate fixed jobs with the exact uploaded bytes and selected physical printer;
the configured test builder must never be called. Ordinary plugin tests stay dependency-free.
A separate CI job checks out merged Themis baseline `900556da79256d6bfb8cddd77430ce7953243e4f`
(PR #199) and runs the suite with its development environment.

From a current Themis `backend` checkout, using its virtual environment:

```powershell
python -m pytest -c pyproject.toml -p tests.conftest C:/path/to/themis-orca-plugin/integration -q
```

The plugin source path is derived from this test file. Fixtures create temporary databases and artifact folders;
this suite does not use a user's configured server or communicate with a real printer.
