# Orca → Themis plugin development

## Current implementation

This is the first BIZ-379 development slice, not the complete BIZ-151 integration.
The wheel registers **Themis: Test connection**, a Script capability. The plugin has no third-party runtime dependencies.
It reads the deployment URL and API key from Orca's built-in capability configuration and tests `GET /api/v1/auth/me`.
The host displays a result with the role and missing scopes. Core client methods also cover printer models, printers,
per-model slicer-profile mappings, the Laminus catalog, and projects; no automatic reference-data refresh is wired yet.

The docked panel, custom settings page, current-plate display, asynchronous connection test, and sending are still to be implemented.
The current Script action performs one synchronous request with a 10-second socket timeout on Orca's UI thread.
Do not treat this development wheel as a production release. Installation and network prompts still need verification inside Orca 2.5.0.

## Local setup and checks

Requires Python 3.12 or newer. CI checks 3.12 and 3.13.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m build --wheel
```

The wheel is written to `dist/themis_orca-0.1.0.dev0-py3-none-any.whl`.
Setuptools writes the single import package `themis_orca` into `top_level.txt`, which Orca's wheel loader uses to select the entry module.
Importing that package registers the plugin only when the embedded `orca` module is available. The client imports normally outside Orca.

## Installation and configuration

1. Use OrcaSlicer **2.5.0** (target API: 2.5.x). Open its Plugins dialog and install the built wheel from file.
2. Select **Themis: Test connection** and open the **Config** tab. Restore defaults if the editor is empty.
3. Set these values and save using the host editor:

   ```json
   {"url": "https://themis.example.test", "api_key": "YOUR_API_KEY"}
   ```

   The URL may be the deployment root or include `/api/v1`. Reverse-proxy prefixes are supported.
   URL credentials, queries, and fragments are rejected. HTTP is supported for local deployments; use HTTPS for remote connections.
4. Run the capability. Approve access only to your configured Themis endpoint when Orca prompts.

The plugin makes no network calls during discovery and requests no wildcard network permission.
Capability config is unavailable during package registration, so this initial implementation relies on Orca's first-use audit prompt for the actual URL.
Further permission behavior, including socket prompts, must be checked in the host before BIZ-379 is complete.
The API key stays in host-managed plugin configuration; it is not encrypted by this plugin. The built-in JSON editor shows it in plain text.
Do not share screenshots or copies of this configuration. The plugin never includes the key or raw server error bodies in result messages or logs.

## API scopes and identity

Reference-data reads need `printers:read`, `projects:read`, and `laminus:read`.
The planned job/project workflows also need `files:write`, `jobs:read`, `jobs:write`, and `projects:write`.
The connection test reports any of these missing scopes by name; missing scopes do not mean the server is unreachable.

Contract checked against the sibling Themis backend's `app/api/routes/session.py`, `printer_models.py`,
`printer_model_slicer_profiles.py`, `printers.py`, `projects.py`, `laminus.py`, and `app/auth.py` on 2026-11-12.
Requests use `X-Api-Key`. In the current backend, `/auth/me` returns `role`, `local`, `customer`, and `scopes`.
It returns HTTP 200 with `role: null` when unauthenticated. It does **not** return a staff key owner's name or key label.
The plugin therefore reports the role and flags local-network fallback as an unverified key identity.
Reporting the actual staff key owner requires a backend identity contract change.

## Troubleshooting

| Result | Action |
| --- | --- |
| Missing or rejected key | Set a valid API key in the Config tab. |
| Missing scopes | Enable the named scopes on the key in Themis. |
| Cannot reach Themis | Check the URL, network, TLS trust, and server availability. |
| Network permission denied | Allow the configured Themis URL in Orca and retry. |
| API not found or invalid JSON | Check the deployment prefix; a login page or frontend URL is not the API. |
| Redirected request | Configure the final URL, including HTTPS where required. Credentials are never forwarded through redirects. |
| Local-network access | The server may have accepted local access despite an invalid key; validate the key outside local fallback. |

## Verification boundaries and next work

Automated tests exercise real HTTP requests against a local test server, scope/error handling, URL validation,
and discovery/config/run against an `orca` stub. They do not prove embedded-host compatibility.

Before marking BIZ-379 done: install the wheel in Orca 2.5.0, check reload/unload, verify actual permission prompts,
add a masked custom settings editor and nonblocking test, build the docked Prepare/Preview panel,
show current plate and refresh reference data. Sending waits for the relevant backend contracts in [the roadmap](roadmap.md).

## Orca API references

- [Plugin development and wheel discovery](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/plugin_development.html)
- [Registration and configuration methods](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/api_reference/registry.html)
- [Pinned v2.5.0 bridge](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/PythonPluginBridge.cpp)
- [Pinned v2.5.0 loader](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/PluginLoader.cpp)
