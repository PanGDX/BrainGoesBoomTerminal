import gamelib
import random
from sys import maxsize

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
        
        # --- STARTING DEFENSIVE FORMATION ---
        # Note: I removed the duplicate [25, 12] from your prompt
        self.base_turrets = [[2, 12], [25, 12], [9, 10], [14, 10], [19,10]]
        self.base_supports = [[13, 8]]
        self.base_walls = [[0,13],[1,13],[2, 13],
                           [9,11],
                           [14,11],
                           [19,11],
                           [25,13],[26,13],[27,13]]
        
        # --- FUTURE EXPANSION LISTS ---
        # Add your future coordinates here. The algorithm will build these 
        # only AFTER ensuring the base defenses are fully intact.
        self.future_turrets = []
        self.future_supports = [[14,8]]
        self.future_walls = [[3,13],[3,12],
                             [24,13],[24,12],
                            
                             ]

    def on_turn(self, turn_state):
        """
        Main strategy execution called every turn
        """
        game_state = gamelib.GameState(self.config, turn_state)
        game_state.suppress_warnings(True)

        # 1. Defense Phase
        self.rebuild_defenses(game_state)
        self.expand_defenses(game_state)
        
        # 2. Attack Phase
        self.execute_scout_rush(game_state)

        game_state.submit_turn()

    def rebuild_defenses(self, game_state):
        """
        Prioritize rebuilding the base starting formation if anything was destroyed.
        """
        # Rebuild Walls
        for loc in self.base_walls:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(WALL, loc):
                game_state.attempt_spawn(WALL, loc)
                
        # Rebuild Turrets
        for loc in self.base_turrets:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(TURRET, loc):
                game_state.attempt_spawn(TURRET, loc)
                
        # Rebuild Supports
        for loc in self.base_supports:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(SUPPORT, loc):
                game_state.attempt_spawn(SUPPORT, loc)

    def expand_defenses(self, game_state):
        """
        If we have remaining SP after rebuilding, build out the expansion lists.
        """
        # Expand Walls
        for loc in self.future_walls:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(WALL, loc):
                game_state.attempt_spawn(WALL, loc)
                
        # Expand Turrets
        for loc in self.future_turrets:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(TURRET, loc):
                game_state.attempt_spawn(TURRET, loc)
                
        # Expand Supports
        for loc in self.future_supports:
            if not game_state.contains_stationary_unit(loc) and game_state.can_spawn(SUPPORT, loc):
                game_state.attempt_spawn(SUPPORT, loc)

    def execute_scout_rush(self, game_state):
        """
        Bomb rush the gap in defense using Scouts.
        """
        mp = int(game_state.get_resource(MP))
        
        # Wait until we have enough MP to make the rush effective (e.g., 12+ MP)
        if mp >= 5:
            best_location = self.find_best_scout_spawn(game_state)
            
            # Spend all available MP on scouts at the most optimal location
            game_state.attempt_spawn(SCOUT, best_location, 1000)
            gamelib.debug_write(f"Scout rush deployed at {best_location} with {mp} MP")

    def find_best_scout_spawn(self, game_state):
        """
        Simulate pathing from all valid edge locations to find the path that takes 
        the LEAST damage from enemy turrets. Defaults to corners.
        """
        # Get all friendly deployable edges
        friendly_edges = game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_LEFT) + game_state.game_map.get_edge_locations(game_state.game_map.BOTTOM_RIGHT)
        
        # Filter out edges that we blocked with our own walls/turrets
        deploy_locations = [loc for loc in friendly_edges if not game_state.contains_stationary_unit(loc)]
        
        # Default fallback corners
        default_corners = [[13, 0], [14, 0]]
        
        if not deploy_locations:
            return random.choice(default_corners)

        best_location = None
        lowest_damage = float('inf')
        
        # Turret damage reference
        turret_damage = gamelib.GameUnit(TURRET, game_state.config).damage_i

        for loc in deploy_locations:
            path = game_state.find_path_to_edge(loc)
            damage_taken = 0
            
            for path_location in path:
                # Count how many enemy turrets can attack this specific tile
                attackers = game_state.get_attackers(path_location, 0) # 0 is our player index
                damage_taken += len(attackers) * turret_damage
                
            if damage_taken < lowest_damage:
                lowest_damage = damage_taken
                best_location = loc
                
        # If the lowest damage path still gets absolutely melted (e.g., heavily fortified board),
        # or if the board is empty and damage is 0 everywhere, default to the corners.
        if lowest_damage == 0 or lowest_damage > (turret_damage * 10): 
            # Make sure our default corners aren't blocked by our own defenses
            valid_corners = [c for c in default_corners if not game_state.contains_stationary_unit(c)]
            if valid_corners:
                return random.choice(valid_corners)
                
        return best_location

if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()
