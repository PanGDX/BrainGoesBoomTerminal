import gamelib
import random
import math
from sys import maxsize
import json
import os


# Aggressive-attack: enemy lost ≥60% supports last turn → all-in at best path.
AGGRESSIVE_ATTACK_LOSS_RATIO = 0.60
AGGRESSIVE_ATTACK_MIN_PRIOR = 3

# Alt-attack fallback: N consecutive scout rushes with zero breaches → flip side + SD.
ALT_ATTACK_THRESHOLD = 5

# Hard-kill threshold: enemy HP ≤ this → pick max-breach path.
HARD_KILL_HP = 12


class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

        # Cumulative enemy scout spawn counts — drives path-sorted build order.
        self.enemy_scout_spawns = {}

        # Support-loss trigger state.
        self.aggressive_attack = False
        self.last_enemy_support_count = 0

        # Alt-attack fallback state.
        self.last_attack_side = None               # "BL" or "BR"
        self.consecutive_zero_breach_attacks = 0
        self.force_alternate_attack = False
        self._pending_our_breaches = 0
        self._launched_attack_last_turn = False

    def on_game_start(self, config):
        gamelib.debug_write('Configuring your custom algo strategy...')
        self.config = config
        global WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP
        global REFUND_THRESHOLD_WALL, REFUND_THRESHOLD_TURRET
        WALL = config["unitInformation"][0]["shorthand"]
        SUPPORT = config["unitInformation"][1]["shorthand"]
        TURRET = config["unitInformation"][2]["shorthand"]
        SCOUT = config["unitInformation"][3]["shorthand"]
        DEMOLISHER = config["unitInformation"][4]["shorthand"]
        INTERCEPTOR = config["unitInformation"][5]["shorthand"]
        MP = 1
        SP = 0

        REFUND_THRESHOLD_WALL = 0.5
        REFUND_THRESHOLD_TURRET = 0.2

        with open(os.path.join(os.path.dirname(__file__), 'build-order.json'), 'r') as f:
            self.build_order = json.loads(f.read())

        self.min_sp_to_save = 0

    def on_action_frame(self, turn_string):
        state = json.loads(turn_string)
        events = state.get("events", {})
        # Read enemy scout spawns once at the start of action phase.
        if state["turnInfo"][0] == 1 and state["turnInfo"][2] == 0:
            for spawn in events.get("spawn", []):
                loc, unit_type = spawn[0], spawn[1]
                if unit_type == 3 and loc[1] >= 14:
                    key = f"{loc[0]}:{loc[1]}"
                    self.enemy_scout_spawns[key] = self.enemy_scout_spawns.get(key, 0) + 1
        # Count OUR breach events (player==1 = our walker reached enemy edge).
        for breach in events.get("breach", []):
            if len(breach) >= 5 and breach[4] == 1:
                self._pending_our_breaches += 1

    def on_turn(self, turn_state):
        game_state = gamelib.GameState(self.config, turn_state)

        # Update alt-attack counter from last turn's result.
        if self._launched_attack_last_turn:
            if self._pending_our_breaches == 0:
                self.consecutive_zero_breach_attacks += 1
            else:
                self.consecutive_zero_breach_attacks = 0
        self._pending_our_breaches = 0
        self._launched_attack_last_turn = False
        if self.consecutive_zero_breach_attacks >= ALT_ATTACK_THRESHOLD:
            self.force_alternate_attack = True
            gamelib.debug_write(
                f"ALT-ATTACK trigger: {self.consecutive_zero_breach_attacks} "
                f"consecutive zero-breach rushes from {self.last_attack_side}"
            )

        try:
            self._update_aggressive_attack_trigger(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception in aggressive-attack trigger: {e}")

        try:
            self.build_defences(game_state)
            self.execute_scout_rush(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception in strategy: {e}")

        game_state.submit_turn()

    def _count_enemy_supports(self, game_state):
        count = 0
        for x in range(28):
            y_max = x + 14 if x < 14 else 41 - x
            for y in range(14, y_max + 1):
                unit = game_state.contains_stationary_unit([x, y])
                if unit and unit.player_index == 1 and unit.unit_type == SUPPORT:
                    count += 1
        return count

    def _update_aggressive_attack_trigger(self, game_state):
        current = self._count_enemy_supports(game_state)
        if (self.last_enemy_support_count >= AGGRESSIVE_ATTACK_MIN_PRIOR
                and current < self.last_enemy_support_count):
            loss = (self.last_enemy_support_count - current) / self.last_enemy_support_count
            if loss >= AGGRESSIVE_ATTACK_LOSS_RATIO:
                self.aggressive_attack = True
                gamelib.debug_write(
                    f"AGGRESSIVE-ATTACK trigger: enemy supports "
                    f"{self.last_enemy_support_count}→{current} (loss={loss:.0%})"
                )
        self.last_enemy_support_count = current

    # --- Defense -------------------------------------------------------------

    def build_defences(self, game_state):
        self.refund_low_health_structures(game_state)
        self.build_default_defences(game_state)
        self._build_random_turrets_fallback(game_state)

    def _friendly_diamond_cells(self, game_state):
        out = []
        for x in range(game_state.ARENA_SIZE):
            if x < game_state.HALF_ARENA:
                for y in range(game_state.HALF_ARENA - x - 1, game_state.HALF_ARENA):
                    out.append([x, y])
            else:
                for y in range(x - 14, game_state.HALF_ARENA):
                    out.append([x, y])
        return out

    def refund_low_health_structures(self, game_state):
        for location in self._friendly_diamond_cells(game_state):
            structure = game_state.contains_stationary_unit(location)
            if not structure:
                continue
            if structure.unit_type == TURRET:
                if structure.health / structure.max_health < REFUND_THRESHOLD_TURRET:
                    game_state.attempt_remove(location)
            elif structure.unit_type == WALL:
                if structure.health / structure.max_health < REFUND_THRESHOLD_WALL:
                    game_state.attempt_remove(location)

    def build_default_defences(self, game_state):
        """Walk tier order; sort each tier's jobs by distance to the most
        frequently-used enemy attack paths. Stops when SP dips below reserve."""
        # Precompute vulnerable path points once per turn (shared across tiers).
        vulnerable_path_points = []
        for loc_str, count in self.enemy_scout_spawns.items():
            if count >= 2:
                x_str, y_str = loc_str.split(":")
                path = game_state.find_path_to_edge([int(x_str), int(y_str)])
                if path:
                    vulnerable_path_points.extend(path)

        def min_dist_to_vuln_path(job):
            jx, jy = job["location"]
            return min(math.hypot(jx - p[0], jy - p[1]) for p in vulnerable_path_points)

        for priority in ("start", "extra_supports", "sides", "frontline",
                         "catchline", "supportstructure", "turret_upgrades"):
            job_list = self.build_order.get(priority, [])
            if vulnerable_path_points:
                job_list = sorted(job_list, key=min_dist_to_vuln_path)
            for build_job in job_list:
                unit = eval(build_job["unit"])
                location = build_job["location"]
                if game_state.get_resource(SP) - game_state.type_cost(unit)[0] < self.min_sp_to_save:
                    return
                if build_job["type"] == "spawn":
                    game_state.attempt_spawn(unit, location)
                elif build_job["type"] == "upgrade":
                    game_state.attempt_upgrade(location)

    def _build_random_turrets_fallback(self, game_state):
        """Spend leftover SP on random upper-half unoccupied cells."""
        turret_cost = game_state.type_cost(TURRET)[0]
        empty_set = {
            tuple(c) for c in self._friendly_diamond_cells(game_state)
            if 8 <= c[1] <= 13 and not game_state.contains_stationary_unit(c)
        }
        attempts = 0
        while game_state.get_resource(SP) >= turret_cost and empty_set and attempts < 20:
            attempts += 1
            cell = random.choice(list(empty_set))
            empty_set.discard(cell)
            sent = game_state.attempt_spawn(TURRET, list(cell))
            if sent > 0:
                gamelib.debug_write(f"RANDOM-TURRET: spawned at {cell}")

    # --- Offense (shared evaluator) -----------------------------------------

    def _evaluate_deploy_locations(self, game_state, mp):
        """Compute once per turn: for each unblocked friendly bottom-edge cell,
        simulate the scout path and record damage_taken, hp-weighted firepower,
        survivor count, depth, and whether path reaches enemy edge. All attack
        strategies share this evaluation — path simulation happens ONCE per cell."""
        gm = game_state.game_map
        friendly_edges = gm.get_edge_locations(gm.BOTTOM_LEFT) + gm.get_edge_locations(gm.BOTTOM_RIGHT)
        deploy_locations = [l for l in friendly_edges if not game_state.contains_stationary_unit(l)]
        enemy_edge_cells = set(map(tuple,
            gm.get_edge_locations(gm.TOP_LEFT) + gm.get_edge_locations(gm.TOP_RIGHT)))
        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        scout_hp = gamelib.GameUnit(SCOUT, game_state.config).max_health

        results = []
        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            if not path:
                continue
            reaches_enemy = tuple(path[-1]) in enemy_edge_cells
            damage_taken = 0
            firepower = 0.0
            for cell in path:
                attackers = game_state.get_attackers(cell, 0)
                damage_taken += len(attackers) * turret_damage
                for a in attackers:
                    hp_frac = (a.health / a.max_health) if a.max_health else 0
                    firepower += turret_damage * hp_frac
            survivors = max(0, mp - (damage_taken // scout_hp))
            depth = max(p[1] for p in path)
            results.append({
                "loc": loc,
                "reaches": reaches_enemy,
                "damage": damage_taken,
                "firepower": firepower,
                "survivors": survivors,
                "depth": depth,
            })
        return results

    def execute_scout_rush(self, game_state):
        mp = int(game_state.get_resource(MP))
        if mp < 5:
            return

        evals = self._evaluate_deploy_locations(game_state, mp)
        reaching = [e for e in evals if e["reaches"]]

        # HARD-KILL override: enemy HP ≤ HARD_KILL_HP → max-breach path.
        if game_state.enemy_health <= HARD_KILL_HP and reaching:
            best = max(reaching, key=lambda e: e["survivors"])
            self._commit_rush(game_state, best["loc"], mp,
                              tag=f"HARD-KILL (enemy hp={game_state.enemy_health:.0f} "
                                  f"survivors={best['survivors']})")
            return

        # ALT-ATTACK fallback: flip side, accept dead-end paths, max depth.
        if self.force_alternate_attack:
            alt = self._find_alternate_spawn(evals)
            if alt is not None:
                self._commit_rush(game_state, alt, mp, tag="ALT-ATTACK (opposite side, SD-accept)")
                self.force_alternate_attack = False
                self.consecutive_zero_breach_attacks = 0
                return
            self.force_alternate_attack = False  # fallthrough

        # Normal path: min HP-weighted firepower among paths reaching enemy.
        if not reaching:
            gamelib.debug_write("All scout paths dead-end — saving MP.")
            return
        best = min(reaching, key=lambda e: e["firepower"])

        # AGGRESSIVE-ATTACK: same best spawn, different tag.
        if self.aggressive_attack:
            self._commit_rush(game_state, best["loc"], mp, tag="AGGRESSIVE-ATTACK")
            self.aggressive_attack = False
            return

        self._commit_rush(
            game_state, best["loc"], mp,
            tag=f"Scout rush (fp={best['firepower']:.1f} raw_dmg={best['damage']})"
        )

    def _commit_rush(self, game_state, loc, mp, tag):
        game_state.attempt_spawn(SCOUT, loc, 1000)
        gamelib.debug_write(f"{tag}: {mp} scouts at {loc}")
        self.last_attack_side = "BL" if loc[0] < 14 else "BR"
        self._launched_attack_last_turn = True

    def _find_alternate_spawn(self, evals):
        """From shared evaluator results, pick opposite-side cell with deepest path."""
        if self.last_attack_side == "BR":
            opposite = [e for e in evals if e["loc"][0] < 14]
        else:
            opposite = [e for e in evals if e["loc"][0] >= 14]
        if not opposite:
            return None
        return max(opposite, key=lambda e: e["depth"])["loc"]


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
