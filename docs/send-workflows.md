# Plate, object and G-code workflows

1. Configure the connection and refresh Themis data.
2. Open the desired plate in Prepare or Preview and choose **Inspect current plate**. Orca exports an immutable 3MF copy,
   including unsaved edits. Plate membership and object IDs come from that copy's model metadata.
3. Choose one action:
   - **Create a job for this plate**: upload geometry and queue one job for Themis to slice for eligible targets.
   - **Add plate to an existing project**: create a locked `3mf_plate` item referencing the selected plate.
   - **Add objects to an existing project**: create `3mf_object` items for the selected exported object IDs.
   - **Add plate to a new project** or **Add objects to a new project**: create a planning-stage project, then add the items.
4. Choose quantities and printer/model eligibility, or **Any printer**. Choose a catalog process preset or leave it at
   Ignore. A Use filament rule applies the entered type/subtype/color/vendor to imported items or job targets; omitted
   fields remain unconstrained. A type requires a subtype (`standard` or `any` are common choices).
5. Optionally supply curated process overrides as JSON. They apply directly to a job, or to the import group's future
   generated/claimed jobs. No earlier project items, existing groups, or previously created jobs are modified.
6. Choose **Send inspected copy**. Project imports do not automatically generate/queue jobs; do that in Themis when ready.

Orca's export API writes the full project archive. Themis selects only the chosen plate/objects for jobs/items, but other
plates remain in the uploaded library file. This is disclosed next to the inspection controls before sending.

## Sliced G-code project imports

1. In the Orca process preset, select **Themis: Capture G-code** in slicing pipeline plugins. Place it last so its
   copy includes changes from earlier post-process plugins. Slice and export G-code. The hook copies the working file
   unchanged into plugin storage and captures `printer_settings_id` from that export's config. It does not upload,
   create records, change the original G-code, read the current GUI printer, or open UI on the slicing worker.
2. Open the Themis panel and refresh reference data. Choose **Add sliced G-code to an existing project** or
   **Add sliced G-code to a new project**. Select the captured export by name/profile, choose the project/name and quantity.
   The capture may belong to a different plate than the current view; geometry inspection is not used for this path.
3. Review automatic eligible printers. The export's machine profile must exactly match a `laminus` mapping for one
   enabled/usable Themis registry model. Only physical printers with that model and the same resolved machine profile
   are targeted, so other nozzle variants are excluded. Missing/ambiguous mappings or no matching printer block sending;
   configure the model/profile/nozzle in Themis and refresh. No fuzzy name matching or Any-printer fallback is used.
4. Choose **Send captured G-code**. Upload includes `eligible_model_uuids` and uses a model-specific `/Orca G-code/<UUID>`
   folder to isolate content deduplication from other models' uploads. The upload response must confirm eligibility;
   the new import group's PATCH must confirm its exact printer targets before any item is added.
5. The project gets one locked `gcode` item referencing raw-file plate `1`, with quantity equal to the number of copies.
   Generate/queue in Themis when ready. It prints those bytes as-is; geometry process overrides, process presets and
   filament-rule inputs are hidden and rejected for this send. Existing project items and groups are unchanged.

The hook supplies **raw `.gcode`**, not a sliced `.gcode.3mf` archive. Themis's printer-format checks still apply.
For example, its Bambu adapter accepts sliced archives and refuses raw G-code; this path cannot make that format
compatible. Archive capture needs a separate host-supported export path and is not emulated by renaming raw bytes.

Captures remain local until explicitly sent. Repeated export hooks with identical bytes/profile reuse one capture;
at most eight captures are retained in a session, and an in-flight copy cannot be evicted/cleared. Submitted captures
cannot be sent again from that session list. **Clear captured exports** removes idle local copies, not Themis files.
Captures are also cleared on normal panel-capability unload; a crash/forced exit can leave files in plugin storage.
Persistent send history and reconciliation across restarts remain BIZ-383 work. Check Themis after uncertain sends.

## Quantities and identity

A plate job is one plate, quantity 1. Plate project-item quantity is the number of plate copies. Object item quantities
are selected-plate instance count multiplied by the entered quantity; IDs are exported 3MF IDs, never host runtime IDs.
Objects on other plates are not offered by the form. Inspect again after editing or changing plate.

The plugin creates one import-specific group for each project send. It configures the group before adding any items,
which prevents an item from landing in an unconfigured Default Group. The operator's other groups are unchanged.

## Backend compatibility

The APIs used are `/files/upload`, `/jobs`, `/projects`, `/projects/{id}/groups`,
`/projects/{id}/groups/{group_id}` and `/projects/{id}/items`. The schema of `GroupPatch` at the deployment's
`/openapi.json` is checked before a project send with overrides. If the field is absent, no upload/project/group/item
writes occur. The PATCH response must also confirm the requested overrides before items are added. Deploy Themis's
project-group override extension (migration 68) first. Unknown override keys are rejected rather than silently dropped.

Supported override names: `layer_height`, `wall_loops`, `top_shell_layers`, `bottom_shell_layers`,
`sparse_infill_density`, `sparse_infill_pattern`, `enable_support`, `support_type`, `support_threshold_angle`,
`support_on_build_plate_only`, `raft_layers`, `brim_type`, `brim_width`, `ironing_type`.

## Interrupted or partial sends

Writes run off the UI thread. The panel blocks concurrent/duplicate sends of the inspected copy and does not retry
POST requests automatically. New-project creation has a UUID external reference and Idempotency-Key; item/group/job
creation is not yet covered by BIZ-378's planned end-to-end idempotency contract. A lost response can therefore mean
the server created work even though the plugin shows an error. Check Themis before inspecting/submitting another copy.
Known project/group/job/item IDs are retained in the result to help reconcile partial imports. No destructive automatic
rollback is attempted. Full send-history/update support remains BIZ-383 work.

## Verification boundary

Automated tests cover all five action plans, exact API request sequences, selected object quantities, ignore semantics,
multipart file bytes, schema checks, partial writes, duplicate sends, and thread placement. The backend tests cover
override persistence/clearing, group isolation, fixed/pool job propagation, pre-sliced rejection, migration round trips,
and its OpenAPI contract. Actual Orca and live-Themis verification remains deferred at the user's request.
G-code tests additionally cover immutable capture, repeated hook deduplication, retention during sends, export-time
profile capture without UI calls, exact/ambiguous model matches, nozzle-specific physical targets, file/group response
confirmation, and both project destinations. The [optional Themis contract suite](../integration/README.md) exercises
the real API/database/store and proves generation creates fixed jobs from unchanged bytes without calling a builder.
