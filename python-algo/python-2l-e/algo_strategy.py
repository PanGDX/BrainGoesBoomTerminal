import gamelib
import random
import math
import warnings
from sys import maxsize
import json
import os

"""
Most of the algo code you write will be in this file unless you create new
modules yourself. Start by modifying the 'on_turn' function.

Advanced strategy tips: 

  - You can analyze action frames by modifying on_action_frame function

  - The GameState.map object can be manually manipulated to create hypothetical 
  board states. Though, we recommended making a copy of the map to preserve 
  the actual current map state.
"""
# Aggressive-attack: enemy lost ≥60% supports last turn → commit all MP at min-firepower path.
AGGRESSIVE_ATTACK_LOSS_RATIO = 0.60
AGGRESSIVE_ATTACK_MIN_PRIOR = 3

# Scout spawn priority: 4 edge-corner clusters (3 cells each, cells closest
# to the true corner first). First cell whose path reaches the enemy edge AND
# whose single-scout final HP (incl. upgraded-support shield buffs) ≥
# CORNER_MIN_FINAL_HP wins. Falls back to the HP-weighted-firepower scan.
SCOUT_CORNER_PRIORITY = [
    # BL edge — top-left corner and 2 inward cells
    (0, 13), (1, 12), (2, 11),
    # BL edge — bottom corner and 2 inward cells
    (13, 0), (12, 1), (11, 2),
    # BR edge — bottom corner and 2 inward cells
    (14, 0), (15, 1), (16, 2),
    # BR edge — top-right corner and 2 inward cells
    (27, 13), (26, 12), (25, 11),
]
CORNER_MIN_FINAL_HP = 4


class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

        # Dictionary to track precise enemy scout spawn locations
        self.enemy_scout_spawns = {}

        # Adaptive layer state
        self.aggressive_attack = False
        self.last_enemy_support_count = 0

        # Alternate-attack fallback: if N consecutive scout rushes produce zero
        # enemy breaches, flip side and accept dead-end SD paths.
        self.last_attack_side = None          # "BL" or "BR" — side of last rush
        self.consecutive_zero_breach_attacks = 0
        self.force_alternate_attack = False
        self._pending_our_breaches = 0        # count during action phase
        self._launched_attack_last_turn = False
        self.ALT_ATTACK_THRESHOLD = 5

    def on_game_start(self, config):
        """ 
        Read in config and perform any initial setup here 
        """
        gamelib.debug_write('Configuring your custom algo strategy...')
        self.config = config
        global WALL, SUPPORT, TURRET, SCOUT, DEMOLISHER, INTERCEPTOR, MP, SP, REFUND_THRESHOLD_WALL, REFUND_THRESHOLD_TURRET
        global ENEMY_EDGE_DEFENSE_LOCATIONS_LEFT, ENEMY_EDGE_DEFENSE_LOCATIONS_RIGHT 
        global ATTACK_DEMOLISHER_LOCATION_LEFT, ATTACK_DEMOLISHER_LOCATION_RIGHT
        global DEFENSE_INTERCEPTOR_LOCATION_LEFT, DEFENSE_INTERCEPTOR_LOCATION_RIGHT
        global ATTACK_LEFT_SCOUT_FIRST_GROUP_LOCATION, ATTACK_LEFT_SCOUT_SECOND_GROUP_LOCATION
        global ATTACK_RIGHT_SCOUT_FIRST_GROUP_LOCATION, ATTACK_RIGHT_SCOUT_SECOND_GROUP_LOCATION
        global ATTACK_LEFT_REMOVE_WALL_LOCATION, ATTACK_RIGHT_REMOVE_WALL_LOCATION
        
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
        with open(os.path.join(os.path.dirname(__file__), 'upgrade-order.json'), 'r') as f:
            self.upgrade_order = json.loads(f.read())

        ENEMY_EDGE_DEFENSE_LOCATIONS_LEFT = [[0, 14], [1, 14], [2, 14], [3, 14], [4, 14], [1, 15], [2, 15], [3, 15], [2, 16], [3, 16]]
        ENEMY_EDGE_DEFENSE_LOCATIONS_RIGHT = [[27, 14], [26, 14], [25, 14], [24, 14], [23, 14], [26, 15], [25, 15], [24, 15], [25, 16], [24, 16]]

        ATTACK_DEMOLISHER_LOCATION_LEFT = [6, 7]
        ATTACK_DEMOLISHER_LOCATION_RIGHT = [21, 7]
        DEFENSE_INTERCEPTOR_LOCATION_LEFT = [7, 6]
        DEFENSE_INTERCEPTOR_LOCATION_RIGHT = [20, 6]
        ATTACK_LEFT_SCOUT_FIRST_GROUP_LOCATION = [14, 0]
        ATTACK_LEFT_SCOUT_SECOND_GROUP_LOCATION = [21, 7]
        ATTACK_RIGHT_SCOUT_FIRST_GROUP_LOCATION = [13, 0]
        ATTACK_RIGHT_SCOUT_SECOND_GROUP_LOCATION = [8, 5]
        ATTACK_LEFT_REMOVE_WALL_LOCATION = [6, 7]
        ATTACK_RIGHT_REMOVE_WALL_LOCATION = [21, 8]

        self.enemy_left_edge_strength = 100
        self.enemy_right_edge_strength = 100
        self.enemy_left_edge_blocked = True
        self.enemy_right_edge_blocked = True
        self.enemy_left_edge_misdirecting = False
        self.enemy_right_edge_misdirecting = False
        self.my_MP = 0
        self.enemy_MP = 0
        self.turn_strategy = "defend" 
        self.attack_turn = 0 

        self.min_sp_to_save = 0 


    def on_action_frame(self, turn_string):
        """
        Intercepts action frames to map enemy scout spawn locations.
        """
        state = json.loads(turn_string)
        events = state.get("events", {})

        # turnInfo[0] == 1 implies Action Phase, turnInfo[2] == 0 implies first action frame
        if state["turnInfo"][0] == 1 and state["turnInfo"][2] == 0:
            for spawn in events.get("spawn", []):
                loc = spawn[0]
                unit_type = spawn[1]
                if unit_type == 3 and loc[1] >= 14:
                    key = f"{loc[0]}:{loc[1]}"
                    self.enemy_scout_spawns[key] = self.enemy_scout_spawns.get(key, 0) + 1

        # Count OUR breach events (player==1 = our walker reached enemy edge).
        for breach in events.get("breach", []):
            if len(breach) >= 5 and breach[4] == 1:
                self._pending_our_breaches += 1



    def on_turn(self, turn_state):
        game_state = gamelib.GameState(self.config, turn_state)

        # Update alternate-attack fallback: if we attacked last turn with zero
        # breaches, increment counter; reset on success.
        if self._launched_attack_last_turn:
            if self._pending_our_breaches == 0:
                self.consecutive_zero_breach_attacks += 1
            else:
                self.consecutive_zero_breach_attacks = 0
        self._pending_our_breaches = 0
        self._launched_attack_last_turn = False
        if self.consecutive_zero_breach_attacks >= self.ALT_ATTACK_THRESHOLD:
            self.force_alternate_attack = True
            gamelib.debug_write(
                f"ALT-ATTACK trigger: {self.consecutive_zero_breach_attacks} "
                f"consecutive zero-breach rushes from {self.last_attack_side}"
            )

        try:
            self.parse_game_state(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in parse_game_state: {e}")

        try:
            self._update_aggressive_attack_trigger(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in aggressive-attack trigger: {e}")

        try:
            self.starter_strategy(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in starter_strategy: {e}")

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
                    f"AGGRESSIVE-ATTACK trigger: enemy supports {self.last_enemy_support_count}→{current} "
                    f"(loss={loss:.0%})"
                )
        self.last_enemy_support_count = current



    def starter_strategy(self, game_state):
        self.build_defences(game_state)
        # self.deploy_anti_scout_interceptor(game_state) # --- NEW: Deploys preemptive interceptor
        self.execute_scout_rush(game_state)


    def parse_game_state(self, game_state):
        self.my_MP = game_state.get_resource(MP, 0)
        self.enemy_MP = game_state.get_resource(MP, 1)
        self.enemy_left_edge_blocked = self.is_enemy_left_edge_blocked(game_state)
        self.enemy_right_edge_blocked = self.is_enemy_right_edge_blocked(game_state)
        self.enemy_left_edge_misdirecting = self.is_enemy_left_edge_misdirecting(game_state)
        self.enemy_right_edge_misdirecting = self.is_enemy_right_edge_misdirecting(game_state)
        self.enemy_left_edge_strength = self.compute_enemy_left_edge_defense_strength(game_state)
        self.enemy_right_edge_strength = self.compute_enemy_right_edge_defense_strength(game_state)


    def is_enemy_left_edge_misdirecting(self, game_state):
        return not self.enemy_left_edge_blocked and game_state.contains_stationary_unit([0, 14])

    def is_enemy_right_edge_misdirecting(self, game_state):
        return not self.enemy_right_edge_blocked and game_state.contains_stationary_unit([27, 14])


    def is_enemy_left_edge_blocked(self, game_state):
        path = game_state.find_path_to_edge([1, 13], game_state.game_map.TOP_RIGHT)
        if path == None:
            return False 

        if len(path) < 10:
            return True
        for i in range(10):
            location = path[i]
            if location[1] < 13:
                return True
        return False


    def is_enemy_right_edge_blocked(self, game_state):
        path = game_state.find_path_to_edge([26, 13], game_state.game_map.TOP_LEFT)
        if path == None:
            return False 
        
        if len(path) < 10:
            return True
        for i in range(10):
            location = path[i]
            if location[1] < 13:
                return True
        return False


    def compute_enemy_left_edge_defense_strength(self, game_state):
        strength = 0
        for location in ENEMY_EDGE_DEFENSE_LOCATIONS_LEFT:
            distance_to_edge = math.dist([0.5, 13], location)
            unit_strength = 0

            unit = game_state.contains_stationary_unit(location)
            if unit and unit.unit_type == TURRET:
                if unit.upgraded:
                    unit_strength = 25 / distance_to_edge
                else:
                    unit_strength = 5 / distance_to_edge
            elif location[1] == 14 and unit and unit.unit_type == WALL:
                if unit.upgraded:
                    unit_strength = 3
                else:
                    unit_strength = 1
            strength += unit_strength
        return strength


    def compute_enemy_right_edge_defense_strength(self, game_state):
        strength = 0
        for location in ENEMY_EDGE_DEFENSE_LOCATIONS_RIGHT:
            distance_to_edge = math.dist([26.5, 13], location)
            unit_strength = 0

            unit = game_state.contains_stationary_unit(location)
            if unit and unit.unit_type == TURRET:
                if unit.upgraded:
                    unit_strength = 25 / distance_to_edge
                else:
                    unit_strength = 5 / distance_to_edge
            elif location[1] == 14 and unit and unit.unit_type == WALL:
                if unit.upgraded:
                    unit_strength = 3
                else:
                    unit_strength = 1
            strength += unit_strength
        return strength


    def build_defences(self, game_state):
        self.refund_low_health_structures(game_state)
        self.build_default_defences(game_state)
        self._build_random_turrets_fallback(game_state)

    def _build_random_turrets_fallback(self, game_state):
        """After all build/upgrade tiers complete, spend any leftover SP on
        random turrets — restricted to y in [11, 13] to match the curated
        build-order's layout (no placements below y=11)."""
        turret_cost = game_state.type_cost(TURRET)[0]
        upper_half = [
            cell for cell in self.enumerate_friendly_side_locations(game_state)
            if 11 <= cell[1] <= 13
        ]
        attempts = 0
        max_attempts = 20
        while game_state.get_resource(SP) >= turret_cost and attempts < max_attempts:
            attempts += 1
            empty = [c for c in upper_half if not game_state.contains_stationary_unit(c)]
            if not empty:
                return
            cell = random.choice(empty)
            sent = game_state.attempt_spawn(TURRET, cell)
            if sent > 0:
                gamelib.debug_write(f"RANDOM-TURRET: spawned at {cell}")


    def enumerate_friendly_side_locations(self, game_state):
        locations = []
        for x in range(game_state.ARENA_SIZE):
            if x < game_state.HALF_ARENA:
                for y in range(game_state.HALF_ARENA - x - 1, game_state.HALF_ARENA):
                    locations.append([x, y])
            else:
                for y in range(x - 14, game_state.HALF_ARENA):
                    locations.append([x, y])
        return locations


    def refund_low_health_structures(self, game_state):
        for location in self.enumerate_friendly_side_locations(game_state):
            structure = game_state.contains_stationary_unit(location)
            if structure:
                if structure.unit_type == TURRET:
                    if structure.health / structure.max_health < REFUND_THRESHOLD_TURRET:
                        game_state.attempt_remove(location)
                elif structure.unit_type == WALL:
                    if structure.health / structure.max_health < REFUND_THRESHOLD_WALL:
                        game_state.attempt_remove(location)


    def build_default_defences(self, game_state):
        """
        Build and patch defenses based on priority levels, then process upgrades.
        Prioritizes structures by Euclidean distance if an enemy scout path is detected.
        """
        stop_flag = False

        # 1. Identify all locations the enemy has spawned at >= 2 times and map their path
        vulnerable_path_points = []
        for loc_str, count in self.enemy_scout_spawns.items():
            if count >= 2:
                # Convert "x:y" back to [x, y]
                x_str, y_str = loc_str.split(":")
                spawn_location = [int(x_str), int(y_str)]
                
                # Get the route these scouts will take based on the current board state
                path = game_state.find_path_to_edge(spawn_location)
                if path:
                    vulnerable_path_points.extend(path)

        for priority in ["start", "extra_supports", "sides", "frontline", "catchline", "turret_upgrades"]:
            if stop_flag:
                break
            
            job_list = self.build_order.get(priority, [])

            # 2. If we found a vulnerable route, sort this priority's job_list by closest distance
            if vulnerable_path_points:
                def min_distance_to_path(job):
                    job_loc = job["location"]
                    # Calculate Euclidean distance to the closest point on the enemy path
                    return min(math.sqrt((job_loc[0] - p[0])**2 + (job_loc[1] - p[1])**2) for p in vulnerable_path_points)
                
                job_list = sorted(job_list, key=min_distance_to_path)

            for build_job in job_list:
                unit = eval(build_job["unit"])
                location = build_job["location"]

                if game_state.get_resource(SP) - game_state.type_cost(unit)[0] < self.min_sp_to_save:
                    stop_flag = True
                    break
                if build_job["type"] == "spawn":
                    game_state.attempt_spawn(unit, location)
                if build_job["type"] == "upgrade":
                    game_state.attempt_upgrade(location)


    def deploy_anti_scout_interceptor(self, game_state):
        """
        If an enemy has spawned scouts at the exact same location >= 4 times, 
        find the path they are taking and drop an Interceptor directly on/near it.
        """
        my_mp = int(game_state.get_resource(MP, 0))
        enemy_mp = int(game_state.get_resource(MP, 1))

        # Only deploy if we have MP, and the enemy has enough MP (>=5) to do a dangerous scout rush
        if my_mp >= 1 and enemy_mp >= 5:
            for loc_str, count in self.enemy_scout_spawns.items():
                if count >= 4:
                    x_str, y_str = loc_str.split(":")
                    spawn_location = [int(x_str), int(y_str)]
                    
                    path = game_state.find_path_to_edge(spawn_location)
                    if not path:
                        continue
                        
                    friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + \
                                     game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
                    
                    available_edges = [loc for loc in friendly_edges if not game_state.contains_stationary_unit(loc)]
                    
                    if not available_edges:
                        continue

                    # 1. Look for an exact intersection between the enemy's path and our allowed spawn edges
                    intersection = [loc for loc in path if loc in available_edges]
                    
                    if intersection:
                        best_loc = intersection[-1] 
                    else:
                        # 2. If no direct intersection, find our available edge that is closest to their path
                        def min_dist_to_path(edge_loc):
                            return min(math.sqrt((edge_loc[0] - p[0])**2 + (edge_loc[1] - p[1])**2) for p in path)
                        
                        best_loc = min(available_edges, key=min_dist_to_path)
                    
                    # Spawn interceptor and subtract 1 MP cost for the rest of our turn
                    if game_state.attempt_spawn(INTERCEPTOR, best_loc, 1):
                        gamelib.debug_write(f"High-threat scout spam detected (>=4 times) from {spawn_location}. Deployed Interceptor at {best_loc}.")
                        break  # One interceptor is usually enough to disrupt a wave, saves MP.


    def execute_scout_rush(self, game_state):
        """
        Bomb rush the gap in defense using Scouts.
        """
        mp = int(game_state.get_resource(MP))
        if mp < 5:
            return

        # HARD-KILL override: enemy HP ≤ 12 → pick path with MAX breach damage
        # (fewest scout deaths → most scouts reach enemy edge → most HP dmg).
        if game_state.enemy_health <= 12:
            hk_loc = self._find_max_breach_path(game_state, mp)
            if hk_loc is not None:
                game_state.attempt_spawn(SCOUT, hk_loc, 1000)
                gamelib.debug_write(
                    f"HARD-KILL: {mp} scouts at {hk_loc} (enemy hp={game_state.enemy_health:.0f})"
                )
                self.last_attack_side = "BL" if hk_loc[0] < 14 else "BR"
                self._launched_attack_last_turn = True
                return

        # Alternate-attack fallback: flip side and accept dead-end SD paths.
        if self.force_alternate_attack:
            alt_loc = self._find_alternate_spawn(game_state)
            if alt_loc is not None:
                game_state.attempt_spawn(SCOUT, alt_loc, 1000)
                gamelib.debug_write(f"ALT-ATTACK fired: {mp} scouts at {alt_loc} (opposite side, SD-accept)")
                self.last_attack_side = "BL" if alt_loc[0] < 14 else "BR"
                self._launched_attack_last_turn = True
                self.force_alternate_attack = False
                self.consecutive_zero_breach_attacks = 0
                return
            self.force_alternate_attack = False  # couldn't find alt — fall through

        best_scout_location, lowest_damage = self.find_best_scout_spawn(game_state)
        if best_scout_location is None:
            gamelib.debug_write("All scout paths are dead-ends — saving MP.")
            return

        self.last_attack_side = "BL" if best_scout_location[0] < 14 else "BR"
        self._launched_attack_last_turn = True

        if self.aggressive_attack:
            game_state.attempt_spawn(SCOUT, best_scout_location, 1000)
            gamelib.debug_write(
                f"AGGRESSIVE-ATTACK fired: {mp} scouts at {best_scout_location}"
            )
            self.aggressive_attack = False
            return

        game_state.attempt_spawn(SCOUT, best_scout_location, 1000)
        gamelib.debug_write(f"Scout rush: {mp} scouts at {best_scout_location} (raw dmg={lowest_damage})")

    def _find_max_breach_path(self, game_state, mp):
        """Pick the spawn whose path lets the most scouts survive to breach.
        Scout dies when cumulative damage exceeds its HP (15). Survivors each
        deal 1 HP breach damage. Maximize survivors = maximize breach damage.
        """
        gm = game_state.game_map
        friendly_edges = gm.get_edge_locations(gm.BOTTOM_LEFT) + gm.get_edge_locations(gm.BOTTOM_RIGHT)
        deploy_locations = [l for l in friendly_edges if not game_state.contains_stationary_unit(l)]
        if not deploy_locations:
            return None
        enemy_edge_cells = set(map(tuple,
            gm.get_edge_locations(gm.TOP_LEFT) + gm.get_edge_locations(gm.TOP_RIGHT)))
        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        scout_hp = gamelib.GameUnit(SCOUT, game_state.config).max_health

        best_loc, best_survivors = None, -1
        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            if not path or tuple(path[-1]) not in enemy_edge_cells:
                continue
            damage_taken = 0
            for cell in path:
                attackers = game_state.get_attackers(cell, 0)
                damage_taken += len(attackers) * turret_damage
            # Each scout has scout_hp HP. Dead scouts = floor(damage / scout_hp).
            dead = damage_taken // scout_hp
            survivors = max(0, mp - dead)
            if survivors > best_survivors:
                best_survivors = survivors
                best_loc = loc
        return best_loc

    def _find_alternate_spawn(self, game_state):
        """Pick a spawn on the OPPOSITE side from last_attack_side, preferring
        the cell whose path goes DEEPEST into enemy territory (max y). Accepts
        dead-end paths — the point is to SD deep in enemy territory and cause
        collateral damage when the normal route is being funneled."""
        gm = game_state.game_map
        if self.last_attack_side == "BR":
            target_edge = gm.BOTTOM_LEFT
        else:
            target_edge = gm.BOTTOM_RIGHT
        cells = [l for l in gm.get_edge_locations(target_edge)
                 if not game_state.contains_stationary_unit(l)]
        if not cells:
            return None
        best_loc, best_depth = None, -1
        for l in cells:
            path = game_state.find_path_to_edge(l)
            if not path:
                continue
            depth = max(p[1] for p in path)
            if depth > best_depth:
                best_depth = depth
                best_loc = l
        return best_loc


    def _our_shielding_supports(self, game_state):
        """List of (x, y, shieldRange, shieldPerUnit) for our supports that
        actually buff walkers (shieldPerUnit > 0, i.e. upgraded)."""
        out = []
        for x in range(28):
            y_lo = 13 - x if x < 14 else x - 14
            for y in range(y_lo, 14):
                unit = game_state.contains_stationary_unit([x, y])
                if not unit or unit.unit_type != SUPPORT or unit.player_index != 0:
                    continue
                sper = getattr(unit, "shieldPerUnit", 0) or 0
                if sper <= 0:
                    continue
                out.append((x, y, getattr(unit, "shieldRange", 0) or 0, sper))
        return out

    def _simulate_scout_final_hp(self, game_state, spawn, scout_hp, turret_damage, supports):
        """Return (path, final_hp) for a single scout walking from `spawn`, or
        (None, None) if dead-end (path end not on enemy edge).

        final_hp = scout_hp + Σ shield_buff − Σ damage_taken along path. Each
        support buffs the walker ONCE when first entered within its range.
        """
        gm = game_state.game_map
        path = game_state.find_path_to_edge(spawn)
        if not path:
            return None, None
        enemy_edge = set(map(tuple,
            gm.get_edge_locations(gm.TOP_LEFT) + gm.get_edge_locations(gm.TOP_RIGHT)))
        if tuple(path[-1]) not in enemy_edge:
            return None, None  # dead-end

        applied = set()
        shield_bonus = 0
        damage_taken = 0
        for cell in path:
            for sx, sy, srange, sper in supports:
                if (sx, sy) in applied:
                    continue
                if math.hypot(cell[0] - sx, cell[1] - sy) <= srange:
                    applied.add((sx, sy))
                    shield_bonus += sper
            attackers = game_state.get_attackers(cell, 0)
            damage_taken += len(attackers) * turret_damage
        return path, scout_hp + shield_bonus - damage_taken

    def find_best_scout_spawn(self, game_state):
        """Priority 1: try the 4 edge-corners (SCOUT_CORNER_PRIORITY); first
        one whose path reaches the enemy edge AND whose single-scout final HP
        (incl. upgraded-support shield buffs) ≥ CORNER_MIN_FINAL_HP wins.

        Priority 2: min HP-weighted enemy firepower across all other edge cells.
        """
        gm = game_state.game_map
        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        scout_hp = gamelib.GameUnit(SCOUT, game_state.config).max_health
        supports = self._our_shielding_supports(game_state)

        # Priority 1: corners
        for corner in SCOUT_CORNER_PRIORITY:
            if game_state.contains_stationary_unit(list(corner)):
                continue
            path, final_hp = self._simulate_scout_final_hp(
                game_state, list(corner), scout_hp, turret_damage, supports
            )
            if path is None:
                continue  # dead-end or no path
            if final_hp >= CORNER_MIN_FINAL_HP:
                raw_damage = sum(
                    len(game_state.get_attackers(c, 0)) * turret_damage for c in path
                )
                gamelib.debug_write(
                    f"CORNER-PRIORITY: {list(corner)} final_hp={final_hp} raw_dmg={raw_damage}"
                )
                return list(corner), raw_damage

        # Priority 2: min HP-weighted firepower across all unblocked edges
        friendly_edges = gm.get_edge_locations(gm.BOTTOM_LEFT) + gm.get_edge_locations(gm.BOTTOM_RIGHT)
        deploy_locations = [loc for loc in friendly_edges if not game_state.contains_stationary_unit(loc)]
        if not deploy_locations:
            return None, float('inf')
        enemy_edge_cells = set(map(tuple,
            gm.get_edge_locations(gm.TOP_LEFT) + gm.get_edge_locations(gm.TOP_RIGHT)))

        best_loc = None
        best_firepower = float('inf')
        best_raw_damage = float('inf')
        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            if not path or tuple(path[-1]) not in enemy_edge_cells:
                continue
            firepower = 0.0
            raw_damage = 0
            for cell in path:
                attackers = game_state.get_attackers(cell, 0)
                raw_damage += len(attackers) * turret_damage
                for a in attackers:
                    hp_frac = (a.health / a.max_health) if a.max_health else 0
                    firepower += turret_damage * hp_frac
            if firepower < best_firepower:
                best_firepower = firepower
                best_raw_damage = raw_damage
                best_loc = loc

        if best_loc is None:
            return None, float('inf')
        gamelib.debug_write(
            f"SCOUT-PATH: loc={best_loc} fp={best_firepower:.1f} raw_dmg={best_raw_damage}"
        )
        return best_loc, best_raw_damage


    def spawn_interceptor(self, game_state, location, number):
        game_state.attempt_spawn(INTERCEPTOR, location, math.floor(number))
        
    def choose_number_of_interceptor_based_on_enemy_MP(self):
        return max(self.enemy_MP / 5, 2) 

    def spawn_scouts(self, game_state, location, number):
        game_state.attempt_spawn(SCOUT, location, math.floor(number))

    def spawn_demolisher(self, game_state, location, number):
        game_state.attempt_spawn(DEMOLISHER, location, math.floor(number))

    def choose_number_of_scouts_in_first_group_based_on_enemy_edge_strength(self, strength):
        return min(5 + math.floor(strength / 7), 10)
    
    def choose_number_of_demolishers_based_on_enemy_edge_strength(self, strength):
        return min(3 + math.floor(strength / 10), 5)


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
