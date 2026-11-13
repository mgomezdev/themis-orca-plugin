# OrcaSlicer 2.5 plugin reference and host verification

Reviewed 2026-11-13 against official tag `v2.5.0`, commit
`40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19`. The installed Windows app reports
`OrcaSlicer Version 2.5.0 build 40ecc66f`, so this is also the source baseline for local verification.

## Reference implementations

The official source tree contains runnable, single-file sandbox examples:

| Reference | Guidance for this plugin |
| --- | --- |
| [Dock Panel Demo](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/sandboxes/orca_dock_panel_plugin_any.py) | A Script capability opens a host-owned dock panel, reuses an existing panel on subsequent runs, handles refresh/hide messages, and clears the handle on close. The page requests its initial data after installing its message listener. |
| [Orca Inspector](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/sandboxes/orca_inspector_plugin_any.py) | Broader examples of model/preset inspection, explicit success/error replies, refresh-generation identifiers, and worker work initiated by UI message callbacks. |
| [G-code Stamp](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/sandboxes/orca_gcode_stamp_plugin_any.py) | Checks `ctx.step == psGCodePostProcess` and uses `ctx.gcode_path`. This seam operates on export copies and may fire more than once for a slice. Themis must copy bytes rather than apply this sample's in-place text modification. |

These are source examples, not a maintained wheel starter template. The official
[plugin guide](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/plugin_development.html)
documents wheel metadata and discovery. Its statement that the repository has no bundled examples is stale
relative to the pinned source tree. Its Script/UI-thread description is also stale relative to the runtime below.

A [community SpoolMan plugin](https://github.com/StodgyWaif/orcaslicer-spoolman-plugin) is a secondary reference for
packaging and user documentation. Its README describes a development prerelease tested on 2.5.0-dev, so it is not
the compatibility authority for this repository. No community plugin code was copied or installed.

## Source-verified practices

- **Registration:** exactly one `@orca.plugin` package class derives from `orca.base` and registers typed capability
  classes. Keep capability names stable because configuration and preset references use those identities. Our adapter
  follows this pattern and returns a dictionary from `get_default_config()`.
- **Wheel:** use a pure-Python `py3-none-any` wheel, one import package, a single dist-info directory, and no third-party
  runtime dependencies unless needed. Our wheel includes `top_level.txt` naming `themis_orca`, and CI tests the installed
  wheel outside the source tree. PEP 723 headers are for single-file plugins, not required in our wheel modules.
- **Script execution:** in this exact build, both ordinary and coroutine `execute()` methods run on a **host-owned
  per-invocation worker**. See [the async bridge design](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/docs/HLSD/python-plugin-async-bridge.md)
  and [ScriptAsyncRuntime in PluginManager.cpp](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/src/slic3r/plugin/PluginManager.cpp).
  Our one-shot connection-test Script therefore needs no extra Python thread. Do not assume that live model handles
  acquired from a Script worker are an immutable UI-thread snapshot.
- **Panel callbacks:** `on_message` runs on the UI thread. Network work initiated there needs a worker; our independent
  `BackgroundRefresh` helper is intended for that future path, not as another thread inside the connection-test Script.
  Poll queued results or use documented host messaging. Never wait for a worker to finish on the UI thread.
- **Lifecycle:** reuse/show an open panel, clear handles on close, cancel pending work on teardown, and discard results
  after cancellation. Arrange an initial page-to-plugin request because posts before page load can be dropped.
- **Permissions:** declare only permissions actually used. Registration cannot inspect capability config, so do not
  hard-code or request wildcard Themis URLs. The current connection Script has no explicit thread requirement and relies
  on the actual configured request's audit event. In this build, an ungranted off-main-thread event fails immediately
  while the host posts a permission prompt; after the user grants access, retry. See the
  [permissions design](https://github.com/OrcaSlicer/OrcaSlicer/blob/40ecc66f78ed72dc368e0c1ebe40d77f00cc8a19/docs/HLSD/plugin-permissions.md).
  Native host grants may cover a whole host and do not enforce ports, so our client still constructs requests only
  beneath the configured API base and refuses redirects. Do not advise full-access permission as a workaround.
- **Slicing:** keep G-code hooks synchronous and make no `orca.host.ui.*` calls there. The UI can be waiting on the
  slicing worker. Capture context values and file bytes while they are valid; do not retain borrowed graph handles.

## Verification performed

1. Launched the installed OrcaSlicer successfully and confirmed build `40ecc66f` in its startup log.
2. Deferred the unrelated filament-preset migration with **No**; no preset migration was requested for this task.
3. Placed the existing development wheel in a new local folder, `orca_plugins/themis-orca/`, using the documented
   side-loading layout. No existing plugin was overwritten. This is not yet proof that discovery/loading succeeded.
4. Opened Orca's Plugins dialog. The computer-use helper rejected interaction with its embedded WebView as a different
   process (`msedgewebview2.exe`), including the Refresh action after a fresh snapshot and retry. No permission grants
   were changed, no API key was entered, and no full-access switch was enabled.
5. Ran the complete test suite using **Orca's own bundled Python 3.12.13**: **78 passed**. Test-only pytest dependencies
   were loaded from the workspace virtual environment, without installing anything into Orca's Python environment.

Pending in-app checks: refresh/discover the side-loaded wheel, activate the plugin, inspect/restore its configuration,
run with missing settings, reload it, then test an explicitly configured Themis endpoint and its network prompt.
The 78 tests and wheel smoke tests do not substitute for those embedded-host checks. The current wheel has no docked
panel or send action, so these cannot be verified yet.
