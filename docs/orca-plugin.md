# Orca → Themis plugin development

## Current implementation

This is the BIZ-379 panel implementation, not the complete BIZ-151 integration.
The wheel registers **Themis: Test connection**, a Script capability that opens the docked **Themis** panel on
Prepare/Preview. Its existing capability name is preserved so host-stored configuration remains attached to the same identity.
Running it again shows the existing panel rather than opening a duplicate. The plugin has no third-party runtime dependencies.

The panel shows the current plate, masked URL/API-key settings, connection state and missing scopes, plus counts of printer
models, printers, per-model slicer mappings, catalog presets, and projects. It polls plate state from UI callbacks and never
retains live model handles. No network request is made until **Test connection & refresh** is chosen.

The reference loader preserves successful collections when another fails and skips endpoints for missing read scopes.
The refresh worker polls through a result queue without invoking host APIs off-thread. Duplicate in-flight refreshes
are rejected. Cancellation discards the old result and stops further requests after the current socket operation completes.

Orca runs Script actions on a host-owned worker; opening/showing the host panel marshals to its UI thread.
Panel `on_message` callbacks run on the UI thread and use the separate background refresh helper for HTTP requests.
They never join that worker. The panel displays counts and per-collection errors after a refresh. Sending remains pending.
Do not treat this development wheel as a production release. Plugin loading and network prompts still need verification inside Orca 2.5.0.
See [the pinned reference review and verification record](orca-2.5-reference.md) for official examples and wiki discrepancies.

## Local setup and checks

Requires Python 3.12 or newer. CI checks 3.12 and 3.13 on Windows and Linux, builds the wheel,
and installs/imports the built wheel in isolated mode so source-tree imports cannot hide packaging errors.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest
node --test tests/panel_ui.test.cjs
.\.venv\Scripts\python -m build --wheel
```

The wheel is written to `dist/themis_orca-0.1.0.dev0-py3-none-any.whl`.
Setuptools writes the single import package `themis_orca` into `top_level.txt`, which Orca's wheel loader uses to select the entry module.
Importing that package registers the plugin only when the embedded `orca` module is available. The client imports normally outside Orca.

## Installation and configuration

1. Use OrcaSlicer **2.5.0** (target API: 2.5.x). Open its Plugins dialog and install the built wheel from file.
2. Activate the plugin and run **Themis: Test connection** to open the **Themis** panel.
3. In **Connection settings**, enter the Themis URL and API key and choose **Save settings**. The key is masked;
   leaving it blank preserves a stored key. **Forget API key** explicitly removes it. Saving does not contact Themis.
4. Choose **Test connection & refresh**. Approve access only to your configured Themis endpoint when Orca prompts, then
   retry if the first attempt was denied while the prompt was being displayed. Off-main-thread audit events fail closed on first use.

The expert **Config** tab still accepts the original JSON format. Its built-in JSON editor displays the key in plain text:

   ```json
   {"url": "https://themis.example.test", "api_key": "YOUR_API_KEY"}
   ```

   The URL may be the deployment root or include `/api/v1`. Reverse-proxy prefixes are supported.
   URL credentials, queries, and fragments are rejected. HTTP is supported for local deployments; use HTTPS for remote connections.
The plugin makes no network calls during discovery and requests no wildcard network permission.
It declares thread permission for background requests initiated by panel callbacks. Capability config is unavailable during
package registration, so it relies on Orca's first-use network audit prompt for the actual configured URL.
Further permission behavior, including socket prompts, must be checked in the host before BIZ-379 is complete.
The API key stays in host-managed plugin configuration; it is not encrypted by this plugin. The panel never sends a stored
key back to its page; it sends only a flag indicating that one is present. After a successful save, the password field clears.
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

Automated tests exercise real HTTP requests against a local test server, complete background reference refresh,
scope/error handling, cancellation, duplicate-refresh protection, URL validation, panel messages, settings preservation,
stale-page rejection, concurrent opening, and teardown against an `orca` stub. Node's built-in test runner checks the
page's host bridge, commands, control states, credential-field clearing, and text-only rendering of status/errors.
Headless Chrome previews exercise the packaged HTML in light/dark simulated host themes at dock width.
They do not prove embedded-host compatibility.

Before marking BIZ-379 done: verify wheel discovery/loading in Orca 2.5.0, check reload/unload, verify actual permission prompts,
and exercise the panel on Prepare/Preview with a real Themis endpoint. The user explicitly deferred these PC-dependent
checks and authorized proceeding with loading assumed; they are still unverified. Sending waits for the relevant backend
contracts in [the roadmap](roadmap.md).

## Orca API references

- [Plugin development and wheel discovery](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/plugin_development.html)
- [Registration and configuration methods](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/api_reference/registry.html)
- [Pinned v2.5.0 bridge](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/PythonPluginBridge.cpp)
- [Pinned v2.5.0 loader](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.5.0/src/slic3r/plugin/PluginLoader.cpp)
