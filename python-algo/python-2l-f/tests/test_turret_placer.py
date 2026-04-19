import pytest
from turret_placer import (
    in_range,
    corner_factor,
    compute_threat_surface,
    score_placement,
    score_upgrade,
    place_turrets,
    existing_turrets,
    find_most_dangerous_enemy_path,
    _damage_along_path,
    WEAKNESS_BOOST_FACTOR,
)


# --- in_range --------------------------------------------------------------

def test_in_range_same_cell():
    assert in_range((10, 10), (10, 10), 2.5) is True


def test_in_range_two_cells_apart_within_25():
    assert in_range((10, 10), (12, 10), 2.5) is True


def test_in_range_three_cells_apart_outside_25():
    assert in_range((10, 10), (13, 10), 2.5) is False


def test_in_range_diagonal_within_upgraded_range():
    assert in_range((10, 10), (12, 12), 2.5) is False
    assert in_range((10, 10), (12, 12), 3.5) is True


# --- corner_factor ---------------------------------------------------------

@pytest.mark.parametrize("x,expected", [
    (0, 3.0), (1, 3.0), (2, 3.0), (3, 3.0),
    (24, 3.0), (25, 3.0), (26, 3.0), (27, 3.0),
    (4, 1.5), (5, 1.5), (6, 1.5), (7, 1.5), (8, 1.5), (9, 1.5),
    (18, 1.5), (19, 1.5), (20, 1.5), (21, 1.5), (22, 1.5), (23, 1.5),
    (10, 0.8), (11, 0.8), (12, 0.8), (13, 0.8),
    (14, 0.8), (15, 0.8), (16, 0.8), (17, 0.8),
])
def test_corner_factor_table(x, expected):
    assert corner_factor(x) == expected


# --- threat surface --------------------------------------------------------

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
        self._paths = paths

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))


def test_compute_threat_surface_counts_paths_on_our_side_only():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]]}
    paths = {
        ((0, 14), "BR"): [[0, 14], [1, 13], [2, 12], [3, 11]],
        ((27, 14), "BL"): [[27, 14], [26, 13], [25, 12]],
    }
    gs = _StubGameState(edges, paths)
    assert compute_threat_surface(gs) == {
        (1, 13): 1, (2, 12): 1, (3, 11): 1,
        (26, 13): 1, (25, 12): 1,
    }


def test_compute_threat_surface_skips_blocked():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]]}
    paths = {((0, 14), "BR"): None, ((27, 14), "BL"): [[27, 14], [26, 13]]}
    gs = _StubGameState(edges, paths)
    assert compute_threat_surface(gs) == {(26, 13): 1}


# --- score_placement -------------------------------------------------------

def test_score_placement_no_threat_in_range_returns_zero():
    threat = {(20, 13): 5}
    assert score_placement((5, 13), threat, 2.5) == 0.0


def test_score_placement_corner_factor_applies():
    # cell (1,13) corner=3.0, tile (1,13) in range, weight=4 → 3.0 * 4 = 12.0
    threat = {(1, 13): 4}
    assert score_placement((1, 13), threat, 2.5) == pytest.approx(12.0)


def test_score_placement_middle_penalty_applies():
    # cell (10,12) middle=0.8, tile (10,13) in range, weight=4 → 0.8 * 4 = 3.2
    threat = {(10, 13): 4}
    assert score_placement((10, 12), threat, 2.5) == pytest.approx(3.2)


def test_score_placement_sums_multiple_in_range_tiles():
    # (10,12) covers (10,13), (11,12), (10,11) — all distance ≤ 2.5
    threat = {(10, 13): 1, (11, 12): 1, (10, 11): 1}
    score = score_placement((10, 12), threat, 2.5)
    assert score == pytest.approx(0.8 * 3)


# --- score_upgrade ---------------------------------------------------------

def test_score_upgrade_in_raw_range():
    threat = {(10, 13): 1}
    assert score_upgrade((10, 12), threat, 2.5, 3.5) == pytest.approx(14.0)


def test_score_upgrade_in_annulus():
    threat = {(13, 13): 1}
    assert score_upgrade((10, 13), threat, 2.5, 3.5) == pytest.approx(20.0)


def test_score_upgrade_outside_upgraded_range_zero():
    threat = {(20, 13): 1}
    assert score_upgrade((5, 13), threat, 2.5, 3.5) == 0.0


# --- existing_turrets ------------------------------------------------------

class _Unit:
    def __init__(self, unit_type, upgraded=False):
        self.unit_type = unit_type
        self.upgraded = upgraded


class _StubGameStateUnits:
    def __init__(self, units):
        self._units = {tuple(k): v for k, v in units.items()}

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))


def test_existing_turrets_returns_only_unupgraded_turrets():
    units = {
        (2, 12): _Unit("TURRET", upgraded=False),
        (6, 13): _Unit("TURRET", upgraded=True),
        (13, 12): _Unit("SUPPORT"),
    }
    gs = _StubGameStateUnits(units)
    result = existing_turrets(gs, "TURRET")
    assert (2, 12) in result
    assert (6, 13) not in result
    assert (13, 12) not in result


# --- find_most_dangerous_enemy_path ----------------------------------------

class _UnitWithPI:
    def __init__(self, player_index, unit_type="WALL"):
        self.player_index = player_index
        self.unit_type = unit_type
        self.upgraded = False


class _DangerStub:
    def __init__(self, edges, paths, structures):
        self.game_map = _StubGameMap(edges)
        self._paths = paths
        self._units = {tuple(k): v for k, v in structures.items()}

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))


def test_damage_along_path_counts_structures_in_range():
    path = [[5, 13], [5, 12], [5, 11]]
    assert _damage_along_path(path, [(6, 12)], 3.5) == 3


def test_find_most_dangerous_picks_path_with_most_structures():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]]}
    path1 = [[0, 14], [1, 13], [1, 12]]
    path2 = [[27, 14], [26, 13], [25, 12]]
    paths = {((0, 14), "BR"): path1, ((27, 14), "BL"): path2}
    structures = {
        (25, 13): _UnitWithPI(0),
        (24, 12): _UnitWithPI(0),
    }
    stub = _DangerStub(edges, paths, structures)
    worst_path, _ = find_most_dangerous_enemy_path(stub)
    assert worst_path == path2


def test_weakness_boost_factor_value():
    assert WEAKNESS_BOOST_FACTOR == 3


# --- place_turrets orchestrator -------------------------------------------

class _OrchestratorStub:
    TURRET_COST = 3
    UPGRADE_COST = 8

    def __init__(self, sp, edges, paths, units):
        self._sp = sp
        self._units = {tuple(k): v for k, v in units.items()}
        self.spawn_calls = []
        self.upgrade_calls = []
        self.game_map = _StubGameMap(edges)
        self._paths = paths

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))

    def get_resource(self, _resource_type, _player=0):
        return self._sp

    def type_cost(self, unit_type, upgrade=False):
        assert unit_type == "TURRET"
        if upgrade:
            return [self.UPGRADE_COST, 0]
        return [self.TURRET_COST, 0]

    def attempt_spawn(self, _unit_type, loc, _count=1):
        loc = tuple(loc)
        if self._sp < self.TURRET_COST:
            return 0
        self._sp -= self.TURRET_COST
        self.spawn_calls.append(loc)
        self._units[loc] = _UnitWithPI(0, "TURRET")
        return 1

    def attempt_upgrade(self, loc):
        loc = tuple(loc)
        if self._sp < self.UPGRADE_COST or loc not in self._units:
            return 0
        self._sp -= self.UPGRADE_COST
        self.upgrade_calls.append(loc)
        self._units[loc].upgraded = True
        return 1


def _stub_with_path():
    edges = {"TL": [], "TR": [[14, 27]], "BL": [], "BR": []}
    path = [[14, 27 - i] for i in range(28)]
    paths = {((14, 27), "BL"): path}
    return edges, paths


def test_place_turrets_only_picks_from_pool():
    edges, paths = _stub_with_path()
    stub = _OrchestratorStub(sp=12, edges=edges, paths=paths, units={})
    pool = [(13, 12), (14, 12), (10, 13)]
    result = place_turrets(stub, "TURRET", candidate_pool=pool)
    for loc in result["placed"]:
        assert loc in pool


def test_place_turrets_skips_occupied_pool_cells():
    edges, paths = _stub_with_path()
    units = {(13, 12): _UnitWithPI(0, "TURRET")}
    stub = _OrchestratorStub(sp=12, edges=edges, paths=paths, units=units)
    pool = [(13, 12), (14, 12)]
    result = place_turrets(stub, "TURRET", candidate_pool=pool)
    assert (13, 12) not in result["placed"]


def test_place_turrets_returns_no_threat_when_no_paths():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]], "BL": [], "BR": []}
    paths = {((0, 14), "BR"): None, ((27, 14), "BL"): None}
    stub = _OrchestratorStub(sp=10, edges=edges, paths=paths, units={})
    result = place_turrets(stub, "TURRET", candidate_pool=[(10, 13)])
    assert result["stopped_reason"] == "no_threat"
    assert result["placed"] == []


def test_place_turrets_strict_priority_no_upgrade_until_placement_exhausted():
    edges, paths = _stub_with_path()
    units = {(14, 12): _UnitWithPI(0, "TURRET")}
    stub = _OrchestratorStub(sp=3, edges=edges, paths=paths, units=units)
    place_turrets(stub, "TURRET", candidate_pool=[(13, 12)])
    assert len(stub.spawn_calls) == 1
    assert len(stub.upgrade_calls) == 0


def test_place_turrets_upgrade_phase_runs_after_placement_exhausted():
    edges, paths = _stub_with_path()
    units = {(14, 12): _UnitWithPI(0, "TURRET")}
    stub = _OrchestratorStub(sp=100, edges=edges, paths=paths, units=units)
    pool = [(13, 12)]
    result = place_turrets(stub, "TURRET", candidate_pool=pool)
    assert len(stub.upgrade_calls) >= 1
