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

_STRONG_CORNER_XS = frozenset({0, 1, 2, 3, 24, 25, 26, 27})
_MID_FLANK_XS = frozenset({4, 5, 6, 21, 22, 23})
STRONG_CORNER_BOOST = 1.5
MID_FLANK_BOOST = 1.2
TENDENCY_MAX_MULTIPLIER = 0.5  # at |tendency|=1, favored side is × (1 + 0.5) = 1.5


def depth_factor(y):
    if y not in _DEPTH_FACTORS:
        raise ValueError(f"y={y} outside upper-half range {UPPER_HALF_Y_RANGE}")
    return _DEPTH_FACTORS[y]


def corner_factor(x):
    """Horizontal-position boost: stronger at outer columns, tapering inward."""
    if x in _STRONG_CORNER_XS:
        return STRONG_CORNER_BOOST
    if x in _MID_FLANK_XS:
        return MID_FLANK_BOOST
    return 1.0


def tendency_factor(x, tendency):
    """Boost candidates on the side the enemy attacks more.

    tendency ∈ [-1, 1]; positive = enemy spawns more from LEFT (x<14).
    Only boosts the favored side — unfavored stays at 1.0.
    """
    if tendency == 0:
        return 1.0
    is_left = x < 14
    if tendency > 0 and is_left:
        return 1.0 + TENDENCY_MAX_MULTIPLIER * tendency
    if tendency < 0 and not is_left:
        return 1.0 + TENDENCY_MAX_MULTIPLIER * (-tendency)
    return 1.0


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


def score_placement(cell, threat_count, coverage, attack_range, mode, tendency=0.0):
    """Score for placing a fresh turret at `cell`.

    Sums tile_weight over threat tiles in range, multiplied by:
      depth_factor(y) × corner_factor(x) × tendency_factor(x, tendency)
    """
    cx, cy = cell
    df = depth_factor(cy)
    cf = corner_factor(cx)
    tf = tendency_factor(cx, tendency)
    total = 0.0
    for tile in threat_count:
        if in_range(cell, tile, attack_range):
            total += tile_weight(tile, coverage, threat_count, mode)
    return df * cf * tf * total


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


def existing_turrets(game_state, turret_shorthand):
    """Return upper-half cells where a non-upgraded turret currently sits."""
    out = []
    y_lo, y_hi = UPPER_HALF_Y_RANGE
    for cell in _enumerate_friendly_diamond():
        x, y = cell
        if y < y_lo or y > y_hi:
            continue
        unit = game_state.contains_stationary_unit(list(cell))
        if not unit:
            continue
        if unit.unit_type != turret_shorthand:
            continue
        if getattr(unit, "upgraded", False):
            continue
        out.append(cell)
    return out


def init_coverage(threat_count, turret_locs, raw_range):
    """Build coverage map: how many turrets currently cover each threat tile."""
    cov = {tile: 0 for tile in threat_count}
    for tile in cov:
        for t in turret_locs:
            if in_range(t, tile, raw_range):
                cov[tile] += 1
    return cov


SP_RESOURCE_INDEX = 0  # game_state.get_resource(SP_RESOURCE_INDEX) returns SP


def place_turrets(
    game_state,
    anchor_locations,
    turret_shorthand,
    scoring="path_freq",
    raw_range=2.5,
    upgraded_range=3.5,
    min_placement_score=0.0,
    attack_tendency=0.0,
):
    """Greedy turret placer + upgrade-fallback. See spec for full design.

    attack_tendency ∈ [-1, 1]: positive = enemy favors LEFT flank; feeds
    tendency_factor inside score_placement.
    """
    placed = []
    upgraded = []

    threat = compute_threat_surface(game_state)
    if not threat:
        return {"placed": placed, "upgraded": upgraded, "stopped_reason": "no_threat"}

    candidates = candidate_cells(game_state)
    coverage = init_coverage(threat, list(anchor_locations), raw_range)

    # --- Phase 3: Greedy placement ---
    turret_cost = game_state.type_cost(turret_shorthand)[SP_RESOURCE_INDEX]
    stopped = "budget_exhausted"
    while game_state.get_resource(SP_RESOURCE_INDEX) >= turret_cost and candidates:
        best, best_score = None, min_placement_score
        for c in candidates:
            s = score_placement(c, threat, coverage, raw_range, scoring, attack_tendency)
            if s > best_score:
                best, best_score = c, s
        if best is None:
            stopped = "no_positive_score"
            break
        sent = game_state.attempt_spawn(turret_shorthand, list(best))
        if sent <= 0:
            candidates.remove(best)
            continue
        placed.append(best)
        candidates.remove(best)
        for tile in threat:
            if in_range(best, tile, raw_range):
                coverage[tile] = coverage.get(tile, 0) + 1

    # --- Phase 4: Upgrade fallback ---
    upgrade_cost = game_state.type_cost(turret_shorthand, upgrade=True)[SP_RESOURCE_INDEX]
    upgrade_pool = list(anchor_locations) + placed
    # Re-fetch existing turrets in case anchors weren't passed and we want to upgrade
    # whatever turrets are present in the upper half (defensive).
    for t in existing_turrets(game_state, turret_shorthand):
        if t not in upgrade_pool:
            upgrade_pool.append(t)

    while game_state.get_resource(SP_RESOURCE_INDEX) >= upgrade_cost and upgrade_pool:
        best, best_score = None, 0.0
        for t in upgrade_pool:
            s = score_upgrade(t, threat, coverage, raw_range, upgraded_range, scoring)
            if s > best_score:
                best, best_score = t, s
        if best is None:
            break
        sent = game_state.attempt_upgrade(list(best))
        if sent <= 0:
            upgrade_pool.remove(best)
            continue
        upgraded.append(best)
        upgrade_pool.remove(best)
        # Update coverage for the newly-covered annulus tiles (upgrades extend range).
        for tile in threat:
            if in_range(best, tile, upgraded_range) and not in_range(best, tile, raw_range):
                coverage[tile] = coverage.get(tile, 0) + 1

    return {"placed": placed, "upgraded": upgraded, "stopped_reason": stopped}
