import gamelib
import random
import math
import warnings
from sys import maxsize
import json


"""
Turret Defense + Scout Rush Strategy:
1. Build comprehensive turret defense network
2. Send interceptors early game until 15+ MP saved
3. Remove blocking turret and mass scout rush at [14,0]
"""

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
        gamelib.debug_write('Configuring Turret Defense Strategy...')
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
        
        # Defense setup tracking
        self.scored_on_locations = []
        self.ready_for_scout_rush = False
        self.turret_removed_for_attack = False
        
        # Primary turret defense positions (40 SP initial setup)
        self.primary_turrets = [
            [1,13], [2,13],[0,13], [1,12], [2,11], [3,10], [8,7],
            [3,13], [4,13], [4,12], [5,12], [5,11], [6,10], [7,9],
            [10,10], [11,11], [12,12], [13,13], [20,8], [20,7], [21,7],
            [20,9], [20,10], [21,10], [21,11], [22,11], [22,12], [23,12], [23,13], [24,13],
            [22,8], [23,9], [24,10], [25,11], [26,12], [27,13], [8,8], [9,6],[10,5], [11,4],[12,3], [13,2],  [14,2], [15,3], [16,3]
        ]
        
        # Secondary turret positions (build after primary complete)
        self.secondary_turrets = [[13,2], [22,13],[21,13],[20,13], [19,13], [18,13], [17,13],[16,13], [14,13], [15,13] ]
        
        # Support positions (build after all turrets complete)
        self.support_positions = [
            [11,10], [12,10], [11,9], [12,9], [13,9], [10,8], [11,8], [12,8], [13,8], [11,7], [11,8]
        ]
        
        # Attack positions
        self.interceptor_positions = [[18,4]]
        self.scout_attack_position1 = [14,0]
        self.scout_attack_position2 = [16,2]
        self.blocking_turret_position1 = [1,13]
        self.blocking_turret_position2 = [2,13]

    def on_turn(self, turn_state):
        """
        Main strategy execution
        """
        game_state = gamelib.GameState(self.config, turn_state)
        gamelib.debug_write('Turn {} - Turret Defense Strategy'.format(game_state.turn_number))
        game_state.suppress_warnings(True)

        # Execute defensive strategy
        self.execute_defensive_strategy(game_state)
        
        # Execute attack strategy 
        self.execute_attack_strategy(game_state)

        game_state.submit_turn()

    def execute_defensive_strategy(self, game_state):
        """
        Build and maintain turret defense network with supports
        """
        # Priority 1: Check and replace damaged structures (below 50% health)
        self.replace_damaged_structures(game_state)
        
        # Priority 2: Ensure all primary turrets are built/replaced
        self.build_primary_turrets(game_state)
        
        # Priority 3: Build secondary turrets if primary is complete
        if self.primary_turrets_complete(game_state):
            self.build_secondary_turrets(game_state)
        
        # Priority 4: Build support structures if all turrets complete
        if self.all_turrets_complete(game_state):
            self.build_support_structures(game_state)
            
        # Priority 5: Upgrade structures when we have excess SP (prevent overflow)
        self.upgrade_structures(game_state)

    def replace_damaged_structures(self, game_state):
        """
        Replace any turrets or supports below 50% health immediately
        """
        structures_replaced = 0
        
        # Check all turret positions (primary + secondary)
        all_turret_positions = self.primary_turrets + self.secondary_turrets
        for location in all_turret_positions:
            # Skip blocking turret if we're preparing for attack
            if (location == self.blocking_turret_position1 or location == self.blocking_turret_position2) and self.ready_for_scout_rush:
                continue
                
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    # Check if it's our unit and below 50% health
                    if unit.player_index == 0 and unit.health < (unit.max_health * 0.5):
                        # Remove and replace immediately
                        game_state.attempt_remove([location])
                        if game_state.can_spawn(TURRET, location):
                            game_state.attempt_spawn(TURRET, location)
                            structures_replaced += 1
                            gamelib.debug_write('Replaced damaged turret at {} (Health: {}/{})'.format(
                                location, unit.health, unit.max_health))
        
        # Check all support positions
        for location in self.support_positions:
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    # Check if it's our unit and below 50% health
                    if unit.player_index == 0 and unit.health < (unit.max_health * 0.5):
                        # Remove and replace immediately
                        game_state.attempt_remove([location])
                        if game_state.can_spawn(SUPPORT, location):
                            game_state.attempt_spawn(SUPPORT, location)
                            structures_replaced += 1
                            gamelib.debug_write('Replaced damaged support at {} (Health: {}/{})'.format(
                                location, unit.health, unit.max_health))
        
        if structures_replaced > 0:
            gamelib.debug_write('Emergency replacement: {} damaged structures rebuilt'.format(structures_replaced))

    def build_primary_turrets(self, game_state):
        """
        Build/replace primary turret positions
        """
        turrets_built = 0
        
        for location in self.primary_turrets:
            # Skip the blocking turret if we're preparing for attack
            if (location == self.blocking_turret_position1 or location == self.blocking_turret_position2) and self.ready_for_scout_rush:
                continue
                
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_built += 1
                    gamelib.debug_write('Built primary turret at {}'.format(location))
        
        if turrets_built > 0:
            gamelib.debug_write('Built/replaced {} primary turrets'.format(turrets_built))

    def build_secondary_turrets(self, game_state):
        """
        Build secondary turret positions after primary complete
        """
        turrets_built = 0
        
        for location in self.secondary_turrets:
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_built += 1
                    gamelib.debug_write('Built secondary turret at {}'.format(location))
        
        if turrets_built > 0:
            gamelib.debug_write('Built {} secondary turrets'.format(turrets_built))

    def upgrade_structures(self, game_state):
        """
        Upgrade structures starting from closest to enemy side to prevent SP overflow
        """
        sp = int(game_state.get_resource(SP))  # Convert to integer to avoid float errors
        
        # Only upgrade if we have excess SP and all basic structures are built
        if self.all_turrets_complete(game_state):
            
            # Get all our structures and sort by distance to enemy (closest first)
            all_positions = self.primary_turrets + self.secondary_turrets + self.support_positions
            
            # Sort by Y coordinate (higher Y = closer to enemy)
            sorted_positions = sorted(all_positions, key=lambda pos: pos[1], reverse=True)
            
            upgrades_made = 0
            for location in sorted_positions:
                # Skip if we don't have enough SP or if preparing for scout rush
                if sp < 5:
                    break
                    
                # Skip blocking turret if preparing for attack
                if (location == self.blocking_turret_position1 or location == self.blocking_turret_position2) and self.ready_for_scout_rush:
                    continue
                
                if game_state.contains_stationary_unit(location):
                    units_at_location = game_state.game_map[location]
                    for unit in units_at_location:
                        # Upgrade our unupgraded structures
                        if unit.player_index == 0 and not unit.upgraded:
                            if game_state.attempt_upgrade([location]):
                                upgrades_made += 1
                                sp -= int(game_state.type_cost(unit.unit_type, upgrade=True)[0])  # Subtract upgrade cost
                                gamelib.debug_write('Upgraded {} at {} (SP remaining: {})'.format(
                                    unit.unit_type, location, sp))
                                break
            
            if upgrades_made > 0:
                gamelib.debug_write('Upgraded {} structures to prevent SP overflow'.format(upgrades_made))

    def build_support_structures(self, game_state):
        """
        Build support structures after all turrets complete
        """
        supports_built = 0
        
        for location in self.support_positions:
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(SUPPORT, location):
                    game_state.attempt_spawn(SUPPORT, location)
                    supports_built += 1
                    gamelib.debug_write('Built support at {}'.format(location))
        
        if supports_built > 0:
            gamelib.debug_write('Built {} support structures'.format(supports_built))

    def primary_turrets_complete(self, game_state):
        """Check if all primary turrets are built"""
        for location in self.primary_turrets:
            # Skip checking blocking turret if we're preparing attack
            if (location == self.blocking_turret_position1 or location == self.blocking_turret_position2) and self.ready_for_scout_rush:
                continue
            if not game_state.contains_stationary_unit(location):
                return False
        return True

    def all_turrets_complete(self, game_state):
        """Check if all turrets (primary + secondary) are built"""
        return (self.primary_turrets_complete(game_state) and 
                all(game_state.contains_stationary_unit(loc) for loc in self.secondary_turrets))

    def execute_attack_strategy(self, game_state):
        """
        Execute attack strategy: interceptors early, then scout rush
        """
        mp = game_state.get_resource(MP)
        
        # Check if we're ready for scout rush
        if mp >= 15:
            self.ready_for_scout_rush = True
            
        if self.ready_for_scout_rush:
            # Execute scout rush sequence
            self.execute_scout_rush(game_state)
        else:
            # Early game interceptor harassment
            self.deploy_early_interceptors(game_state)

    def deploy_early_interceptors(self, game_state):
        """
        Deploy 1 interceptor only if enemy has >10 MP, our rush mode is off, AND it's within first 3 rounds
        """
        our_mp = int(game_state.get_resource(MP))  # Our MP
        enemy_mp = int(game_state.get_resource(MP, 1))  # Enemy MP (player index 1)
        turn = game_state.turn_number
        
        # Only deploy if enemy has >10 MP, we're not in rush mode, we can afford it, AND it's first 3 rounds
        if enemy_mp > 10 and not self.ready_for_scout_rush and our_mp >= 3 and turn <= 2:
            for position in self.interceptor_positions:
                if game_state.can_spawn(INTERCEPTOR, position):
                    game_state.attempt_spawn(INTERCEPTOR, position)
                    gamelib.debug_write('Deployed defensive interceptor at {} (Turn: {}, Enemy MP: {})'.format(
                        position, turn, enemy_mp))
                    break  # Deploy only 1 interceptor
        else:
            # Log why interceptor was not deployed
            if turn > 2:
                gamelib.debug_write('Skipping interceptor - Past turn 2 (Turn: {})'.format(turn))
            elif enemy_mp <= 10:
                gamelib.debug_write('Skipping interceptor - Enemy MP: {} ≤ 10 (Turn: {})'.format(enemy_mp, turn))
            elif self.ready_for_scout_rush:
                gamelib.debug_write('Skipping interceptor - Our rush mode active (Turn: {})'.format(turn))
            elif our_mp < 3:
                gamelib.debug_write('Skipping interceptor - Insufficient MP: {} (Turn: {})'.format(our_mp, turn))

    def execute_scout_rush(self, game_state):
        """
        Execute the scout rush: remove blocking turret BEFORE attack, then deploy 2-wave scout attack
        """
        our_mp = int(game_state.get_resource(MP))  # Convert to integer to avoid float errors
        enemy_mp = int(game_state.get_resource(MP, 1))  # Enemy MP
        # Phase 1: Remove blocking turret when we're close to attack threshold (but don't attack yet)
        if our_mp >= 12 and not self.turret_removed_for_attack:
            if game_state.contains_stationary_unit(self.blocking_turret_position1) or game_state.contains_stationary_unit(self.blocking_turret_position2):
                game_state.attempt_remove([self.blocking_turret_position1])
                game_state.attempt_remove([self.blocking_turret_position2])
                self.turret_removed_for_attack = True
            return
        
        # Phase 2: Deploy 2-wave scout attack only AFTER turret has been removed (next turn)
        if our_mp >= 15 and self.turret_removed_for_attack:  # Higher threshold for actual attack
            # Wave 1: Deploy 5 scouts at position 1 [14,0]
            wave1_scouts = min(3, our_mp)
            actual_wave1 = game_state.attempt_spawn(SCOUT, self.scout_attack_position1, wave1_scouts)
            
            if actual_wave1 > 0:
                gamelib.debug_write('SCOUT RUSH WAVE 1: Deployed {} scouts at {}'.format(
                    actual_wave1, self.scout_attack_position1))
                
                # Update MP after wave 1 deployment
                remaining_mp =our_mp - actual_wave1
                
                # Wave 2: Deploy all remaining scouts at position 2 [16,2]
                if remaining_mp > 0:
                    wave2_scouts = min(remaining_mp, 100)  # Cap at 20 for wave 2
                    actual_wave2 = game_state.attempt_spawn(SCOUT, self.scout_attack_position2, wave2_scouts)
                    
                    if actual_wave2 > 0:
                        gamelib.debug_write('SCOUT RUSH WAVE 2: Deployed {} scouts at {}'.format(
                            actual_wave2, self.scout_attack_position2))
                    
                    total_deployed = actual_wave1 + actual_wave2
                    gamelib.debug_write('TOTAL SCOUT RUSH: {} scouts deployed in 2 waves (Original MP: {})'.format(
                        total_deployed, our_mp))
                else:
                    gamelib.debug_write('SCOUT RUSH: Only wave 1 deployed ({} scouts total)'.format(actual_wave1))
            else:
                gamelib.debug_write('SCOUT RUSH: Failed to deploy wave 1 at {} (MP: {})'.format(
                    self.scout_attack_position1, our_mp))
        
        # Fallback: Only deploy backup interceptor if enemy has >10 MP (threat exists) AND it's first 3 rounds
        elif our_mp >= 3 and not self.turret_removed_for_attack and enemy_mp > 10 and game_state.turn_number <= 2:
            gamelib.debug_write('Scout rush mode but preparing (MP: {}), deploying backup interceptor (Turn: {}, Enemy MP: {})'.format(our_mp, game_state.turn_number, enemy_mp))
            for position in self.interceptor_positions:
                if game_state.can_spawn(INTERCEPTOR, position):
                    game_state.attempt_spawn(INTERCEPTOR, position)
                    gamelib.debug_write('Backup interceptor deployed at {} (Turn: {}, Enemy threat: {} MP)'.format(position, game_state.turn_number, enemy_mp))
                    break
        elif our_mp >= 3 and not self.turret_removed_for_attack:
            # Log why backup interceptor was not deployed
            if game_state.turn_number > 2:
                gamelib.debug_write('Scout rush preparation - NO interceptor deployed (Past turn 2: Turn {})'.format(game_state.turn_number))
            elif enemy_mp <= 10:
                gamelib.debug_write('Scout rush preparation - NO interceptor deployed (Enemy MP: {} ≤ 10)'.format(enemy_mp))

        def rebuild_blocking_turrets(self, game_state):
            """
            Rebuild the blocking turrets when we're done attacking
            """
            turrets_rebuilt = 0
            
            # Rebuild turret at position 1
            if not game_state.contains_stationary_unit(self.blocking_turret_position1):
                if game_state.can_spawn(TURRET, self.blocking_turret_position1):
                    game_state.attempt_spawn(TURRET, self.blocking_turret_position1)
                    turrets_rebuilt += 1
                    gamelib.debug_write('Rebuilt blocking turret at {}'.format(self.blocking_turret_position1))
            
            # Rebuild turret at position 2  
            if not game_state.contains_stationary_unit(self.blocking_turret_position2):
                if game_state.can_spawn(TURRET, self.blocking_turret_position2):
                    game_state.attempt_spawn(TURRET, self.blocking_turret_position2)
                    turrets_rebuilt += 1
                    gamelib.debug_write('Rebuilt blocking turret at {}'.format(self.blocking_turret_position2))
            
            if turrets_rebuilt > 0:
                gamelib.debug_write('Defensive perimeter restored: {} blocking turrets rebuilt'.format(turrets_rebuilt))

    def on_action_frame(self, turn_string):
        """
        Track where we get scored on for defensive analysis
        """
        state = json.loads(turn_string)
        events = state["events"]
        breaches = events["breach"]
        for breach in breaches:
            location = breach[0]
            unit_owner_self = True if breach[4] == 1 else False
            if not unit_owner_self:
                gamelib.debug_write("Got scored on at: {}".format(location))
                self.scored_on_locations.append(location)


if __name__ == "__main__":
    algo = AlgoStrategy()
    algo.start()