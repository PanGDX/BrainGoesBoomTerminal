"""Curated-pool turret placer for python-2l-d.

Simplified scoring: greedy over curated positions, scored by
    corner_factor(x) * sum(threat_count[tile] for tile in range(cell))
where threat_count is multiplied by WEAKNESS_BOOST_FACTOR for cells on the
most-damaging enemy path.

No depth_factor, no tendency, no parity override, no scoring modes.
"""

import math


# --- Horizontal-position weighting -----------------------------------------

_STRONG_CORNER_XS = frozenset({0, 1, 2, 3, 24, 25, 26, 27})
_QUARTER_ZONE_XS = frozenset({4, 5, 6, 7, 8, 9, 18, 19, 20, 21, 22, 23})
_MIDDLE_XS = frozenset({10, 11, 12, 13, 14, 15, 16, 17})
STRONG_CORNER_BOOST = 1.5
QUARTER_ZONE_BOOST = 1.5
MIDDLE_PENALTY = 0.8


def corner_factor(x):
    """U-shape: corners + quarter zones boosted, middle penalized."""
    if x in _STRONG_CORNER_XS:
        return STRONG_CORNER_BOOST
    if x in _QUARTER_ZONE_XS:
        return QUARTER_ZONE_BOOST
    if x in _MIDDLE_XS:
        return MIDDLE_PENALTY
    return 1.0


# --- Range check -----------------------------------------------------------

def in_range(turret_loc, target_loc, attack_range):
    """Cell-center Euclidean range check, matching engine attackRange semantics."""
    tx, ty = turret_loc
    px, py = target_loc
    return math.dist((tx + 0.5, ty + 0.5), (px + 0.5, py + 0.5)) <= attack_range


# --- Threat surface --------------------------------------------------------

def compute_threat_surface(game_state):
    """Path-frequency map of cells on our side that enemy walkers may cross."""
    gm = game_state.game_map
    threat_count = {}
    for start_edge, target_edge in [(gm.TOP_LEFT, gm.BOTTOM_RIGHT),
                                     (gm.TOP_RIGHT, gm.BOTTOM_LEFT)]:
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


# --- Weakness boost --------------------------------------------------------

WEAKNESS_BOOST_FACTOR = 3
SCOUT_ATTACK_RANGE_FOR_DAMAGE_SIM = 3.5


def _enumerate_friendly_diamond():
    for x in range(28):
        if x < 14:
            for y in range(14 - x - 1, 14):
                yield (x, y)
        else:
            for y in range(x - 14, 14):
                yield (x, y)


def _collect_our_structures(game_state):
    out = []
    for cell in _enumerate_friendly_diamond():
        unit = game_state.contains_stationary_unit(list(cell))
        if unit and getattr(unit, "player_index", 0) == 0:
            out.append(cell)
    return out


def _damage_along_path(path, our_structures, walker_range):
    total = 0
    for cell in path:
        cx, cy = cell[0], cell[1]
        for sx, sy in our_structures:
            if math.dist((cx + 0.5, cy + 0.5), (sx + 0.5, sy + 0.5)) <= walker_range:
                total += 1
    return total


def find_most_dangerous_enemy_path(game_state, walker_range=SCOUT_ATTACK_RANGE_FOR_DAMAGE_SIM):
    """Find the enemy-spawn path that would inflict the most damage on our structures."""
    gm = game_state.game_map
    our_structures = _collect_our_structures(game_state)
    worst_path, worst_damage = None, -1
    for start_edge, target_edge in [(gm.TOP_LEFT, gm.BOTTOM_RIGHT),
                                     (gm.TOP_RIGHT, gm.BOTTOM_LEFT)]:
        for start in gm.get_edge_locations(start_edge):
            path = game_state.find_path_to_edge(start, target_edge)
            if not path:
                continue
            damage = _damage_along_path(path, our_structures, walker_range)
            if damage > worst_damage:
                worst_damage = damage
                worst_path = path
    return worst_path, worst_damage


# --- Scoring ---------------------------------------------------------------

def score_placement(cell, threat_count, attack_range):
    """Score = corner_factor(x) * sum of threat_count over tiles in range."""
    cx, _ = cell
    cf = corner_factor(cx)
    total = 0.0
    for tile, weight in threat_count.items():
        if in_range(cell, tile, attack_range):
            total += weight
    return cf * total


# --- Existing turrets (for upgrade fallback) -------------------------------

def existing_turrets(game_state, turret_shorthand):
    """Return cells where a non-upgraded turret currently sits, in upper half."""
    out = []
    for cell in _enumerate_friendly_diamond():
        x, y = cell
        if y < 8 or y > 13:
            continue
        unit = game_state.contains_stationary_unit(list(cell))
        if not unit or unit.unit_type != turret_shorthand:
            continue
        if getattr(unit, "upgraded", False):
            continue
        out.append(cell)
    return out


# --- Upgrade scoring -------------------------------------------------------

RAW_TURRET_DAMAGE = 6
UPGRADED_TURRET_DAMAGE = 20


def score_upgrade(turret_loc, threat_count, raw_range, upgraded_range):
    """Damage gain from upgrading a turret. No coverage discount, no depth bias."""
    raw_gain = UPGRADED_TURRET_DAMAGE - RAW_TURRET_DAMAGE
    annulus_gain = UPGRADED_TURRET_DAMAGE
    total = 0.0
    for tile, weight in threat_count.items():
        if in_range(turret_loc, tile, raw_range):
            total += raw_gain * weight
        elif in_range(turret_loc, tile, upgraded_range):
            total += annulus_gain * weight
    return total


# --- Orchestrator ----------------------------------------------------------

SP_RESOURCE_INDEX = 0


def place_turrets(
    game_state,
    turret_shorthand,
    candidate_pool,
    raw_range=2.5,
    upgraded_range=3.5,
    min_placement_score=0.0,
):
    """Greedy turret placer over a curated pool + upgrade fallback.

    Per iteration: score each candidate as corner_factor(x) * sum(threat_count
    for tiles in range), pick highest, attempt spawn. Repeat until SP < cost
    or no positive score.

    candidate_pool: required list of (x, y) tuples — the only allowed positions.
    """
    placed = []
    upgraded = []

    threat = compute_threat_surface(game_state)
    if not threat:
        return {"placed": placed, "upgraded": upgraded, "stopped_reason": "no_threat"}

    # Boost threat priority along the most-damaging enemy path.
    dangerous_path, _ = find_most_dangerous_enemy_path(game_state)
    if dangerous_path:
        for cell in dangerous_path:
            x, y = cell[0], cell[1]
            if y <= 13 and (x, y) in threat:
                threat[(x, y)] = threat[(x, y)] * WEAKNESS_BOOST_FACTOR

    candidates = [
        (x, y) for (x, y) in candidate_pool
        if not game_state.contains_stationary_unit([x, y])
    ]

    # --- Greedy placement ---
    turret_cost = game_state.type_cost(turret_shorthand)[SP_RESOURCE_INDEX]
    stopped = "budget_exhausted"
    while game_state.get_resource(SP_RESOURCE_INDEX) >= turret_cost and candidates:
        best, best_score = None, min_placement_score
        for c in candidates:
            s = score_placement(c, threat, raw_range)
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

    # --- Upgrade fallback ---
    upgrade_cost = game_state.type_cost(turret_shorthand, upgrade=True)[SP_RESOURCE_INDEX]
    upgrade_pool = list(placed)
    for t in existing_turrets(game_state, turret_shorthand):
        if t not in upgrade_pool:
            upgrade_pool.append(t)
    while game_state.get_resource(SP_RESOURCE_INDEX) >= upgrade_cost and upgrade_pool:
        best, best_score = None, 0.0
        for t in upgrade_pool:
            s = score_upgrade(t, threat, raw_range, upgraded_range)
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

    return {"placed": placed, "upgraded": upgraded, "stopped_reason": stopped}
