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

        REFUND_THRESHOLD_WALL = 0
        REFUND_THRESHOLD_TURRET = 0
        with open(os.path.join(os.path.dirname(__file__), 'build-order.json'), 'r') as f:
            self.build_order = json.loads(f.read())


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
            self.starter_strategy(game_state)
        except Exception as e:
            gamelib.debug_write(f"Exception caught in starter_strategy: {e}")
        

        game_state.submit_turn()


    def starter_strategy(self, game_state):
        self.build_defences(game_state)
        self.execute_scout_rush(game_state)




    def build_defences(self, game_state):
        # self.refund_low_health_structures(game_state)
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

        for priority in ["start", "sides", "frontline", "catchline", "supportstructure"]:
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


    def execute_scout_rush(self, game_state):
        """
        Bomb rush the gap in defense using Scouts, or pummel if blocked.
        """
        mp = int(game_state.get_resource(MP))

        # Find the best path for a pure scout rush and observe anticipated damage
        best_scout_location, lowest_damage = self.find_best_scout_spawn(game_state)
        
        # If lowest_damage is infinity, it means EVERY spawn location is walled in / stuck.
        if lowest_damage == float('inf'):
            # Pummelling strategy: save up to 10 MP, then break defenses
            if mp < 10:
                gamelib.debug_write(f"All scout paths blocked! Saving MP for pummelling. Current MP: {mp}/10")
                return
            
            pummel_loc = [13, 0]
            if game_state.contains_stationary_unit(pummel_loc):
                pummel_loc = [14, 0]
                
            game_state.attempt_spawn(SCOUT, pummel_loc, 1000)
            gamelib.debug_write(f"Pummelling activated at {pummel_loc} with {mp} MP.")
            return

        # Normal rush requires at least 5 MP
        if mp < 5:
            return

        game_state.attempt_spawn(SCOUT, best_scout_location, 1000)
        gamelib.debug_write(f"Scout rush deployed at {best_scout_location} with {mp} MP. Route damage: {lowest_damage}")


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
        
        if not deploy_locations:
            return None, float('inf')

        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i
        enemy_supports = self._enemy_support_locations(game_state)
        SCOUT_ATTACK_RANGE = gamelib.GameUnit(SCOUT, game_state.config).attackRange

        # Valid enemy edges to confirm the path isn't blocked
        target_edges = game_state.game_map.get_edge_locations(game_state.game_map.TOP_LEFT) + \
                       game_state.game_map.get_edge_locations(game_state.game_map.TOP_RIGHT)

        valid_paths = []

        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            
            # If the path doesn't end on an enemy edge, it is a self-destruct (blocked) path.
            if not path or path[-1] not in target_edges:
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

        if valid_paths:
            # We sort the list of valid paths. 
            # 1st Priority: 'damage' ascending (Always prefer lowest damage).
            # 2nd Priority: '-supports' ascending (which means supports descending, to break ties).
            valid_paths.sort(key=lambda p: (p['damage'], -p['supports']))
            
            best_path = valid_paths[0]
            return best_path['loc'], best_path['damage']

        # Fallback: All paths are blocked. Return infinity to trigger pummelling.
        return None, float('inf')

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



if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
