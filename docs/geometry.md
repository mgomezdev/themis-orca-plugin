# Plate footprint contract (BIZ-381)

`themis_orca.footprint.plate_footprint(world_vertices, margin_mm=0)` computes the XY convex hull and
minimum bed dimensions without Orca, NumPy, or network access. It returns `None` for an empty plate so callers can
block sending. Non-finite geometry and negative/non-finite margins are rejected.

The adapter must supply all vertices of **printable parts on the selected plate**, after applying volume and instance
transforms. Non-printable parts, supports represented by non-part volumes, and objects on other plates must be excluded by
the adapter. This function cannot infer plate membership or printability from bare vertices.

The result's `min_bed_mm()` contains `x`, `y`, and `z`. X/Y are the world-aligned hull extents, including gaps between parts.
The margin is applied on each of the four XY edges; a 300 × 300 plate with a 2 mm margin requires 304 × 304 mm.
Height is maximum world Z above the bed plane (Z=0), without adding margin or subtracting minimum Z.
XY translation does not change the required bed dimensions. The calculation does not rotate the plate to find a smaller
rectangle; it preserves the orientation of the sliced/exported plate.

This is the independently tested calculation layer. 3MF plate-membership parsing, host mesh/transform capture, export,
filament/preset options, sending, and server-side eligibility enforcement remain pending. Do not interpret these unit tests
as proof that the current Themis claim loop enforces bed dimensions; that requires backend BIZ-375.
