# BIZ-151 implementation map

The user selected a standalone `orca-plugin` repository, superseding the earlier issue comment suggesting `integrations/orcaslicer/` inside Themis.

## Plugin work

1. BIZ-379: package, configuration, connection test, docked panel and reference data.
2. BIZ-380: capture G-code on the slicing worker, then send unchanged bytes for a selected printer model.
3. BIZ-381: export geometry, resolve plate membership, calculate footprint, optional filaments/presets.
   The pure world-space footprint calculation is implemented separately; see [its input contract](geometry.md).
4. BIZ-382: per-target preset differences and ordered printer preferences.
5. BIZ-383: persist send identity and update previous sends.

## Backend dependencies (Themis repository)

- BIZ-375: footprint eligibility.
- BIZ-376: per-target overrides.
- BIZ-377: preference-aware claiming.
- BIZ-378: idempotent sends and updates to unstarted work.

Do not invent routes or silently emulate these missing backend guarantees. Confirm contracts before implementing sending.

## Host constraints

Target Orca 2.5.x, with the exact host build recorded during verification. Use host-owned UI. Export 3MF through the supported UI-thread path. Plate membership must come from the exported `Metadata/model_settings.config`. G-code capture uses `psGCodePostProcess` with the plugin enabled in the process preset; no UI calls from that worker. A normal completion event does not provide G-code bytes.

In v2.5.0 build `40ecc66f`, Script actions run on a host-owned worker; panel message callbacks run on the UI thread.
The official wiki has stale descriptions of this behavior. Follow the [pinned source review](orca-2.5-reference.md).

## Sources

- [BIZ-151](https://linear.app/deviant-mushroom/issue/BIZ-151), including sub-issues and agent notes.
- [Official plugin guide](https://www.orcaslicer.com/wiki/developer_reference/plugin_development/plugin_development.html).
- [Orca v2.5.0 plugin source](https://github.com/OrcaSlicer/OrcaSlicer/tree/v2.5.0/src/slic3r/plugin).
