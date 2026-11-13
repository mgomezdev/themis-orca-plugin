# Plate and object workflows

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
