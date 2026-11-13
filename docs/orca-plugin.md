# Orca → Themis plugin development

The development wheel implements the [BIZ-151 workflows](send-workflows.md): plate jobs, plate/object project imports,
raw sliced G-code jobs/project imports, target settings, footprint eligibility and persistent send recovery.
It uses the official 2.5.0 examples reviewed in [the pinned source record](orca-2.5-reference.md).
The Script capability retains its original **Themis: Test connection** name so existing host configuration survives upgrades.
Running it opens or shows one host-owned dock on Prepare/Preview. There are no third-party runtime dependencies.

## Setup and checks

Requires Python 3.12+. CI tests Python 3.12/3.13 on Windows/Linux, Node page contracts, isolated wheel installation,
and real Themis API contracts pinned to the merged backend. Native Orca verification remains deferred.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest
node --test tests/panel_ui.test.cjs
.\.venv\Scripts\python -m build --wheel
```

The wheel is `dist/themis_orca-0.1.0.dev0-py3-none-any.whl`. It includes one import package and `top_level.txt`,
which Orca uses for discovery. Importing outside Orca does not register host capabilities.
See [API contract verification](../integration/README.md) for the companion suite.

## Installation and configuration

1. Install the wheel from OrcaSlicer 2.5.0's Plugins dialog and activate it.
2. Run **Themis: Test connection** to open the panel.
3. Expand **Connection settings**, enter the URL and paste the API key. Normal clipboard shortcuts are retained.
   **Show entered API key** allows reviewing/copying the entered value. Save clears and remasks the field.
   A blank field preserves the stored key; **Forget API key** removes it. Saving makes no network request.
4. Choose **Test connection & refresh**. If Orca prompts for the configured endpoint, grant access and retry.
5. Review the source, destination and optional settings before sending. See [the workflow guide](send-workflows.md).

The expert Config tab accepts `{"url":"https://themis.example.test","api_key":"YOUR_API_KEY"}`.
Its JSON editor displays the key; avoid sharing that configuration. The panel never reads a stored key back into its page.
The key is retained in host-managed plugin configuration, without additional plugin encryption.
URLs can include `/api/v1` and reverse-proxy prefixes. URL credentials, queries, fragments and redirects are refused.
HTTP supports local deployments; use HTTPS remotely.

Deploy [Themis PR #199](https://github.com/mgomezdev/themis/pull/199), including migrations 69–71, first.
Older servers are rejected before upload because atomic send/replay/update support is required.

## Authentication and permissions

Requests use `X-Api-Key`. A fresh identity/scope check precedes every send or replay.
Local-network fallback is not accepted as verified key authentication for sending.
`/auth/me?include_identity=true` supplies an optional key label; this is not a staff owner's identity.
The plugin shows role, key label and missing scopes without echoing credentials or raw server errors.

Reference loading uses `printers:read`, `projects:read`, and `laminus:read` as available.
Fresh sends need `files:write`, `jobs:read`, and the destination's `jobs:write` or `projects:write`.
Project lookup requires `projects:read`. Retry uses the stored request and does not re-upload the file.

Discovery and G-code capture perform no network calls. The plugin declares thread access for panel-initiated background
HTTP and relies on Orca's first-use audit prompt for the configured URL, without requesting wildcard network access.
Off-main-thread first use can fail while Orca displays the prompt; grant the intended endpoint and retry.
Actual network/filesystem/thread prompts still require native acceptance.

## Execution and recovery

Panel callbacks capture host data on the UI thread. Workers receive immutable snapshots, perform HTTP and queue results;
they do not call host APIs. UI polling persists the prepared request and acknowledges it before the worker submits.
A failed persistence step prevents submission. Closing the panel stops a prepared send awaiting acknowledgement;
a request already in flight can be recovered by lookup/replay using its saved UUID.

Refresh keeps successful reference collections when another fails, skips unavailable scopes, rejects duplicate refreshes,
and discards canceled results. Geometry uses a copy export; original model files and exported G-code remain unchanged.
G-code capture runs synchronously at the source-verified post-process seam and performs bounded local streaming I/O only.

## Troubleshooting

| Result | Action |
| --- | --- |
| Missing/rejected key | Paste a valid key in Connection settings and save. |
| Missing scopes | Enable the named scopes on the key in Themis. |
| Cannot reach Themis | Check URL, network, TLS trust and server availability. |
| Permission denied | Allow the intended configured endpoint/access in Orca, then retry. |
| Atomic API unavailable | Deploy the updated Themis backend and migrations. |
| Unknown export profile | Select the intended model explicitly; verify its Themis slicer mapping. |
| Submission outcome uncertain | Refresh saved-send status, then Retry saved send using the same UUID. |
| Started/shared work conflict | Open the existing work or deliberately choose Send as new. |

Automated tests and headless previews do not prove embedded-host compatibility. The [native acceptance checklist](roadmap.md)
remains open under the user's instruction to proceed while away from the PC. Raw `.gcode` capture is implemented;
the Bambu sliced-archive/Print plate seam still needs native investigation and is not claimed as supported.
