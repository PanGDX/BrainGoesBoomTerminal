import gamelib
import random
import math
import warnings
from sys import maxsize
import json


"""
Turret Defense + Scout Rush Strategy:
1. Build comprehensive turret defense network
2. 3-Phase Attack System (ALWAYS rebuilds defenses after each attack):
   - Phase 1: ADD funnel turret at [22,11], REMOVE turrets at blocking_turret_position2 (MP >= 15)
   - Phase 2: Deploy 3 scouts at [13,0] + 12 scouts at [11,2] AND remove funnel turret [22,11] (same turn)
   - Phase 3: ALWAYS rebuild all blocking_turret_position2 turrets and reset all flags (next turn)
3. Hard reset to normal defensive state before each new attack cycle
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
        self.attack_path_cleared = False  # Hardcoded indicator for attack readiness
        
        # Primary turret defense positions
        self.primary_turrets = [
            [0,13],[1,12],[1,13],[2,12],[2,13],[3,12],[3,13],[4,12],[4,13],[5,12],[6,12],[7,12],[8,12],[9,12],[10,12],[11,12],[12,12],[13,12],[14,12],[15,12],[16,11],[17,10],[18,11],[19,12],[20,12],[21,12],[22,12],[23,12],[23,13],[24,12],[24,13],[25,12],[25,13],[26,12],[26,13],[27,13]
        ]
        
        # Secondary turret positions (build after primary complete)
        self.secondary_turrets = [[4,11],[5,11],[21,11],[22,11],[23,11],[24,11],[25,11], [12,11], [15,11], [9,11]]
        
        # Support positions (build after all turrets complete)
        self.support_positions = [[6,11],[7,11], [8,11], [9,11], [5,10],[6,10],[7,10],[8,10],[9,10]]
        # Attack positions and blocking turret logic
        self.scout_attack_position1 = [14,0]  # 3 scouts
        self.scout_attack_position2 = [12,1]  # 12 scouts
        #self.blocking_turret_position1 = [5,10]  # ADD during attack prep to funnel
        self.blocking_turret_position2 = [[1,12],[1,13],[2,12]]  # REMOVE during attack prep

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
        
        # Priority 1: Rebuild blocking turrets if needed (highest priority, only when not attacking)
        if not self.ready_for_scout_rush and not self.attack_path_cleared and not self.turret_removed_for_attack:
            self.rebuild_blocking_turrets_priority(game_state)
        
        # Priority 2: Check and replace damaged structures (below 50% health)
        self.replace_damaged_structures(game_state)
        
        # Priority 3: Ensure all primary turrets are built/replaced
        self.build_primary_turrets(game_state)
        
        # Priority 4: Build secondary turrets if primary is complete
        if self.primary_turrets_complete(game_state):
            self.build_secondary_turrets(game_state)
        
        # Priority 5: Build support structures if all turrets complete
        if self.all_turrets_complete(game_state):
            self.build_support_structures(game_state)
            
        # Priority 6: Upgrade structures when we have excess SP (prevent overflow)
        self.upgrade_structures(game_state)

    def rebuild_blocking_turrets_priority(self, game_state):
        """
        Rebuild blocking turrets with TOP PRIORITY when not in attack mode
        """
        turrets_rebuilt = 0
        
        # Rebuild all turrets in blocking_turret_position2 with highest priority
        for location in self.blocking_turret_position2:
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_rebuilt += 1
                    gamelib.debug_write('HIGH PRIORITY: Rebuilt blocking turret at {}'.format(location))
        
        if turrets_rebuilt > 0:
            gamelib.debug_write('HIGH PRIORITY REBUILD: {} blocking turrets restored'.format(turrets_rebuilt))

    def replace_damaged_structures(self, game_state):
        """
        Replace any turrets or supports below 50% health immediately
        """
        structures_replaced = 0
        
        # Check all turret positions (primary + secondary)
        all_turret_positions = self.primary_turrets + self.secondary_turrets
        for location in all_turret_positions:
            # Skip blocking turrets during attack preparation/execution
            if self.attack_path_cleared:
                #if location == self.blocking_turret_position1:  # Don't replace funnel turret during attack
                #    continue
                if location in self.blocking_turret_position2:  # Don't replace removed turrets during attack
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
            # Skip blocking turrets during attack preparation/execution
            if self.attack_path_cleared:
                #if location == self.blocking_turret_position1:  # Don't build funnel turret during attack
                #    continue
                if location in self.blocking_turret_position2:  # Don't build removed turrets during attack
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
        Upgrade structures starting from the side taking damage first, then closest to enemy
        """
        sp = int(game_state.get_resource(SP))  # Convert to integer to avoid float errors
        
        # Only upgrade if we have excess SP and all basic structures are built
        if self.all_turrets_complete(game_state):
            
            # Determine which side is under attack based on scored_on_locations
            left_side_damage = 0
            right_side_damage = 0
            
            for damage_location in self.scored_on_locations:
                if damage_location[0] < 14:  # Left side (closer to [0,13])
                    left_side_damage += 1
                else:  # Right side (closer to [27,13])
                    right_side_damage += 1
            
            # Determine priority side (left side prioritized if equal damage)
            priority_left_side = left_side_damage >= right_side_damage
            
            # Specific upgrade positions for each side
            left_side_upgrade_positions = [[2,13], [3,13],[15,11]]
            right_side_upgrade_positions = [[25,13], [24,13], [26,12], [12,11]]
            
            # Sort each side by Y coordinate (higher Y = closer to enemy)
            left_side_sorted = sorted(left_side_upgrade_positions, key=lambda pos: pos[1], reverse=True)
            right_side_sorted = sorted(right_side_upgrade_positions, key=lambda pos: pos[1], reverse=True)
            
            # Create priority order based on which side is taking damage
            if priority_left_side:
                sorted_positions = left_side_sorted + right_side_sorted
                gamelib.debug_write('Prioritizing LEFT SIDE upgrades (damage count: L={}, R={})'.format(left_side_damage, right_side_damage))
            else:
                sorted_positions = right_side_sorted + left_side_sorted
                gamelib.debug_write('Prioritizing RIGHT SIDE upgrades (damage count: L={}, R={})'.format(left_side_damage, right_side_damage))
            
            upgrades_made = 0
            for location in sorted_positions:
                # Skip if we don't have enough SP
                if sp < 5:
                    break
                    
                # Skip blocking turrets during attack preparation/execution
                if self.attack_path_cleared:
                    #if location == self.blocking_turret_position1:
                    #    continue
                    if location in self.blocking_turret_position2:
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
            # Skip checking blocking turrets during attack preparation/execution
            if self.attack_path_cleared:
                #if location == self.blocking_turret_position1:
                #    continue
                if location in self.blocking_turret_position2:
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
        Execute attack strategy: scout rush when ready
        """
        mp = int(game_state.get_resource(MP))  # Convert to integer to avoid float errors
        
        # Check if we're ready for scout rush (only when not in attack cycle)
        if mp >= 15 and not self.ready_for_scout_rush and not self.turret_removed_for_attack:
            self.ready_for_scout_rush = True
            gamelib.debug_write('Scout rush mode ACTIVATED - MP: {} (Starting new attack cycle)'.format(mp))
            
        if self.ready_for_scout_rush:
            # Execute scout rush sequence
            self.execute_scout_rush(game_state)

    def execute_scout_rush(self, game_state):
        """
        Execute the 3-phase scout rush with mandatory defense rebuilding
        """
        mp = int(game_state.get_resource(MP))  # Convert to integer to avoid float errors
        
        # Phase 1: Setup blocking turrets (MP >= 15, preparation turn)
        if mp >= 18 and not self.turret_removed_for_attack:
            # ADD funnel turret at blocking_turret_position1
            #if not game_state.contains_stationary_unit(self.blocking_turret_position1):
            #    if game_state.can_spawn(TURRET, self.blocking_turret_position1):
            #        game_state.attempt_spawn(TURRET, self.blocking_turret_position1)
            #        gamelib.debug_write('PHASE 1: Added funnel turret at {}'.format(self.blocking_turret_position1))
            
            # REMOVE all turrets in blocking_turret_position2
            turrets_removed = 0
            for location in self.blocking_turret_position2:
                if game_state.contains_stationary_unit(location):
                    game_state.attempt_remove([location])
                    turrets_removed += 1
                    gamelib.debug_write('PHASE 1: Removed blocking turret at {}'.format(location))
            
            # Set indicators - attack will happen NEXT turn
            self.turret_removed_for_attack = True
            self.attack_path_cleared = True
            gamelib.debug_write('PHASE 1: Attack preparation complete - scout attack NEXT turn (Removed: {})'.format(turrets_removed))
            
            # DO NOT deploy scouts this turn - return immediately
            return
        
        # Phase 2: Deploy scout attack AND remove funnel turret (attack turn)
        elif self.attack_path_cleared and self.turret_removed_for_attack:
            # Deploy scouts first
            available_mp = mp
            wave1_scouts = 18
            remaining_mp_after_wave1 = available_mp - wave1_scouts
            wave2_scouts = max(remaining_mp_after_wave1, 6)  # Ensure minimum 20 total (3 + 17)
            
            # Deploy Wave 1: 3 scouts at [13,0]
            actual_wave1 = game_state.attempt_spawn(SCOUT, self.scout_attack_position1, wave1_scouts)
            
            # Deploy Wave 2: Remaining scouts at [11,2] 
            actual_wave2 = game_state.attempt_spawn(SCOUT, self.scout_attack_position2, 0)
            
            total_deployed = actual_wave2
            
            # REMOVE the funnel turret at blocking_turret_position1 during attack
            #if game_state.contains_stationary_unit(self.blocking_turret_position1):
            #    game_state.attempt_remove([self.blocking_turret_position1])
             #   gamelib.debug_write('PHASE 2: Removed funnel turret at {} during attack'.format(self.blocking_turret_position1))
            
            gamelib.debug_write('PHASE 2: Attack executed - {} scouts at {}, {} scouts at {} (Total: {})'.format(
                actual_wave1, self.scout_attack_position1, actual_wave2, self.scout_attack_position2, total_deployed))
            
            # Set flag for mandatory rebuild next turn
            self.attack_path_cleared = False  # Attack is complete, prepare for rebuild
            gamelib.debug_write('PHASE 2: Attack complete, defenses will be rebuilt NEXT turn')
        
        # Phase 3: ALWAYS rebuild defenses (turn after attack)
        elif not self.attack_path_cleared and self.turret_removed_for_attack:
            # ALWAYS rebuild all turrets in blocking_turret_position2
            turrets_rebuilt = 0
            for location in self.blocking_turret_position2:
                if not game_state.contains_stationary_unit(location):
                    if game_state.can_spawn(TURRET, location):
                        game_state.attempt_spawn(TURRET, location)
                        turrets_rebuilt += 1
                        gamelib.debug_write('PHASE 3: Rebuilt blocking turret at {}'.format(location))
            
            # ALWAYS reset all attack mode indicators to normal defensive state
            self.turret_removed_for_attack = False
            self.ready_for_scout_rush = False
            
            gamelib.debug_write('PHASE 3: MANDATORY REBUILD complete - {} blocking turrets restored, all flags reset'.format(turrets_rebuilt))
            gamelib.debug_write('PHASE 3: Ready for next attack cycle when MP >= 15')

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