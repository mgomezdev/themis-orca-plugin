# BIZ-151 implementation and acceptance

The original issue and sub-issues define the scope, supplemented by the user's plate/object project-import requirements.

| Work | Implementation |
| --- | --- |
| BIZ-379: package, settings, panel | Pure-Python wheel, host-owned dock, paste/copy-friendly API-key field, safe key-label/scopes reporting and background HTTP. |
| BIZ-380: sliced G-code | Immutable export capture and config facts, machine/system-parent matching, editable model, direct job and new/existing-project destinations. |
| BIZ-381: geometry | Exported membership/instance identity, transformed printable-part hull and height, configurable margin, job/plate/object destinations, optional filaments and catalog presets. |
| BIZ-382: overrides/preferences | Edited-preset differences against the system parent, unsupported-key warnings, per-target overrides, ordered preference and strict/no-fallback. |
| BIZ-383: history/updates | UUID saved before upload; request saved before submission; restart recovery, lookup, Update, Retry, Send as new and Open in Themis. |
| BIZ-375–378: backend | Themis PR #199 adds footprint eligibility, target settings, preference claiming, atomic replay/update, migrations 69–71 and OpenAPI. |

Deploy the updated Themis backend before using these sends. The plugin checks its atomic API before uploading.
The provider's existing curated override allowlist is retained; unsupported differences are shown rather than silently applied.
Started work, active pools, and packs shared with unrelated items are protected against replacement.

## Deferred native acceptance

The user is away from the PC and authorized assuming plugin loading works to unblock development. These checks remain
unverified and must not be reported as passed:

- Orca wheel installation/discovery, reload/unload and actual network/filesystem/thread permission prompts.
- Embedded WebView copy/paste, dock behavior, real export/identity/matrix bindings and preset snapshots.
- Export/upload capture, live-Themis sends and real printer execution.
- Whether Bambu Print plate / sliced `.gcode.3mf` export runs the post-process seam. The documented implementation captures raw `.gcode`; Themis format gating still applies.

Orca's post-process context does not identify a plate. A user can explicitly associate a selected export with the current
project/plate for history. Otherwise the export is remembered by content/profile, never guessed from GUI state on a worker.

See [workflows](send-workflows.md), [host source review](orca-2.5-reference.md),
[Themis PR #199](https://github.com/mgomezdev/themis/pull/199), and [BIZ-151](https://linear.app/deviant-mushroom/issue/BIZ-151).
