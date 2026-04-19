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
SUPPORT_TARGET_BONUS = 30
SUPPORT_TARGET_UPGRADED_MULT = 2
class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))
        
        # Dictionary to track precise enemy scout spawn locations
        self.enemy_scout_spawns = {}

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
        Intercepts action frames from the engine to map exact enemy scout spawn locations.
        """
        state = json.loads(turn_string)
        
        # turnInfo[0] == 1 implies Action Phase, turnInfo[2] == 0 implies the very first frame where units spawn
        if state["turnInfo"][0] == 1 and state["turnInfo"][2] == 0:
            spawns = state.get("events", {}).get("spawn", [])
            for spawn in spawns:
                loc = spawn[0]      # e.g., [20, 27]
                unit_type = spawn[1] # 3 = Scout
                
                # Check if it is a Scout and spawned on the enemy half (y >= 14)
                if unit_type == 3 and loc[1] >= 14:
                    # Format as "x:y" and increment the counter
                    key = f"{loc[0]}:{loc[1]}"
                    self.enemy_scout_spawns[key] = self.enemy_scout_spawns.get(key, 0) + 1
                    gamelib.debug_write(f"Enemy scout detected at {key}. Total times: {self.enemy_scout_spawns[key]}")


    def on_turn(self, turn_state):
        game_state = gamelib.GameState(self.config, turn_state)
        
        try:
            self.parse_game_state(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in parse_game_state: {e}")

        try:
            self.starter_strategy(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in starter_strategy: {e}")
        

        game_state.submit_turn()


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

        for priority in ["start", "sides", "frontline", "catchline", "supportstructure", "turret_upgrades"]:
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
        
        # We need at least 5 MP for any rush to be effective
        if mp < 5:
            return

        # Find the best path for a pure scout rush and observe anticipated damage
        best_scout_location, lowest_damage = self.find_best_scout_spawn(game_state)
        
        # If lowest_damage is infinity, it means EVERY spawn location is walled in / stuck.
        # We abort the spawn to prevent wasting MP on troops that will instantly self-destruct.
        if lowest_damage == float('inf'):
            gamelib.debug_write("All scout paths are stuck/blocked! Saving MP.")
            return

        game_state.attempt_spawn(SCOUT, best_scout_location, 1000)
        gamelib.debug_write(f"Scout rush deployed at {best_scout_location} with {mp} MP. Route damage: {lowest_damage}")


    def _enemy_support_locations(self, game_state):
        """List of (x, y, upgraded) for every enemy SUPPORT on the board."""
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


    def find_best_scout_spawn(self, game_state):
        """
        Calculates the safest route to the enemy edge.
        Primary Objective: STRICTLY minimize damage taken.
        Secondary Objective: If multiple paths take the exact same minimal damage, 
                             pick the one that hits the most exposed supports.
        """
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + \
                         game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)

        deploy_locations = [loc for loc in friendly_edges if not game_state.contains_stationary_unit(loc)]
        default_corners = [[13, 0], [14, 0]]
        
        if not deploy_locations:
            return random.choice(default_corners), float('inf')

        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        enemy_supports = self._enemy_support_locations(game_state)
        SCOUT_ATTACK_RANGE = gamelib.GameUnit(SCOUT, game_state.config).attackRange

        valid_paths = []

        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            
            # ISSUE 1 FIX: If the path ends on our half of the board (y < 13), 
            # the troop is stuck and will self-destruct. Discard this location.
            if not path or path[-1][1] < 13:
                continue
                
            damage_taken = 0
            supports_hit = set()

            for path_location in path:
                attackers = game_state.get_attackers(path_location, 0)
                damage_taken += len(attackers) * turret_damage
                
                for sx, sy, upgraded in enemy_supports:
                    if (sx, sy) in supports_hit:
                        continue
                    # Check if support is within scout's attack range
                    if math.sqrt((path_location[0] + 0.5 - (sx + 0.5))**2 + (path_location[1] + 0.5 - (sy + 0.5))**2) <= SCOUT_ATTACK_RANGE:
                        supports_hit.add((sx, sy))

            valid_paths.append({
                'loc': loc,
                'damage': damage_taken,
                'supports': len(supports_hit)
            })

        # ISSUE 2 & 3 FIX: Separate pure rushing from support hunting.
        if valid_paths:
            # We sort the list of valid paths. 
            # 1st Priority: 'damage' ascending (Always prefer lowest damage).
            # 2nd Priority: '-supports' ascending (which means supports descending, to break ties).
            valid_paths.sort(key=lambda p: (p['damage'], -p['supports']))
            
            best_path = valid_paths[0]
            return best_path['loc'], best_path['damage']

        # Fallback: Every single edge location is blocked/stuck.
        valid_corners = [c for c in default_corners if not game_state.contains_stationary_unit(c)]
        return random.choice(valid_corners or default_corners), float('inf')


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
