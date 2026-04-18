"""Greedy turret placer for python-2l-c.

See docs/superpowers/specs/2026-04-18-greedy-turret-placer-design.md.
"""

import math

_DEPTH_FACTORS = {
    13: 0.90,
    12: 0.95,
    11: 0.95,
    10: 0.95,
    9: 0.70,
    8: 0.60,
}

UPPER_HALF_Y_RANGE = (8, 13)  # inclusive on both ends


def depth_factor(y):
    if y not in _DEPTH_FACTORS:
        raise ValueError(f"y={y} outside upper-half range {UPPER_HALF_Y_RANGE}")
    return _DEPTH_FACTORS[y]


def in_range(turret_loc, target_loc, attack_range):
    """Cell-center Euclidean range check, matching engine attackRange semantics."""
    tx, ty = turret_loc
    px, py = target_loc
    return math.dist((tx + 0.5, ty + 0.5), (px + 0.5, py + 0.5)) <= attack_range


SCORING_MODES = ("gap_fill", "stacking", "path_freq")


def tile_weight(tile, coverage, threat_count, mode):
    """Return a per-tile weight in [0, 1] under the chosen scoring mode."""
    if mode == "gap_fill":
        return 1.0 if coverage.get(tile, 0) == 0 else 0.2
    if mode == "stacking":
        return 1.0
    if mode == "path_freq":
        if not threat_count:
            return 0.0
        peak = max(threat_count.values())
        if peak == 0:
            return 0.0
        return threat_count.get(tile, 0) / peak
    raise ValueError(f"unknown scoring mode: {mode!r}")


def score_placement(cell, threat_count, coverage, attack_range, mode):
    """Score for placing a fresh turret at `cell`.

    Sums tile_weight × depth_factor over all threat tiles in range.
    """
    cx, cy = cell
    df = depth_factor(cy)
    total = 0.0
    for tile in threat_count:
        if in_range(cell, tile, attack_range):
            total += tile_weight(tile, coverage, threat_count, mode)
    return df * total


RAW_TURRET_DAMAGE = 6
UPGRADED_TURRET_DAMAGE = 20


def score_upgrade(turret_loc, threat_count, coverage, raw_range, upgraded_range, mode):
    """Damage gain from upgrading the turret at `turret_loc`.

    Two contributions, summed:
      - tiles already in raw range: (upgraded_dmg - raw_dmg) * weight
      - tiles in the annulus (raw_range < d <= upgraded_range): upgraded_dmg * weight

    No depth_factor — the turret already sits where it sits.
    """
    raw_gain_factor = UPGRADED_TURRET_DAMAGE - RAW_TURRET_DAMAGE
    annulus_gain_factor = UPGRADED_TURRET_DAMAGE
    total = 0.0
    for tile in threat_count:
        w = tile_weight(tile, coverage, threat_count, mode)
        if w == 0:
            continue
        if in_range(turret_loc, tile, raw_range):
            total += raw_gain_factor * w
        elif in_range(turret_loc, tile, upgraded_range):
            total += annulus_gain_factor * w
    return total


def compute_threat_surface(game_state):
    """Build a path-frequency map of cells on our side that enemy walkers may cross.

    Iterates every cell on the enemy edges (TOP_LEFT + TOP_RIGHT). Each
    successful path contributes +1 to threat_count[(x, y)] for every cell
    on the path with y <= 13.
    """
    gm = game_state.game_map
    threat_count = {}
    edge_targets = [
        (gm.TOP_LEFT, gm.BOTTOM_RIGHT),
        (gm.TOP_RIGHT, gm.BOTTOM_LEFT),
    ]
    for start_edge, target_edge in edge_targets:
        for start in gm.get_edge_locations(start_edge):
            path = game_state.find_path_to_edge(start, target_edge)
            if not path:
                continue
            for cell in path:
                x, y = cell[0], cell[1]
                if y <= 13:
                    key = (x, y)
                    threat_count[key] = threat_count.get(key, 0) + 1
    return threat_count


ARENA_SIZE = 28
HALF_ARENA = 14


def _enumerate_friendly_diamond():
    """Generator over every (x, y) inside the friendly half-diamond, y in [0, 13]."""
    for x in range(ARENA_SIZE):
        if x < HALF_ARENA:
            for y in range(HALF_ARENA - x - 1, HALF_ARENA):
                yield (x, y)
        else:
            for y in range(x - HALF_ARENA, HALF_ARENA):
                yield (x, y)


def candidate_cells(game_state):
    """Empty cells inside the upper half of the friendly diamond, y in [8, 13]."""
    y_lo, y_hi = UPPER_HALF_Y_RANGE
    out = []
    for cell in _enumerate_friendly_diamond():
        x, y = cell
        if y < y_lo or y > y_hi:
            continue
        if game_state.contains_stationary_unit(list(cell)):
            continue
        out.append(cell)
    return out
