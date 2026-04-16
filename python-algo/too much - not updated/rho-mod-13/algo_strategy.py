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
        
        # Corner wall positions (replace turrets at [0,13] and [27,13])
        self.corner_walls = [[0,13], [27,13]]
        
        # Primary turret defense positions
        self.primary_turrets = [[1,12],[1,13],[2,12],[2,13],[3,13],[4,13],[5,13],[6,13],[7,13],[8,13],[9,13],[10,13],[11,13],[12,13],[13,13],[14,13],[15,13],[16,13],[17,13],[18,13],[19,13],[20,13],[21,13],[22,13],[23,13],[24,12],[24,13],[25,12],[25,13],[26,12],[26,13]]
        
        # Secondary turret positions (build after primary complete)
        self.secondary_turrets = []
        
        # Support positions (build after all turrets complete)
        self.support_positions = [[22,10],[21,10],[20,10],[19,10],[18,10],[17,10],[16,10]]
        # Attack positions and blocking turret logic
        self.scout_attack_position1 = [15,1]  # 3 scouts
        self.scout_attack_position2 = [13,0]  # 12 scouts
        # self.blocking_turret_position1 = [5,10]  # ADD during attack prep to funnel
        self.blocking_turret_position2 = [[25,12],[26,12],[26,13]]  # REMOVE during attack prep

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
        # Priority 0: Build and maintain corner walls (highest priority)
        self.build_and_maintain_corner_walls(game_state)
        
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

    def build_and_maintain_corner_walls(self, game_state):
        """
        Build and maintain corner walls at [0,13] and [27,13] with instant upgrades
        """
        for location in self.corner_walls:
            wall_needs_attention = False
            
            # Check if wall exists and its health
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0:  # Our unit
                        # Check if health is below 40%
                        if unit.health < (unit.max_health * 0.4):
                            wall_needs_attention = True
                            gamelib.debug_write('Corner wall at {} below 40% health ({}/{}), replacing...'.format(
                                location, unit.health, unit.max_health))
                            break
            else:
                # No wall exists, need to build one
                wall_needs_attention = True
                gamelib.debug_write('No corner wall at {}, building...'.format(location))
            
            # Replace/build and upgrade wall if needed
            if wall_needs_attention:
                # Remove existing unit if present
                if game_state.contains_stationary_unit(location):
                    game_state.attempt_remove([location])
                
                # Build new wall
                if game_state.can_spawn(WALL, location):
                    if game_state.attempt_spawn(WALL, location):
                        gamelib.debug_write('Built corner wall at {}'.format(location))
                        
                        # Instantly upgrade the wall
                        if game_state.attempt_upgrade([location]):
                            gamelib.debug_write('Instantly upgraded corner wall at {}'.format(location))
                        else:
                            gamelib.debug_write('Failed to upgrade corner wall at {} (insufficient SP)'.format(location))

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
                # if location == self.blocking_turret_position1:  # Don't replace funnel turret during attack
                #     continue
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
                # if location == self.blocking_turret_position1:  # Don't build funnel turret during attack
                #     continue
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
        Coherent upgrade priority system:
        1. First support at [22,10] - build and upgrade FIRST 
        2. Priority turrets [2,13], [25,13] - upgrade after first support is handled
        3. Remaining supports (handled in build_support_structures) - only after priority turrets upgraded
        4. Secondary turrets [3,12], [25,12] - only after all supports complete
        """
        sp = int(game_state.get_resource(SP))  # Convert to integer to avoid float errors
        
        # Only upgrade if we have excess SP and all basic structures are built
        if self.all_turrets_complete(game_state):
            upgrades_made = 0
            
            # STEP 1: Handle first support [22,10] FIRST - this gets priority over everything
            first_support_location = [22,10]
            if self.first_support_needs_upgrade(game_state):
                if sp >= 5 and game_state.contains_stationary_unit(first_support_location):
                    units_at_location = game_state.game_map[first_support_location]
                    for unit in units_at_location:
                        if unit.player_index == 0 and not unit.upgraded:
                            if game_state.attempt_upgrade([first_support_location]):
                                sp -= int(game_state.type_cost(unit.unit_type, upgrade=True)[0])
                                upgrades_made += 1
                                gamelib.debug_write('STEP 1: Upgraded first support at {} (SP remaining: {})'.format(
                                    first_support_location, sp))
                            break
            
            # STEP 2: Priority turrets [2,13], [25,13] - only after first support is handled
            if self.first_support_complete(game_state):
                priority_turret_positions = [[2,13], [25,13]]
                
                for location in priority_turret_positions:
                    if sp < 5:
                        break
                        
                    # Skip blocking turrets during attack preparation/execution
                    if self.attack_path_cleared and location in self.blocking_turret_position2:
                        continue
                    
                    if game_state.contains_stationary_unit(location):
                        units_at_location = game_state.game_map[location]
                        for unit in units_at_location:
                            if unit.player_index == 0 and not unit.upgraded:
                                if game_state.attempt_upgrade([location]):
                                    upgrades_made += 1
                                    sp -= int(game_state.type_cost(unit.unit_type, upgrade=True)[0])
                                    gamelib.debug_write('STEP 2: Upgraded priority turret at {} (SP remaining: {})'.format(
                                        location, sp))
                                    break
            
            # STEP 3: Support structures are handled in build_support_structures method
            # (They get built and upgraded one at a time, but only after priority turrets are upgraded)
            
            # STEP 4: Secondary turrets [3,12], [25,12] (only if all supports are placed and upgraded)
            if self.all_supports_upgraded(game_state):
                secondary_turret_positions = [[3,12], [25,12]]
                
                for location in secondary_turret_positions:
                    if sp < 5:
                        break
                        
                    # Skip blocking turrets during attack preparation/execution
                    if self.attack_path_cleared and location in self.blocking_turret_position2:
                        continue
                    
                    if game_state.contains_stationary_unit(location):
                        units_at_location = game_state.game_map[location]
                        for unit in units_at_location:
                            if unit.player_index == 0 and not unit.upgraded:
                                if game_state.attempt_upgrade([location]):
                                    upgrades_made += 1
                                    sp -= int(game_state.type_cost(unit.unit_type, upgrade=True)[0])
                                    gamelib.debug_write('STEP 4: Upgraded secondary turret at {} (SP remaining: {})'.format(
                                        location, sp))
                                    break
            
            if upgrades_made > 0:
                gamelib.debug_write('Completed {} upgrades this turn'.format(upgrades_made))

    def build_support_structures(self, game_state):
        """
        Build support structures with coherent priority system:
        1. First support [22,10] gets built immediately (no restrictions)
        2. Remaining supports only built after priority turrets [2,13], [25,13] are upgraded
        3. Each support gets upgraded immediately after building
        """
        supports_built = 0
        supports_upgraded = 0
        
        first_support_location = [22,10]
        
        # CASE 1: First support doesn't exist - build it immediately (highest priority)
        if not game_state.contains_stationary_unit(first_support_location):
            if game_state.can_spawn(SUPPORT, first_support_location):
                if game_state.attempt_spawn(SUPPORT, first_support_location):
                    supports_built += 1
                    gamelib.debug_write('Built FIRST support at {} (position 0)'.format(first_support_location))
                    
                    # Immediately upgrade the first support we just built
                    if game_state.attempt_upgrade([first_support_location]):
                        supports_upgraded += 1
                        gamelib.debug_write('Immediately upgraded FIRST support at {}'.format(first_support_location))
                    else:
                        gamelib.debug_write('Failed to upgrade FIRST support at {} (insufficient SP)'.format(first_support_location))
            # Exit after handling first support
            if supports_built > 0 or supports_upgraded > 0:
                gamelib.debug_write('First support progress: built {}, upgraded {}'.format(supports_built, supports_upgraded))
            return
        
        # CASE 2: First support exists but not upgraded - upgrade it first
        if self.first_support_needs_upgrade(game_state):
            units_at_location = game_state.game_map[first_support_location]
            for unit in units_at_location:
                if unit.player_index == 0 and not unit.upgraded:
                    if game_state.attempt_upgrade([first_support_location]):
                        supports_upgraded += 1
                        gamelib.debug_write('Upgraded existing FIRST support at {}'.format(first_support_location))
                    else:
                        gamelib.debug_write('Failed to upgrade existing FIRST support at {} (insufficient SP)'.format(first_support_location))
                    break
            # Exit after handling first support
            if supports_upgraded > 0:
                gamelib.debug_write('First support upgrade progress: upgraded {}'.format(supports_upgraded))
            return
        
        # CASE 3: First support is complete, now check priority turrets before building remaining supports
        if not self.priority_turrets_upgraded(game_state):
            gamelib.debug_write('First support complete, but priority turrets not upgraded - pausing remaining support building')
            return
        
        # CASE 4: First support complete AND priority turrets upgraded - build remaining supports
        remaining_support_positions = self.support_positions[1:]  # Skip first support [22,10]
        
        # Find the first remaining support position that either doesn't exist or exists but isn't upgraded
        for i, location in enumerate(remaining_support_positions):
            actual_position = i + 1  # Since we skipped position 0
            
            if not game_state.contains_stationary_unit(location):
                # No support exists, build it
                if game_state.can_spawn(SUPPORT, location):
                    if game_state.attempt_spawn(SUPPORT, location):
                        supports_built += 1
                        gamelib.debug_write('Built remaining support at {} (position {})'.format(location, actual_position))
                        
                        # Immediately upgrade the support we just built
                        if game_state.attempt_upgrade([location]):
                            supports_upgraded += 1
                            gamelib.debug_write('Immediately upgraded remaining support at {}'.format(location))
                        else:
                            gamelib.debug_write('Failed to upgrade remaining support at {} (insufficient SP)'.format(location))
                # Only build one support per turn, exit after building
                break
            else:
                # Support exists, check if it's upgraded
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0:  # Our unit
                        if not unit.upgraded:
                            # Support exists but not upgraded, try to upgrade it
                            if game_state.attempt_upgrade([location]):
                                supports_upgraded += 1
                                gamelib.debug_write('Upgraded existing remaining support at {} (position {})'.format(location, actual_position))
                            else:
                                gamelib.debug_write('Failed to upgrade existing remaining support at {} (insufficient SP)'.format(location))
                            # Exit after handling this unupgraded support
                            break
                        else:
                            # This support is already upgraded, continue to next position
                            continue
                # If we reach here and the support was not upgraded, we handled it above and should exit
                # If it was upgraded, we continue to the next position
                if game_state.contains_stationary_unit(location):
                    units_at_location = game_state.game_map[location]
                    for unit in units_at_location:
                        if unit.player_index == 0 and not unit.upgraded:
                            # We handled this case above, exit
                            break
                    else:
                        # Support is upgraded, continue to next position
                        continue
                    break
        
        if supports_built > 0 or supports_upgraded > 0:
            gamelib.debug_write('Remaining support progress: built {}, upgraded {}'.format(supports_built, supports_upgraded))

    def first_support_complete(self, game_state):
        """Check if first support [22,10] is built and upgraded"""
        first_support_location = [22,10]
        
        if not game_state.contains_stationary_unit(first_support_location):
            return False  # First support not even built
        
        units_at_location = game_state.game_map[first_support_location]
        for unit in units_at_location:
            if unit.player_index == 0:
                return unit.upgraded  # Return whether it's upgraded
        
        return False

    def first_support_needs_upgrade(self, game_state):
        """Check if first support [22,10] exists but needs upgrade"""
        first_support_location = [22,10]
        
        if not game_state.contains_stationary_unit(first_support_location):
            return False  # First support doesn't exist
        
        units_at_location = game_state.game_map[first_support_location]
        for unit in units_at_location:
            if unit.player_index == 0:
                return not unit.upgraded  # Return whether it needs upgrade
        
        return False

    def priority_turrets_upgraded(self, game_state):
        """Check if priority turrets [2,13], [25,13] are upgraded"""
        priority_turret_positions = [[2,13], [25,13]]
        
        for location in priority_turret_positions:
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0 and not unit.upgraded:
                        return False  # Priority turret exists but not upgraded
            # If turret doesn't exist, we consider it "not ready" for continuing with supports
            else:
                return False
        
        return True  # All priority turrets are built and upgraded

    def all_supports_upgraded(self, game_state):
        """Check if all support structures are placed and upgraded"""
        for location in self.support_positions:
            if not game_state.contains_stationary_unit(location):
                return False  # Support not even built yet
            
            units_at_location = game_state.game_map[location]
            for unit in units_at_location:
                if unit.player_index == 0 and not unit.upgraded:
                    return False  # Support exists but not upgraded
        
        return True  # All supports are built and upgraded

    def primary_turrets_complete(self, game_state):
        """Check if all primary turrets are built"""
        for location in self.primary_turrets:
            # Skip checking blocking turrets during attack preparation/execution
            if self.attack_path_cleared:
                # if location == self.blocking_turret_position1:
                #     continue
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
        if mp >= 16 and not self.ready_for_scout_rush and not self.turret_removed_for_attack:
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
        if mp >= 16 and not self.turret_removed_for_attack:
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
            wave1_scouts = 5
            remaining_mp_after_wave1 = available_mp - wave1_scouts
            wave2_scouts = max(remaining_mp_after_wave1, 13)  # Ensure minimum 20 total (3 + 17)
            
            # Deploy Wave 1: 3 scouts at [13,0]
            actual_wave1 = game_state.attempt_spawn(SCOUT, self.scout_attack_position1, wave1_scouts)
            
            # Deploy Wave 2: Remaining scouts at [11,2] 
            actual_wave2 = game_state.attempt_spawn(SCOUT, self.scout_attack_position2, wave2_scouts)
            
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