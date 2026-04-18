import gamelib
import random
import math
import warnings
from sys import maxsize
import json
import os

from turret_placer import place_turrets

"""
Most of the algo code you write will be in this file unless you create new
modules yourself. Start by modifying the 'on_turn' function.

Advanced strategy tips: 

  - You can analyze action frames by modifying on_action_frame function

  - The GameState.map object can be manually manipulated to create hypothetical 
  board states. Though, we recommended making a copy of the map to preserve 
  the actual current map state.
"""

# Anchor turrets — these are spawned by the build-order `start` tier and
# treated by the placer as already-present (their coverage seeds the map).
# Must match the TURRET entries in build-order.json `start` tier.
ANCHOR_TURRETS = [
    (6, 13), (12, 12), (13, 13), (14, 13), (15, 12),
    (21, 13), (2, 12), (25, 12),
]
TURRET_SCORING_MODE = "path_freq"  # one of: "gap_fill", "stacking", "path_freq"

# Scout-spawn picker bonus per enemy SUPPORT in scout range along the path.
# Higher = more aggressive support-hunting (tolerate more turret damage to land
# the rush near supports). Upgraded supports count UPGRADED_MULT × this bonus.
SUPPORT_TARGET_BONUS = 30
SUPPORT_TARGET_UPGRADED_MULT = 2
SCOUT_ATTACK_RANGE = 3.5  # game-configs.json scout attackRange

class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))

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

        REFUND_THRESHOLD_WALL = 0.7
        REFUND_THRESHOLD_TURRET = 0.5
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

        # Enemy attack-tendency tracking (populated by on_action_frame).
        # Counts cumulative enemy mobile-unit spawns per flank.
        self.enemy_spawn_left = 0
        self.enemy_spawn_right = 0
        # Activation: tendency stays 0 until at least this many spawns observed.
        self.tendency_min_spawns = 5

        # Important characteristics of a game state, will be parsed in self.parse_game_state()
        self.enemy_left_edge_strength = 100
        self.enemy_right_edge_strength = 100
        self.enemy_left_edge_blocked = True
        self.enemy_right_edge_blocked = True
        self.enemy_left_edge_misdirecting = False
        self.enemy_right_edge_misdirecting = False
        self.my_MP = 0
        self.enemy_MP = 0
        self.turn_strategy = "defend" # defend, attack_left, attack_right
        self.attack_turn = 0 # first need to remove the defense then channel in

        self.min_sp_to_save = 0 # at least this amount of SP left in case need to repair for next turn


    def on_turn(self, turn_state):
        """
        This function is called every turn with the game state wrapper as
        an argument. The wrapper stores the state of the arena and has methods
        for querying its state, allocating your current resources as planned
        unit deployments, and transmitting your intended deployments to the
        game engine.
        """
        game_state = gamelib.GameState(self.config, turn_state)
        self.starter_strategy(game_state)

        game_state.submit_turn()


    def starter_strategy(self, game_state):
        self.build_defences(game_state)
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
        tendency = self._compute_attack_tendency()
        result = place_turrets(
            game_state,
            anchor_locations=ANCHOR_TURRETS,
            turret_shorthand=TURRET,
            scoring=TURRET_SCORING_MODE,
            attack_tendency=tendency,
        )
        gamelib.debug_write(
            f"placer: placed={len(result['placed'])} "
            f"upgraded={len(result['upgraded'])} "
            f"stop={result['stopped_reason']} "
            f"tendency={tendency:+.2f} (L={self.enemy_spawn_left} R={self.enemy_spawn_right})"
        )

    def _compute_attack_tendency(self):
        """Cumulative-spawn-derived flank tendency. Returns 0.0 until ≥ 5 spawns."""
        total = self.enemy_spawn_left + self.enemy_spawn_right
        if total < self.tendency_min_spawns:
            return 0.0
        return (self.enemy_spawn_left - self.enemy_spawn_right) / total

    def on_action_frame(self, turn_string):
        """Tally enemy mobile-unit spawn cells per flank. Read once per turn at
        the start of the deploy phase (turnInfo[0]==1, turnInfo[2]==0).
        """
        state = json.loads(turn_string)
        turn_info = state.get("turnInfo", [])
        if len(turn_info) < 3 or turn_info[0] != 1 or turn_info[2] != 0:
            return
        spawn_locs_this_turn = []
        for spawn in state.get("events", {}).get("spawn", []):
            if len(spawn) < 4:
                continue
            location, unit_type, _uid, player = spawn[0], spawn[1], spawn[2], spawn[3]
            # unit_type 3=SCOUT, 4=DEMOLISHER, 5=INTERCEPTOR; player 2 = enemy
            if player != 2 or unit_type not in (3, 4, 5):
                continue
            spawn_locs_this_turn.append(tuple(location))
            if location[0] < 14:
                self.enemy_spawn_left += 1
            else:
                self.enemy_spawn_right += 1
        if spawn_locs_this_turn:
            gamelib.debug_write(f"enemy_spawns_this_turn: {spawn_locs_this_turn}")


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
        """
        stop_flag = False

        for priority in ["start", "frontline","catchline", "supportstructure"]:
            if stop_flag:
                break
            
            job_list = self.build_order.get(priority, [])

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


    def execute_scout_rush(self, game_state):
        """
        Bomb rush the gap in defense using Scouts.
        If the path is too heavily defended, save up MP and use the alternative 
        Demolisher + Scout strategy.
        """
        mp = int(game_state.get_resource(MP))
        
        # We need at least 5 MP for any rush to be effective
        if mp < 5:
            return

        # Find the best path for a pure scout rush and observe anticipated damage
        best_scout_location, lowest_damage = self.find_best_scout_spawn(game_state)
        
        # Calculate if our pure scout rush will get melted (Corrected to SCOUT health)
        scout_health = gamelib.GameUnit(SCOUT, game_state.config).max_health
        total_scout_health = mp * scout_health

        funnel_locations = [[11, 4], [12, 3], [13, 2], [14, 2], [15, 3], [16, 4]]
        funnel_built = True
        for loc in funnel_locations:
            unit = game_state.contains_stationary_unit(loc)
            # If there's no unit, or the unit there isn't a wall, try to build it
            if not unit or unit.unit_type != WALL:
                funnel_built = False # Even if we just spawned it, wait until next turn to be safe

        
        if lowest_damage > total_scout_health * 0.8 and funnel_built:
            gamelib.debug_write(f"Picking Strategy: funnel")
            # Path is heavily defended. Run the alternative strategy.
            # Requires waiting until we have at least 8 MP for the Demolisher + Scouts
            if mp >= 8:
                left_strength = self.compute_enemy_left_edge_defense_strength(game_state)
                right_strength = self.compute_enemy_right_edge_defense_strength(game_state)
                
                # Determine which side to attack
                # (Spawning on the left edges targets top-right, Spawning on right targets top-left)
                if right_strength < left_strength:
                    # Attack right side by deploying on the left edge
                    demo_loc = [11,2]
                    scout_loc = [10, 3]
                else:
                    # Attack left side by deploying on the right edge
                    demo_loc = [16, 2]
                    scout_loc = [17, 3]
                
                # Ensure the specific deployment locations aren't blocked by our own walls
                if game_state.contains_stationary_unit(demo_loc):
                    game_state.attempt_remove(demo_loc)
                if game_state.contains_stationary_unit(scout_loc):
                    game_state.attempt_remove(scout_loc)

                # Deduct demolisher cost to determine how many scouts we can spam 
                # (Will act as vanguard/tank ahead of demolisher)
                demo_cost = game_state.type_cost(DEMOLISHER)[0]
                scouts_to_spawn = mp - demo_cost
                
                # Execute alternative strategy!
                game_state.attempt_spawn(SCOUT, scout_loc, scouts_to_spawn)
                game_state.attempt_spawn(DEMOLISHER, demo_loc, 1)
                
                gamelib.debug_write(f"Alternative Strategy deployed: Demolisher at {demo_loc}, {scouts_to_spawn} Scouts at {scout_loc}")
            else:
                gamelib.debug_write(f"Scouts would melt. Waiting for MP >= 8 for alternative strategy. Current MP: {mp}")
        else:
            # Path is safe enough to deploy normal pure scout rush
            game_state.attempt_spawn(SCOUT, best_scout_location, 1000)
            gamelib.debug_write(f"Scout rush deployed at {best_scout_location} with {mp} MP")


    def find_best_scout_spawn(self, game_state):
        """
        Pick the scout-spawn cell with the best score:
            score = damage_taken − SUPPORT_TARGET_BONUS × supports_in_range
        Lower score = better spawn. Returns (best_location, RAW damage_taken at that
        spawn) so the funnel-trigger threshold sees real damage, not the adjusted score.
        """
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + \
                         game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)

        deploy_locations = [loc for loc in friendly_edges if not game_state.contains_stationary_unit(loc)]
        default_corners = [[13, 0], [14, 0]]
        if not deploy_locations:
            return random.choice(default_corners), float('inf')

        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        enemy_supports = self._enemy_support_locations(game_state)

        best_location = None
        best_score = float('inf')
        best_raw_damage = float('inf')

        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            damage_taken = 0
            supports_hit = set()  # dedupe across path tiles

            for path_location in path:
                attackers = game_state.get_attackers(path_location, 0)
                damage_taken += len(attackers) * turret_damage
                for sx, sy, upgraded in enemy_supports:
                    if (sx, sy) in supports_hit:
                        continue
                    if math.dist((path_location[0] + 0.5, path_location[1] + 0.5),
                                 (sx + 0.5, sy + 0.5)) <= SCOUT_ATTACK_RANGE:
                        supports_hit.add((sx, sy))

            support_bonus = 0
            for sx, sy in supports_hit:
                upgraded = next(u for ux, uy, u in enemy_supports if (ux, uy) == (sx, sy))
                support_bonus += SUPPORT_TARGET_BONUS * (SUPPORT_TARGET_UPGRADED_MULT if upgraded else 1)

            score = damage_taken - support_bonus
            if score < best_score:
                best_score = score
                best_location = loc
                best_raw_damage = damage_taken

        # Fallback: no path scored or every path is harmless AND has no supports — pick a corner.
        if best_location is None or (best_raw_damage == 0 and best_score == 0):
            valid_corners = [c for c in default_corners if not game_state.contains_stationary_unit(c)]
            best_location = random.choice(valid_corners or default_corners)

        return best_location, best_raw_damage

    def _enemy_support_locations(self, game_state):
        """List of (x, y, upgraded) for every enemy SUPPORT on the board.

        Iterates the enemy half-diamond (y in [14, 27]) and filters by player
        index + unit type.
        """
        out = []
        for x in range(28):
            y_max = x + 14 if x < 14 else 41 - x
            for y in range(14, y_max + 1):
                unit = game_state.contains_stationary_unit([x, y])
                if not unit or unit.player_index != 1:
                    continue
                if unit.unit_type != SUPPORT:
                    continue
                out.append((x, y, getattr(unit, "upgraded", False)))
        return out


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
