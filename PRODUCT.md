# Product

## Register

product

## Users and purpose

BIZ-151 describes operators working in OrcaSlicer who send the current plate to Themis as a job or project item.
The plugin belongs beside the Prepare/Preview workspace, with three eventual send modes and explicit Use/Ignore
choices for optional settings. Success means an operator can see which plate and connection are active before sending.

The send workflow must offer a plate job; a plate or selected plate objects added to an existing project; and a plate
or selected plate objects added to a new project. Each import can set eligible printers/models, process overrides,
process preset, quantities, and filament rules. Project imports use their own group so prior project items retain
their settings. Users review an inspected immutable copy; changes made afterward require another inspection.

Sliced G-code can also be added to a new or existing project. Capture an immutable local copy at export time, then
require an explicit choice/send in the panel. Match that slice's exact printer profile to a Themis model and its
physical printers; never substitute the currently selected GUI preset or silently fall back to Any printer.

## Reference and voice

Follow the official v2.5.0 Dock Panel Demo and the source-verified patterns in docs/orca-2.5-reference.md.
Use Orca-owned controls and theme variables. Connection failures name the repair action; unavailable functionality is
described honestly. Keep language concise, practical, and specific to the operator's task.

## Design principles

- Preserve the slicer's working context and keep the panel compact.
- Make connection, plate, and loading state visible.
- Require explicit configuration before network access.
- Keep credentials out of status messages, diagnostics, and reference-data payloads.
- Distinguish completed automated checks from pending embedded-host verification.

## Accessibility

Use labeled native form controls, visible keyboard focus, a password field for the key, and live status text.
Do not communicate errors by color alone. Support narrow dock widths and the host's light/dark theme without
decorative motion. These are implementation standards; no additional user-specific accessibility needs were supplied.

## Scope

This context derives from BIZ-151/BIZ-379, the repository's roadmap and official source examples. No separate marketing
identity or custom visual brand was requested. The user's instruction is to proceed with host-loading verification
assumed for now; verification remains pending and must not be reported as passed.
