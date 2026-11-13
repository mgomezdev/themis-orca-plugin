# Themis API contract verification

This optional suite runs the plugin's real multipart/JSON serializers and send executor against Themis's isolated
ASGI app, auth, database, artifact store and project generation routes. It needs Themis's development dependencies,
not a deployed server or printer. Both project destinations must generate two fixed G-code jobs with the exact
uploaded bytes and the automatically selected physical printer. Ordinary plugin tests stay dependency-free;
a separate CI job checks out Themis baseline `be3500c5f4c69b3a5dc3dbd6dfcb4d2a74b47e09` and runs this suite
with its development environment. A test builder is configured, and the tests assert it is never called for G-code.

From a current Themis `backend` checkout, using its virtual environment:

```powershell
python -m pytest -c pyproject.toml -p tests.conftest C:/path/to/themis-orca-plugin/integration/test_themis_gcode.py -q
```

The plugin source path is derived from this test file. Fixtures create temporary databases and artifact folders;
this suite does not use a user's configured server or communicate with a real printer.
