# Sending work to Themis

## Connection and API key

Open **Themis: Test connection** to show the full dock panel. The capability name stays unchanged to preserve saved configuration.
**Connection settings** is first and opens automatically when unconfigured. Enter the URL and paste the API key with
Ctrl+V (Cmd+V on macOS). **Show entered API key** reveals the entered value for native selection/copy with Ctrl+C/Cmd+C.
No editing/paste shortcuts are intercepted. Save clears and masks the entered field; Orca-managed configuration retains
the key. Leave the field blank to keep a stored key, or use **Forget API key** to remove it.

**Test connection & refresh** reports role, the key label when available, and missing scopes. Staff keys have labels,
not a human-owner relation; no owner is invented. Every send/retry rechecks authentication and required scopes.
Local-network fallback alone cannot authorize a plugin send. The stored secret is never returned to the page or history.

Reference reads need `printers:read`, `projects:read`, `laminus:read`. Sends need `jobs:read` and destination
`jobs:write` / `projects:write`; uploads also need `files:write`. Project-send lookup needs `projects:read`.
Only the configured URL is used; wildcard network grants and credential-forwarding redirects are not requested.

## Geometry

Choose **Inspect current plate** in Prepare/Preview, then:

- **Create a job for this plate** uploads geometry for Themis to slice.
- **Add plate to an existing/new project** creates a locked `3mf_plate` item.
- **Add objects to an existing/new project** creates selected `3mf_object` items.

Select/name the project and choose eligibility. **Any printer** stands alone. Job quantity is 1. Plate-item quantity is
copies; object quantity is selected-plate instance count multiplied by quantity. Other-plate/non-printable instances
are excluded. Inspect again after changing the plate or its geometry.

The required bed comes from the convex hull of printable-part world vertices, using both volume and instance matrices.
Exported membership/identity selects the correct instances; runtime object order is not assumed. Modifiers/negative volumes
are excluded. Height is max world Z, and margin adds to each X/Y edge. Themis checks fit at target expansion and claim,
including later printer/bed changes. Individually selected objects are repacked, so their old plate arrangement is irrelevant.

Orca exports the **full project archive**. Only selected content becomes work, but other plates remain in the library file.
Each import gets a dedicated configured group. New projects start in planning; generate/queue in Themis when ready.

## Optional settings

**Load inspected Orca preset settings** fills defaults from the inspected snapshot. Use/Ignore remains explicit:

- Process preset can be a catalog name or Ignore. Inherited user presets fall back to a matching parent/system name and are flagged. Missing/cyclic inheritance is reported.
- **Use per-filament requirements from Orca** includes type/subtype/color/vendor per model filament. Review/edit the JSON for the selected plate.
- **Use per-filament catalog presets** independently includes profile names. Ignoring either omits those fields. A single filament rule is also available; it supplies defaults for each map entry, with explicit per-filament fields taking precedence.
- Common process overrides default to edited-preset differences against the stored system parent, including unsaved process edits. Supported keys follow the provider's curated contract. Unsupported differences are listed and not copied.
- Individual target overrides are JSON keyed by eligible picker keys, e.g. `{"5":{"wall_loops":"4"}}`. They win over common overrides, which win over printer defaults. Unknown/non-finite/container values are rejected; effective settings enter cache keys.
- Add preferred printers/models and use **Move up/down/Remove**. Idle eligible preferences get first chance. Busy/ineligible preferences do not delay fallback. **Only these** disables fallback. Preferences never widen eligibility.

## Sliced G-code

Enable **Themis: Capture G-code** in the process preset's slicing pipeline plugins, place it last, then slice/export.
The synchronous hook copies bytes unchanged and records export-time printer preset/model, nozzle and filament facts.
It does no UI or network work and never substitutes the currently selected GUI printer.

Choose **Create a job from sliced G-code** or **Add sliced G-code to an existing/new project**, then select an export.
The model defaults from its exact machine-profile mapping/system parent and stays editable. An unmatched/ambiguous
capture needs explicit model selection. Choose the model this G-code was sliced for. Upload records that model's
eligibility. A direct job has one model target and no explicit printers; a project receives a locked `gcode` item.
G-code uses raw-file plate 1, with project quantity as copies. Geometry settings are hidden/rejected; no re-slicing occurs.

**Remember this export as the current project/plate** explicitly associates history when the user knows it belongs there.
The hook does not supply a plate identity. Otherwise history follows the bytes/profile and remains in the saved-send picker.

The implemented path supplies **raw `.gcode`**, not sliced `.gcode.3mf`. Themis still enforces printer-format support;
its Bambu adapter refuses raw G-code. Bambu's archive/export seam remains part of deferred native verification. Renaming
raw bytes is not archive support. Repeated identical hooks reuse a capture; eight copies are retained per session and
active copies cannot be evicted. Clear/unload removes idle local copies; a crash can leave copies in plugin storage.

## History, retry and update

A UUID is saved **before upload**, and the full prepared request is saved on the UI thread **before submission**.
Themis atomically commits the ledger and job/import. Invalid imports leave no partial work; separately deduplicated
uploads may remain in the library. The most recent 100 histories are kept in host configuration, separately per server.
Saved projects use path + plate; unsaved projects use a session key. G-code also has a content/profile identity.

- **Retry saved send** reuses the exact UUID/request, without re-uploading. It recovers a lost response or restart and returns the original IDs.
- **Refresh send status** fetches current state. Until refreshed, status is explicitly the last known state.
- **Update previous send** uses a newly inspected/captured source. Queued/blocked jobs retain their IDs while source/settings replace stale slices/estimates.
- Project work can be replaced/regenerated while every affected job is unstarted and contains only this send's items. Failed repacks restore old work and remove new artifacts. Started work, active pools and unrelated shared packs return 409.
- **Send as new** creates a new identity and retains the old record. **Open in Themis** opens its job/project. The saved-send picker also recovers records whose original local project is no longer open.

Deploy Themis migrations 69–71, plus group overrides from 68. The plugin checks the atomic API before uploading and
never silently drops requirements on an older server. API/DB/store integration tests run without a live server/printer.
Actual Orca installation, embedded clipboard behavior, permissions and live sends remain deferred by the user.
