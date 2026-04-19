"""python-2l-g — maximally hardcoded symmetric-balance algo.

Philosophy:
  - No path simulation anywhere.
  - Defense: hardcoded structure list; for each (left, right) turret pair
    build the WEAKER of our two halves first to maintain parity.
  - Attack: count enemy turrets per half; spawn all scouts on the edge
    that routes them through the WEAKER enemy half.
"""
import gamelib
import random
from sys import maxsize


# --- Hardcoded position lists --------------------------------------------

# Corner walls — built first as cheap corner cover.
CORNER_WALLS = [(0, 13), (27, 13)]

# Supports — center only, built + upgraded in this order.
SUPPORT_POSITIONS = [
    (13, 12), (14, 12),
    (13, 11), (14, 11),
    (13, 10), (14, 10),
]

# Turret (left, right) pairs in priority order. For each pair: build the
# weaker side first, then the other.
TURRET_PAIRS = [
    # Frontline anchors (y=13 outer band)
    ((2, 13),  (25, 13)),
    ((1, 13),  (26, 13)),
    ((4, 13),  (23, 13)),
    ((5, 13),  (22, 13)),
    # Center top (y=13)
    ((13, 13), (14, 13)),
    ((11, 13), (16, 13)),
    ((10, 13), (17, 13)),
    ((7, 13),  (20, 13)),
    ((8, 13),  (19, 13)),
    # y=12
    ((12, 12), (15, 12)),
    ((5, 12),  (22, 12)),
    ((7, 12),  (20, 12)),
    ((10, 12), (17, 12)),
    ((8, 12),  (19, 12)),
    ((4, 12),  (23, 12)),
    # y=11
    ((11, 11), (16, 11)),
    ((8, 11),  (19, 11)),
    ((5, 11),  (22, 11)),
    ((4, 11),  (23, 11)),
    ((7, 11),  (20, 11)),
    # y=10
    ((8, 10),  (19, 10)),
    ((5, 10),  (22, 10)),
    ((9, 10),  (18, 10)),
    ((6, 10),  (21, 10)),
]

REFUND_THRESHOLD_WALL = 0.5
REFUND_THRESHOLD_TURRET = 0.2


class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

    def on_game_start(self, config):
        self.config = config
        global WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP
        WALL = config["unitInformation"][0]["shorthand"]
        SUPPORT = config["unitInformation"][1]["shorthand"]
        TURRET = config["unitInformation"][2]["shorthand"]
        SCOUT = config["unitInformation"][3]["shorthand"]
        DEMOLISHER = config["unitInformation"][4]["shorthand"]
        INTERCEPTOR = config["unitInformation"][5]["shorthand"]
        MP = 1
        SP = 0

    def on_turn(self, turn_state):
        game_state = gamelib.GameState(self.config, turn_state)
        try:
            self._refund_low_hp(game_state)
            self._build_corner_walls(game_state)
            self._build_and_upgrade_supports(game_state)
            self._build_turret_pairs(game_state)
            self._upgrade_turret_pairs(game_state)
            self._spawn_scouts(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception in strategy: {e}")
        game_state.submit_turn()

    # --- Defense ----------------------------------------------------------

    def _iter_our_diamond_cells(self):
        for x in range(28):
            y_lo = 13 - x if x < 14 else x - 14
            for y in range(y_lo, 14):
                yield (x, y)

    def _refund_low_hp(self, game_state):
        for (x, y) in self._iter_our_diamond_cells():
            unit = game_state.contains_stationary_unit([x, y])
            if not unit:
                continue
            if unit.unit_type == TURRET and unit.health / unit.max_health < REFUND_THRESHOLD_TURRET:
                game_state.attempt_remove([x, y])
            elif unit.unit_type == WALL and unit.health / unit.max_health < REFUND_THRESHOLD_WALL:
                game_state.attempt_remove([x, y])

    def _build_corner_walls(self, game_state):
        for (x, y) in CORNER_WALLS:
            if game_state.contains_stationary_unit([x, y]):
                continue
            if game_state.get_resource(SP) < game_state.type_cost(WALL)[0]:
                return
            game_state.attempt_spawn(WALL, [x, y])

    def _build_and_upgrade_supports(self, game_state):
        for (x, y) in SUPPORT_POSITIONS:
            if game_state.contains_stationary_unit([x, y]):
                continue
            if game_state.get_resource(SP) < game_state.type_cost(SUPPORT)[0]:
                return
            game_state.attempt_spawn(SUPPORT, [x, y])
        for (x, y) in SUPPORT_POSITIONS:
            unit = game_state.contains_stationary_unit([x, y])
            if not unit or unit.unit_type != SUPPORT or getattr(unit, "upgraded", False):
                continue
            if game_state.get_resource(SP) < game_state.type_cost(SUPPORT, upgrade=True)[0]:
                return
            game_state.attempt_upgrade([x, y])

    def _our_side_strength(self, game_state, side):
        """Count our turrets on the given side (upgraded = 2×)."""
        count = 0
        x_range = range(0, 14) if side == "L" else range(14, 28)
        for x in x_range:
            y_lo = 13 - x if x < 14 else x - 14
            for y in range(y_lo, 14):
                unit = game_state.contains_stationary_unit([x, y])
                if unit and unit.player_index == 0 and unit.unit_type == TURRET:
                    count += 2 if getattr(unit, "upgraded", False) else 1
        return count

    def _pair_order_by_weakness(self, game_state, lpos, rpos):
        our_l = self._our_side_strength(game_state, "L")
        our_r = self._our_side_strength(game_state, "R")
        if our_l <= our_r:
            return (lpos, rpos)
        return (rpos, lpos)

    def _build_turret_pairs(self, game_state):
        for (lpos, rpos) in TURRET_PAIRS:
            for (x, y) in self._pair_order_by_weakness(game_state, lpos, rpos):
                if game_state.contains_stationary_unit([x, y]):
                    continue
                if game_state.get_resource(SP) < game_state.type_cost(TURRET)[0]:
                    return
                game_state.attempt_spawn(TURRET, [x, y])

    def _upgrade_turret_pairs(self, game_state):
        for (lpos, rpos) in TURRET_PAIRS:
            for (x, y) in self._pair_order_by_weakness(game_state, lpos, rpos):
                unit = game_state.contains_stationary_unit([x, y])
                if not unit or unit.unit_type != TURRET or getattr(unit, "upgraded", False):
                    continue
                if game_state.get_resource(SP) < game_state.type_cost(TURRET, upgrade=True)[0]:
                    return
                game_state.attempt_upgrade([x, y])

    # --- Attack -----------------------------------------------------------

    def _enemy_side_strength(self, game_state, side):
        """Count enemy turrets on the given side (upgraded = 2×)."""
        count = 0
        x_range = range(0, 14) if side == "L" else range(14, 28)
        for x in x_range:
            y_max = x + 14 if x < 14 else 41 - x
            for y in range(14, y_max + 1):
                unit = game_state.contains_stationary_unit([x, y])
                if unit and unit.player_index == 1 and unit.unit_type == TURRET:
                    count += 2 if getattr(unit, "upgraded", False) else 1
        return count

    def _spawn_scouts(self, game_state):
        """All-in scout rush on the edge targeting enemy's weaker half.

        Spawning on BOTTOM_LEFT → walker targets TOP_RIGHT → traverses
        enemy's RIGHT side. So:
          attack enemy LEFT  → spawn on BOTTOM_RIGHT (e.g. [14, 0])
          attack enemy RIGHT → spawn on BOTTOM_LEFT  (e.g. [13, 0])
        """
        mp = int(game_state.get_resource(MP))
        if mp < 5:
            return
        el = self._enemy_side_strength(game_state, "L")
        er = self._enemy_side_strength(game_state, "R")
        if el <= er:
            spawn = self._pick_edge_cell(game_state, "BR")
        else:
            spawn = self._pick_edge_cell(game_state, "BL")
        if spawn is None:
            gamelib.debug_write("No unblocked spawn cell — saving MP.")
            return
        game_state.attempt_spawn(SCOUT, spawn, 1000)
        gamelib.debug_write(f"Scout rush: {mp} scouts at {spawn} (enemy L={el} R={er})")

    def _pick_edge_cell(self, game_state, corner):
        gm = game_state.game_map
        target = gm.BOTTOM_LEFT if corner == "BL" else gm.BOTTOM_RIGHT
        for cell in gm.get_edge_locations(target):
            if not game_state.contains_stationary_unit(cell):
                return cell
        return None


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
