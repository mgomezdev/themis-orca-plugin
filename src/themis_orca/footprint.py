"""Minimum bed dimensions from selected printable parts' world-space vertices.

The host adapter must filter by plate membership and printability, and apply
volume and instance transforms before calling this function. This module neither
reads a live Orca model nor substitutes bounding boxes for transformed meshes.
"""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PlateFootprint:
    hull_xy: tuple[tuple[float, float], ...]
    x: float
    y: float
    z: float

    def min_bed_mm(self):
        return {"x": self.x, "y": self.y, "z": self.z}


def _convex_hull(points):
    """Monotone chain; duplicate and interior collinear points are omitted."""
    points = sorted(set(points))
    if len(points) <= 1:
        return tuple(points)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(sequence):
        result = []
        for point in sequence:
            while len(result) >= 2 and cross(result[-2], result[-1], point) <= 0:
                result.pop()
            result.append(point)
        return result[:-1]

    return tuple(half(points) + half(reversed(points)))


def plate_footprint(world_vertices, *, margin_mm=0) -> PlateFootprint | None:
    """Return hull extents plus X/Y margin on each edge, or None for an empty plate.

    Height is maximum world Z above the bed plane (Z=0), not max Z minus
    min Z. Margin applies to X and Y only. Placement within Orca's coordinate
    system does not add to X/Y size: Themis may center the exported plate.
    """
    try:
        margin = float(margin_mm)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Plate margin must be a finite non-negative number.") from None
    if not isfinite(margin) or margin < 0:
        raise ValueError("Plate margin must be a finite non-negative number.")
    xy = []
    max_z = None
    for vertex in world_vertices:
        try:
            x, y, z = map(float, vertex)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Plate vertices must have three finite coordinates.") from None
        if not all(isfinite(v) for v in (x, y, z)):
            raise ValueError("Plate vertices must have three finite coordinates.")
        xy.append((x, y))
        max_z = z if max_z is None else max(max_z, z)
    if not xy:
        return None
    if max_z < 0:
        raise ValueError("The plate has no geometry at or above the bed plane.")
    hull = _convex_hull(xy)
    x = max(p[0] for p in hull) - min(p[0] for p in hull) + 2 * margin
    y = max(p[1] for p in hull) - min(p[1] for p in hull) + 2 * margin
    if not all(isfinite(v) for v in (x, y)):
        raise ValueError("Plate dimensions exceed the supported numeric range.")
    return PlateFootprint(hull, x, y, max_z)
