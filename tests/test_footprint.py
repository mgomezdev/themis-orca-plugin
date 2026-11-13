from itertools import permutations
from math import cos, radians, sin, sqrt

import pytest

from themis_orca.footprint import plate_footprint


def box(x, y, z, *, dx=0, dy=0):
    return [(dx + a, dy + b, c) for a in (0, x) for b in (0, y) for c in (0, z)]


def test_300_mm_plate_does_not_understate_bed_requirement():
    footprint = plate_footprint(box(300, 300, 30))
    assert footprint.min_bed_mm() == {"x": 300, "y": 300, "z": 30}
    assert footprint.x > 256 and footprint.y > 256
    assert len(footprint.hull_xy) == 4


def test_rotated_part_uses_world_vertices():
    angle = radians(45)
    vertices = [(x * cos(angle) - y * sin(angle), x * sin(angle) + y * cos(angle), z)
                for x, y, z in box(100, 20, 25)]
    footprint = plate_footprint(vertices)
    assert footprint.x == pytest.approx(120 / sqrt(2))
    assert footprint.y == pytest.approx(120 / sqrt(2))
    assert footprint.z == 25


def test_separated_instances_include_space_between_parts():
    vertices = box(20, 30, 10, dx=-100) + box(20, 30, 40, dx=180, dy=50)
    footprint = plate_footprint(vertices)
    assert footprint.min_bed_mm() == {"x": 300, "y": 80, "z": 40}


def test_empty_plate_is_not_a_zero_sized_send():
    assert plate_footprint(iter(())) is None


def test_margin_is_on_each_xy_edge_and_does_not_change_height():
    footprint = plate_footprint(box(300, 200, 50), margin_mm=2.5)
    assert footprint.min_bed_mm() == {"x": 305, "y": 205, "z": 50}


def test_height_is_above_bed_not_relative_to_lowest_vertex():
    assert plate_footprint([(0, 0, 20), (20, 30, 100)]).z == 100


def test_xy_translation_cannot_change_required_bed_size():
    vertices = box(100, 20, 30)
    shifted = [(x - 1000, y + 2000, z) for x, y, z in vertices]
    assert plate_footprint(vertices).min_bed_mm() == plate_footprint(shifted).min_bed_mm()


def test_hull_is_order_independent_and_discards_interior_duplicate_collinear_points():
    corners = [(0, 0, 1), (10, 0, 1), (10, 10, 1), (0, 10, 1)]
    expected = ((0, 0), (10, 0), (10, 10), (0, 10))
    for ordering in permutations(corners):
        vertices = [*ordering, (0, 0, 1), (5, 5, 1), (5, 0, 1)]
        assert plate_footprint(vertices).hull_xy == expected


def test_collinear_and_single_point_inputs_have_defined_extents():
    assert plate_footprint([(0, 0, 1), (5, 5, 2), (10, 10, 3)]).hull_xy == ((0, 0), (10, 10))
    assert plate_footprint([(1, 1, 5)]).min_bed_mm() == {"x": 0, "y": 0, "z": 5}


@pytest.mark.parametrize("margin", [-1, float("nan"), float("inf"), "invalid", None])
def test_invalid_margins_cannot_shrink_or_corrupt_requirements(margin):
    with pytest.raises(ValueError, match="margin"):
        plate_footprint(box(10, 10, 10), margin_mm=margin)


@pytest.mark.parametrize("vertex", [(0, 0, float("nan")), (float("inf"), 0, 0), (1, 2), None, ("invalid", 0, 0)])
def test_invalid_geometry_cannot_produce_an_eligible_plate(vertex):
    with pytest.raises(ValueError, match="finite coordinates"):
        plate_footprint([vertex])


def test_entirely_below_bed_geometry_is_invalid():
    with pytest.raises(ValueError, match="bed plane"):
        plate_footprint([(0, 0, -2), (10, 10, -1)])
