import pytest
from turret_placer import depth_factor, in_range, tile_weight, score_placement, score_upgrade, compute_threat_surface, candidate_cells, existing_turrets, init_coverage


class _Unit:
    def __init__(self, unit_type, upgraded=False):
        self.unit_type = unit_type
        self.upgraded = upgraded


class _StubGameStateUnits:
    def __init__(self, units):
        # units: dict[(x,y)] -> _Unit or None
        self._units = {tuple(k): v for k, v in units.items()}

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))


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


# Damage constants from the spec
RAW_DMG = 6
UP_DMG = 20


def test_score_upgrade_in_raw_only():
    # Tile at distance 1.0 from turret — already in raw 2.5 range.
    # Gain per tile: (UP_DMG - RAW_DMG) * weight = 14 * 1.0
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 1}
    s = score_upgrade((10, 12), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == pytest.approx(14.0)


def test_score_upgrade_in_annulus_only():
    # Tile at distance 3.0 from turret — outside raw, inside upgraded.
    # Gain: UP_DMG * weight = 20 * 1.0
    threat_count = {(13, 13): 1}
    coverage = {(13, 13): 0}
    s = score_upgrade((10, 13), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == pytest.approx(20.0)


def test_score_upgrade_outside_upgraded_range_zero():
    threat_count = {(20, 13): 1}
    coverage = {(20, 13): 0}
    s = score_upgrade((5, 13), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == 0.0


def test_score_upgrade_no_depth_factor_applied():
    # depth_factor must NOT scale upgrade scores (turret already exists at its location).
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 1}
    s_y8 = score_upgrade((10, 8), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    # (10,8) → (10,13) distance 5.0, outside upgraded 3.5 → 0
    assert s_y8 == 0.0
    # Test a tile actually in range with low-y turret:
    threat_count2 = {(10, 9): 1}
    coverage2 = {(10, 9): 1}
    s_y8_close = score_upgrade((10, 8), threat_count2, coverage2, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    # Tile in raw range, weight=1.0, gain=14, NO depth multiplier
    assert s_y8_close == pytest.approx(14.0)


class _StubGameMap:
    TOP_LEFT = "TL"
    TOP_RIGHT = "TR"
    BOTTOM_LEFT = "BL"
    BOTTOM_RIGHT = "BR"

    def __init__(self, edge_locs):
        self._edge_locs = edge_locs

    def get_edge_locations(self, edge):
        return self._edge_locs[edge]


class _StubGameState:
    def __init__(self, edge_locs, paths):
        self.game_map = _StubGameMap(edge_locs)
        self._paths = paths  # {(start_tuple, target_str): [path_cells]}

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))


def test_compute_threat_surface_counts_paths_on_our_side_only():
    # Two enemy edge cells, each with a path. Tiles at y<=13 should count.
    edges = {
        "TL": [[0, 14]],  # one enemy top-left cell
        "TR": [[27, 14]],  # one enemy top-right cell
    }
    paths = {
        ((0, 14), "BR"): [[0, 14], [1, 13], [2, 12], [3, 11]],
        ((27, 14), "BL"): [[27, 14], [26, 13], [25, 12]],
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    # Enemy-side cells (y >= 14) excluded; only y <= 13 cells counted.
    assert threat == {
        (1, 13): 1,
        (2, 12): 1,
        (3, 11): 1,
        (26, 13): 1,
        (25, 12): 1,
    }


def test_compute_threat_surface_skips_blocked_cells():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]]}
    paths = {
        ((0, 14), "BR"): None,  # blocked — no path
        ((27, 14), "BL"): [[27, 14], [26, 13]],
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    assert threat == {(26, 13): 1}


def test_compute_threat_surface_increments_shared_tiles():
    edges = {"TL": [[0, 14], [1, 14]], "TR": []}
    paths = {
        ((0, 14), "BR"): [[0, 14], [5, 13]],
        ((1, 14), "BR"): [[1, 14], [5, 13]],  # same tile both paths
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    assert threat[(5, 13)] == 2


class _StubGameStateOccupancy:
    def __init__(self, occupied):
        self._occupied = {tuple(c) for c in occupied}

    def contains_stationary_unit(self, loc):
        return tuple(loc) in self._occupied


def test_candidate_cells_returns_only_upper_half_diamond():
    gs = _StubGameStateOccupancy(occupied=[])
    cells = candidate_cells(gs)
    # Spot-check: the arena is a diamond. At y=13 our row is x in [0,27]; at y=8 it shrinks.
    assert (0, 13) in cells
    assert (27, 13) in cells
    # y=7 is excluded (below upper half)
    assert (10, 7) not in cells
    # y=14 is enemy side
    assert (10, 14) not in cells


def test_candidate_cells_excludes_occupied():
    gs = _StubGameStateOccupancy(occupied=[[10, 13], [11, 12]])
    cells = candidate_cells(gs)
    assert (10, 13) not in cells
    assert (11, 12) not in cells
    assert (12, 12) in cells  # neighbor still candidate


def test_candidate_cells_y_range_strict():
    gs = _StubGameStateOccupancy(occupied=[])
    cells = candidate_cells(gs)
    ys = {y for (_, y) in cells}
    assert ys == {8, 9, 10, 11, 12, 13}


def test_existing_turrets_returns_only_unupgraded_turrets():
    units = {
        (2, 12): _Unit("TURRET", upgraded=False),
        (6, 13): _Unit("TURRET", upgraded=True),  # already upgraded — exclude
        (13, 12): _Unit("SUPPORT"),                # not a turret
        (10, 10): _Unit("WALL"),                   # not a turret
    }
    gs = _StubGameStateUnits(units)
    result = existing_turrets(gs, turret_shorthand="TURRET")
    assert (2, 12) in result
    assert (6, 13) not in result
    assert (13, 12) not in result
    assert (10, 10) not in result


def test_existing_turrets_only_upper_half():
    units = {
        (10, 5): _Unit("TURRET"),   # below upper half — exclude
        (10, 13): _Unit("TURRET"),  # in upper half
    }
    gs = _StubGameStateUnits(units)
    result = existing_turrets(gs, turret_shorthand="TURRET")
    assert (10, 5) not in result
    assert (10, 13) in result


def test_init_coverage_counts_anchors_in_range_of_threat():
    threat = {(10, 13): 1, (11, 13): 1, (20, 13): 1}
    anchors = [(10, 12)]  # in range of (10,13) and (11,13), not (20,13)
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov[(10, 13)] == 1
    assert cov[(11, 13)] == 1
    assert cov[(20, 13)] == 0


def test_init_coverage_stacks_multiple_anchors():
    threat = {(10, 13): 1}
    anchors = [(10, 12), (11, 12)]  # both in range of (10,13)
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov[(10, 13)] == 2


def test_init_coverage_initializes_uncovered_to_zero():
    threat = {(10, 13): 1, (20, 13): 1}
    anchors = []
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov == {(10, 13): 0, (20, 13): 0}


from turret_placer import place_turrets


class _OrchestratorStub:
    """Combines map, paths, occupancy, units, SP, and spawn/upgrade actions."""

    TURRET_COST = 3
    UPGRADE_COST = 8

    def __init__(self, sp, edges, paths, units):
        self._sp = sp
        self._edges = edges
        self._paths = paths
        self._units = {tuple(k): v for k, v in units.items()}
        self.spawn_calls = []
        self.upgrade_calls = []
        self.game_map = _StubGameMap(edges)

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))

    def get_resource(self, resource_type, _player=0):
        return self._sp

    def type_cost(self, unit_type, upgrade=False):
        # Return [SP, MP] cost. Index 0 (SP) is what placer reads.
        if upgrade:
            return [self.UPGRADE_COST, 0]
        return [self.TURRET_COST, 0]

    def attempt_spawn(self, unit_type, loc, count=1):
        loc = tuple(loc)
        if self._sp < self.TURRET_COST:
            return 0
        self._sp -= self.TURRET_COST
        self.spawn_calls.append(loc)
        self._units[loc] = _Unit("TURRET", upgraded=False)
        return 1

    def attempt_upgrade(self, loc):
        loc = tuple(loc)
        if self._sp < self.UPGRADE_COST:
            return 0
        if loc not in self._units:
            return 0
        self._sp -= self.UPGRADE_COST
        self.upgrade_calls.append(loc)
        self._units[loc].upgraded = True
        return 1


def _make_simple_stub(sp, anchors=()):
    # Single enemy path going straight down through x=14.
    edges = {"TL": [], "TR": [[14, 27]], "BL": [], "BR": []}
    path = [[14, 27 - i] for i in range(28)]  # crosses y=13..0 at x=14
    paths = {((14, 27), "BL"): path}
    units = {tuple(a): _Unit("TURRET", upgraded=False) for a in anchors}
    return _OrchestratorStub(sp, edges, paths, units)


def test_place_turrets_spends_until_sp_below_3():
    stub = _make_simple_stub(sp=10)  # 3 turrets affordable, 1 SP left
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert len(stub.spawn_calls) == 3
    assert stub._sp == 1
    assert result["stopped_reason"] in ("budget_exhausted", "no_positive_score")


def test_place_turrets_upgrade_fallback_runs_after_placement():
    # Anchor at (14,12) covers (14,13) etc. After all candidate placements
    # (in the simple-path stub, every relevant placement has already been made),
    # leftover SP >= 8 should trigger upgrade.
    # SP = 9: too little for upgrade after spending most on placements.
    # SP = 100: plenty for upgrades.
    stub = _make_simple_stub(sp=100, anchors=[(14, 12)])
    result = place_turrets(stub, anchor_locations=[(14, 12)], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    # At least one upgrade should fire (some turret is in range of threat tiles).
    assert len(stub.upgrade_calls) >= 1


def test_place_turrets_strict_priority_no_upgrade_until_placement_exhausted():
    # Tiny budget — only 3 SP. Placement gets the spend, no upgrade ever.
    stub = _make_simple_stub(sp=3, anchors=[(14, 12)])
    place_turrets(stub, anchor_locations=[(14, 12)], turret_shorthand="TURRET",
                   scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert len(stub.spawn_calls) == 1
    assert len(stub.upgrade_calls) == 0


def test_place_turrets_returns_action_log():
    stub = _make_simple_stub(sp=6)
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert "placed" in result
    assert "upgraded" in result
    assert "stopped_reason" in result
    assert len(result["placed"]) == 2  # 6 SP / 3 = 2 turrets


def test_place_turrets_no_threat_does_nothing():
    # Path is blocked from every enemy edge → empty threat surface.
    edges = {"TL": [[0, 14]], "TR": [[27, 14]], "BL": [], "BR": []}
    paths = {((0, 14), "BR"): None, ((27, 14), "BL"): None}
    stub = _OrchestratorStub(sp=10, edges=edges, paths=paths, units={})
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert stub.spawn_calls == []
    assert result["stopped_reason"] == "no_threat"
