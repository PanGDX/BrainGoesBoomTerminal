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
        
        # Track enemy attacks on left vs right sides for reinforcement prioritizing
        self.left_attacks = 0
        self.right_attacks = 0

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
        REFUND_THRESHOLD_TURRET = 0.0

        # Read the raw build order (left side only) and expand it symmetrically
        with open(os.path.join(os.path.dirname(__file__), 'build-order.json'), 'r') as f:
            raw_build_order = json.loads(f.read())
            
        self.build_order_left = {}
        self.build_order_right = {}
        
        for priority, job_list in raw_build_order.items():
            left_jobs = []
            right_jobs = []
            
            for job in job_list:
                # Add the left-side job
                left_job = dict(job)
                left_jobs.append(left_job)
                
                # Copy properties and formulate the symmetrical right-side job
                right_job = dict(job)
                right_job["location"] = [27 - job["location"][0], job["location"][1]]
                right_jobs.append(right_job)
                
            # Sort by absolute distance from x center (13.5 for perfect symmetry) and then by y
            # reverse=True builds INWARDS (largest distance from center first) and DOWN (largest y first)
            left_jobs.sort(key=lambda j: (abs(j["location"][0] - 13.5), j["location"][1]), reverse=True)
            right_jobs.sort(key=lambda j: (abs(j["location"][0] - 13.5), j["location"][1]), reverse=True)
            
            self.build_order_left[priority] = left_jobs
            self.build_order_right[priority] = right_jobs

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
        Intercepts action frames from the engine.
        To completely eliminate latency, we only process the 1st frame of the action phase.
        We track the enemy spawns using standard integer increments (fastest approach).
        """
        state = json.loads(turn_string)
        
        # turnInfo[0] == 1 implies Action Phase, turnInfo[2] == 0 implies the very first frame
        if state["turnInfo"][0] == 1 and state["turnInfo"][2] == 0:
            spawns = state.get("events", {}).get("spawn", [])
            for spawn in spawns:
                loc = spawn[0]      # e.g., [20, 27]
                unit_type = spawn[1] # 3 = Scout, 4 = Demolisher, 5 = Interceptor
                
                # Check if it is a Mobile unit and spawned on the enemy half (y >= 14)
                if unit_type in (3, 4, 5) and loc[1] >= 14:
                    # Increment corresponding side based on spawn X coordinate
                    if loc[0] <= 13:
                        self.left_attacks += 1
                    else:
                        self.right_attacks += 1


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


    def build_default_defences(self, game_state):
        """
        Build and patch defenses based on priority levels, building inwards and then down.
        Dynamically prioritizes the side (left/right) that is being attacked the most!
        """
        stop_flag = False

        # Determine which side is under heavier attack
        prioritize_left = self.left_attacks >= self.right_attacks

        # Use keys from build_order_left so original json block sequence is strictly maintained
        for priority in self.build_order_left.keys():
            if stop_flag:
                break
            
            left_jobs = self.build_order_left.get(priority, [])
            right_jobs = self.build_order_right.get(priority, [])

            # Place prioritized side's jobs at the front of the queue
            if prioritize_left:
                ordered_jobs = left_jobs + right_jobs
            else:
                ordered_jobs = right_jobs + left_jobs

            for build_job in ordered_jobs:
                unit = eval(build_job["unit"])
                location = build_job["location"]

                if game_state.get_resource(SP) - game_state.type_cost(unit)[0] < self.min_sp_to_save:
                    stop_flag = True
                    break
                
                if build_job["type"] == "spawn":
                    game_state.attempt_spawn(unit, location)
                elif build_job["type"] == "upgrade":
                    game_state.attempt_upgrade(location)


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


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
