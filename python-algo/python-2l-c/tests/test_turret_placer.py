import pytest
from turret_placer import depth_factor, in_range, tile_weight, score_placement


@pytest.mark.parametrize("y,expected", [
    (13, 0.90),
    (12, 0.95),
    (11, 0.95),
    (10, 0.95),
    (9, 0.70),
    (8, 0.60),
])
def test_depth_factor_table(y, expected):
    assert depth_factor(y) == pytest.approx(expected)


def test_depth_factor_below_range_raises():
    with pytest.raises(ValueError):
        depth_factor(7)


def test_depth_factor_above_range_raises():
    with pytest.raises(ValueError):
        depth_factor(14)


def test_in_range_same_cell():
    assert in_range((10, 10), (10, 10), 2.5) is True


def test_in_range_two_cells_apart_within_25():
    # Cell-center to cell-center distance: math.dist((10.5,10.5),(12.5,10.5)) == 2.0 ≤ 2.5
    assert in_range((10, 10), (12, 10), 2.5) is True


def test_in_range_three_cells_apart_outside_25():
    # Distance 3.0 > 2.5
    assert in_range((10, 10), (13, 10), 2.5) is False


def test_in_range_diagonal_within_upgraded_range():
    # math.dist((10.5,10.5),(12.5,12.5)) == sqrt(8) ≈ 2.83, > 2.5 but ≤ 3.5
    assert in_range((10, 10), (12, 12), 2.5) is False
    assert in_range((10, 10), (12, 12), 3.5) is True


def test_in_range_at_exact_boundary():
    # math.dist((10.5,10.5),(13.0,10.5)) == 2.5, but cells are integer so test (10,10)→(12,10) above.
    # Test (10,10)→(13,10): center-to-center 3.0, never ≤ 2.5.
    assert in_range((10, 10), (13, 10), 3.0) is True


def test_tile_weight_gap_fill_uncovered():
    coverage = {(5, 13): 0, (6, 13): 2}
    threat_count = {(5, 13): 3, (6, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "gap_fill") == 1.0


def test_tile_weight_gap_fill_already_covered():
    coverage = {(5, 13): 2}
    threat_count = {(5, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "gap_fill") == 0.2


def test_tile_weight_stacking_constant():
    coverage = {(5, 13): 0}
    threat_count = {(5, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "stacking") == 1.0
    coverage = {(5, 13): 5}
    assert tile_weight((5, 13), coverage, threat_count, "stacking") == 1.0


def test_tile_weight_path_freq_normalized():
    coverage = {}
    threat_count = {(5, 13): 4, (6, 13): 8, (7, 13): 2}
    # max threat = 8
    assert tile_weight((6, 13), coverage, threat_count, "path_freq") == 1.0
    assert tile_weight((5, 13), coverage, threat_count, "path_freq") == 0.5
    assert tile_weight((7, 13), coverage, threat_count, "path_freq") == 0.25


def test_tile_weight_path_freq_empty_threat_count():
    assert tile_weight((5, 13), {}, {}, "path_freq") == 0.0


def test_tile_weight_unknown_mode_raises():
    with pytest.raises(ValueError):
        tile_weight((5, 13), {}, {}, "bogus")


def test_score_placement_no_threat_in_range_returns_zero():
    cell = (5, 13)
    threat_count = {(20, 13): 5}  # far away
    coverage = {(20, 13): 0}
    score = score_placement(cell, threat_count, coverage, attack_range=2.5, mode="path_freq")
    assert score == 0.0


def test_score_placement_in_range_path_freq():
    # Turret at (10,12), tile (10,13) → distance 1.0, in range.
    # path_freq weight: threat_count[10,13]=4 / max=4 → weight 1.0
    # depth_factor(12) = 0.95
    # Expected: 1.0 * 0.95 = 0.95
    cell = (10, 12)
    threat_count = {(10, 13): 4, (20, 13): 4}
    coverage = {(10, 13): 0, (20, 13): 0}
    score = score_placement(cell, threat_count, coverage, attack_range=2.5, mode="path_freq")
    assert score == pytest.approx(0.95)


def test_score_placement_gap_fill_prefers_uncovered():
    cell = (10, 12)
    threat_count = {(10, 13): 1, (11, 13): 1}
    coverage_uncov = {(10, 13): 0, (11, 13): 0}
    coverage_cov = {(10, 13): 2, (11, 13): 2}
    s_uncov = score_placement(cell, threat_count, coverage_uncov, attack_range=2.5, mode="gap_fill")
    s_cov = score_placement(cell, threat_count, coverage_cov, attack_range=2.5, mode="gap_fill")
    assert s_uncov > s_cov


def test_score_placement_depth_decay_applies():
    # Same neighbor tile, two candidate y rows.
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 0}
    s_y13 = score_placement((10, 13), threat_count, coverage, 2.5, "stacking")
    s_y8 = score_placement((10, 8), threat_count, coverage, 2.5, "stacking")
    # (10,13) is in range of itself, depth_factor(13)=0.90 → 0.90.
    # (10,8) is distance 5 from (10,13), out of 2.5 range → 0.
    assert s_y13 == pytest.approx(0.90)
    assert s_y8 == 0.0
