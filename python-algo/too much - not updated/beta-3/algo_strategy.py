import gamelib
import random
import math
import warnings
from sys import maxsize
import json


"""
Turret Defense + Upgrade-Based Dynamic Scout Rush Strategy:
1. Build comprehensive turret defense network
2. UPGRADE-BASED DYNAMIC ATTACK DIRECTION ANALYSIS each turn:
   - Analyzes ALL three directions (CENTER/LEFT/RIGHT) for upgraded turret counts
   - PRIORITY: Always attack area with FEWEST UPGRADED TURRETS
   - CENTER: Analyzes columns 7-19 for upgraded turrets + weak column count (>8 weak = viable)
   - LEFT vs RIGHT: Analyzes [1-3,14-15] vs [24-26,14-15] for upgraded turrets
   - Tiebreaker: If equal upgraded turrets, attack area with fewer total turrets
   - Attack positions adapt: CENTER([6,7]+[19,5]), LEFT([12,1]+[14,0]), RIGHT([16,2]+[13,0])
3. 3-Phase Attack System with Blocking Turret Protection:
   - Phase 1: REMOVE turrets at dynamic blocking positions (MP >= escalating threshold)
   - Phase 2: Deploy scouts with PROTECTED PATH (no defensive rebuilding during scout deployment)
   - Phase 3: ALWAYS rebuild all blocking turrets and reset all flags (next turn)
4. MODIFIED ESCALATING ATTACK WAVES: 
   - MP threshold increases by +2 after each completed attack cycle (13→15→17→19...)
   - Wave 1 size: 5 scouts for first attack, then 7 scouts forever (no further increase)
   - Wave 2 uses ALL remaining MP for maximum impact
   - Attack direction dynamically chosen each cycle based on UPGRADED TURRET analysis
5. Hard reset to normal defensive state before each new attack cycle
6. DAMAGE-BASED TURRET UPGRADE SYSTEM:
   - Analyzes recent damage locations to prioritize turret upgrades
   - Left damage: Prioritizes turrets with x-coordinate 0-5
   - Right damage: Prioritizes turrets with x-coordinate 23-27
   - Middle damage: Prioritizes specific middle turrets in order
7. REAL-TIME SINGLE WAVE ATTACK OPTIMIZATION:
   - REAL-TIME analysis during Phase 2 checks current upgraded turrets in target area
   - ONLY when target zone has 0 upgraded turrets: combines waves into single massive push
   - Wave 1: 0 scouts, Wave 2: ALL available MP for maximum breakthrough potential
"""

class AlgoStrategy(gamelib.AlgoCore):
    def __init__(self):
        super().__init__()
        seed = random.randrange(maxsize)
        random.seed(seed)
        gamelib.debug_write('Random seed: {}'.format(seed))
        
        # Initialize dynamic attack system variables early
        self.current_attack_direction = "left"  # Default attack direction
        self.scout_attack_position1 = [12,1]  # Default positions
        self.scout_attack_position2 = [14,0]
        self.blocking_turret_position2 = [[1,13],[1,12],[2,12]]

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
        self.primary_turrets = [[1,12],[1,13],[2,12],[2,13],[3,12],[3,13],[4,13],[5,13],[6,13],[7,13],[8,13],[9,13],[10,13],[11,13],[12,13],[13,13],[14,13],[15,13],[16,13],[17,13],[18,13],[19,13],[20,13],[21,13],[22,13],[23,13],[24,12],[24,13],[25,12],[25,13],[26,12],[26,13]]
        # Secondary turret positions (build after primary complete)
        self.secondary_turrets = [[9,12], [13,12], [15,12], [5,12], [16,12],[18,12], [11,12],[20,12],[22,12]]
        
        # Support positions (build after all turrets complete)
        self.support_positions = [[8,12],[10,12],[6,12],[17,12],[19,12]]
        
        self.tertiary_turrets = [[12,11], [14,11], [8,11], [17,11], [19,11], [21,11]]
        # Attack positions and blocking turret logic
        self.scout_attack_position1 = [12,1] 
        self.scout_attack_position2 = [14,0] 
        self.blocking_turret_position2 = [[1,13],[1,12],[2,12]]  # REMOVE during attack prep
        
        # MODIFIED ESCALATING ATTACK WAVE SYSTEM - Wave 1 caps at 7 scouts
        self.min_attack_mp = 15  # Starting threshold for first attack (Attack 1: MP>=13)
        self.attack_cycles_completed = 0  # Track number of completed attack cycles
        
        # SINGLE WAVE ATTACK SYSTEM - Track if target area has 0 upgraded turrets
        self.target_area_upgraded_turrets = 1  # Default to 1 to use normal dual-wave attack
        
        gamelib.debug_write('TURRET-ONLY UPGRADE-BASED DYNAMIC ATTACK SYSTEM INITIALIZED: Prioritizes areas with fewest upgraded TURRETS (ignores supports)')

    def on_turn(self, turn_state):
        """
        Main strategy execution
        """
        game_state = gamelib.GameState(self.config, turn_state)
        gamelib.debug_write('Turn {} - Upgrade-Based Dynamic Defense Strategy (Attack threshold: MP>={}, Direction: {}, Wave 1: {} scouts)'.format(
            game_state.turn_number, self.min_attack_mp, 
            getattr(self, 'current_attack_direction', 'left').upper(), 
            5 if self.attack_cycles_completed == 0 else 7))
        game_state.suppress_warnings(True)

        # Execute defensive strategy
        self.execute_defensive_strategy(game_state)
        
        # Execute attack strategy 
        self.execute_attack_strategy(game_state)

        game_state.submit_turn()

    def execute_defensive_strategy(self, game_state):
        """
        NEW PRIORITY SYSTEM - Fixed defensive strategy execution
        """
        # DYNAMIC ATTACK ANALYSIS: Only decide attack direction when NOT in active attack cycle
        # This prevents changing attack direction mid-cycle and ensures proper blocking turret removal
        if not self.ready_for_scout_rush and not self.turret_removed_for_attack and not self.attack_path_cleared:
            self.analyze_enemy_and_set_attack_direction(game_state)
            gamelib.debug_write('🎯 TURRET-ONLY ANALYSIS: Updated attack direction to {} (not in active attack cycle)'.format(self.current_attack_direction.upper()))
        else:
            phase_status = []
            if self.ready_for_scout_rush: phase_status.append("READY")
            if self.turret_removed_for_attack: phase_status.append("TURRETS_REMOVED")
            if self.attack_path_cleared: phase_status.append("PATH_CLEARED")
            gamelib.debug_write('🎯 TURRET-ONLY ANALYSIS: Skipped (Active: {}) - maintaining {} direction, blocking protection ACTIVE'.format(
                "+".join(phase_status), self.current_attack_direction.upper()))
        
        # Always maintain corner walls first
        self.build_and_maintain_corner_walls(game_state)
        
        # STEP 1: Ensure all primary and secondary turrets are built
        self.build_primary_and_secondary_turrets(game_state)
        
        # STEP 2: Mark damaged turrets for removal (below 30% health)
        self.mark_damaged_turrets_for_removal(game_state)
        
        # STEP 3: Build all support structures (build one, upgrade immediately, then next)
        self.build_support_structures_sequential(game_state)
        
        # STEP 4: Only after all supports are built, upgrade remaining turrets
        if self.all_supports_built_and_upgraded(game_state):
            self.upgrade_turrets_by_priority(game_state)
            
        # STEP 5: Build tertiary turrets only after everything else is complete
        if self.all_primary_systems_complete(game_state):
            self.build_tertiary_turrets(game_state)
        else:
            gamelib.debug_write('STEP 5 SKIPPED: Primary systems not complete yet (need all turrets built+upgraded, all supports built+upgraded)')

    def analyze_enemy_and_set_attack_direction(self, game_state):
        """
        ENHANCED TURRET-ONLY DYNAMIC ATTACK STRATEGY: Analyze enemy TURRET defenses and prioritize by UPGRADED TURRETS ONLY
        Priority: Attack area with FEWEST UPGRADED TURRETS (ignores supports, walls, and other structures)
        """
        try:
            # Analyze all three attack directions for upgraded turrets
            middle_analysis = self.should_attack_middle(game_state)
            left_side_analysis = self.analyze_side_defenses(game_state, "left")
            right_side_analysis = self.analyze_side_defenses(game_state, "right")
            
            # Create comprehensive comparison
            attack_options = {
                'middle': {
                    'upgraded_turrets': middle_analysis['upgraded_turrets'],
                    'total_turrets': middle_analysis['total_turrets'],
                    'viable': middle_analysis['viable'],
                    'name': 'CENTER'
                },
                'left': {
                    'upgraded_turrets': left_side_analysis['upgraded_turrets'],
                    'total_turrets': left_side_analysis['total_turrets'],
                    'viable': True,  # Always viable
                    'name': 'LEFT'
                },
                'right': {
                    'upgraded_turrets': right_side_analysis['upgraded_turrets'], 
                    'total_turrets': right_side_analysis['total_turrets'],
                    'viable': True,  # Always viable
                    'name': 'RIGHT'
                }
            }
            
            gamelib.debug_write('🎯 TURRET-ONLY UPGRADE ANALYSIS:')
            gamelib.debug_write('CENTER: {}U/{}T TURRETS (Viable: {}, Weak Columns: {}/13)'.format(
                middle_analysis['upgraded_turrets'], middle_analysis['total_turrets'], 
                middle_analysis['viable'], middle_analysis['weak_columns']))
            gamelib.debug_write('LEFT: {}U/{}T TURRETS | RIGHT: {}U/{}T TURRETS'.format(
                left_side_analysis['upgraded_turrets'], left_side_analysis['total_turrets'],
                right_side_analysis['upgraded_turrets'], right_side_analysis['total_turrets']))
            
            # Find the attack option with FEWEST UPGRADED TURRETS
            best_option = self.choose_attack_by_upgrades(attack_options)
            
            if best_option == 'middle':
                self.set_center_attack_configuration()
                self.target_area_upgraded_turrets = middle_analysis['upgraded_turrets']
                gamelib.debug_write('🎯 TURRET PRIORITY: CENTER attack selected (Fewest upgraded TURRETS: {}U vs L:{}U R:{}U)'.format(
                    middle_analysis['upgraded_turrets'], left_side_analysis['upgraded_turrets'], right_side_analysis['upgraded_turrets']))
            elif best_option == 'left':
                self.set_left_attack_configuration()
                self.target_area_upgraded_turrets = left_side_analysis['upgraded_turrets']
                gamelib.debug_write('🎯 TURRET PRIORITY: LEFT attack selected (Fewest upgraded TURRETS: {}U vs C:{}U R:{}U)'.format(
                    left_side_analysis['upgraded_turrets'], middle_analysis['upgraded_turrets'], right_side_analysis['upgraded_turrets']))
            else:  # right
                self.set_right_attack_configuration()
                self.target_area_upgraded_turrets = right_side_analysis['upgraded_turrets']
                gamelib.debug_write('🎯 TURRET PRIORITY: RIGHT attack selected (Fewest upgraded TURRETS: {}U vs C:{}U L:{}U)'.format(
                    right_side_analysis['upgraded_turrets'], middle_analysis['upgraded_turrets'], left_side_analysis['upgraded_turrets']))
                    
        except Exception as e:
            # Fallback to left attack if analysis fails
            gamelib.debug_write('ERROR in turret-only upgrade analysis, defaulting to LEFT attack: {}'.format(str(e)))
            self.set_left_attack_configuration()
            self.target_area_upgraded_turrets = 1  # Default to 1 to use normal dual-wave attack

    def choose_attack_by_upgrades(self, attack_options):
        """
        Choose attack direction prioritizing FEWEST UPGRADED TURRETS ONLY (ignores supports)
        Returns: 'middle', 'left', or 'right'
        """
        # Filter to only viable options
        viable_options = {k: v for k, v in attack_options.items() if v['viable']}
        
        if not viable_options:
            gamelib.debug_write('No viable options, defaulting to LEFT')
            return 'left'
        
        # Sort by upgraded turrets (ascending), then by total turrets (ascending)
        sorted_options = sorted(viable_options.items(), 
                              key=lambda x: (x[1]['upgraded_turrets'], x[1]['total_turrets']))
        
        best_option = sorted_options[0][0]
        best_stats = sorted_options[0][1]
        
        gamelib.debug_write('TURRET PRIORITY LOGIC: {} chosen ({}U/{}T TURRETS) - fewest upgraded turrets'.format(
            best_stats['name'], best_stats['upgraded_turrets'], best_stats['total_turrets']))
        
        return best_option
    def get_real_time_upgraded_turrets_in_target_area(self, game_state):
        """
        REAL-TIME ANALYSIS: Get current upgraded turret count in the target attack area
        This is called during Phase 2 to ensure we have the most up-to-date information
        """
        try:
            if self.current_attack_direction == "center":
                # Analyze center area (columns 7-19)
                analysis = self.should_attack_middle(game_state)
                return analysis['upgraded_turrets']
            elif self.current_attack_direction == "left":
                # Analyze left side area
                analysis = self.analyze_side_defenses(game_state, "left")
                return analysis['upgraded_turrets']
            elif self.current_attack_direction == "right":
                # Analyze right side area
                analysis = self.analyze_side_defenses(game_state, "right")
                return analysis['upgraded_turrets']
            else:
                # Fallback to left analysis if direction is unknown
                gamelib.debug_write('Unknown attack direction {}, defaulting to left analysis'.format(self.current_attack_direction))
                analysis = self.analyze_side_defenses(game_state, "left")
                return analysis['upgraded_turrets']
        except Exception as e:
            gamelib.debug_write('Error in real-time upgraded turret analysis: {}'.format(str(e)))
            return 1  # Default to 1 to use dual-wave attack if analysis fails

    def should_attack_middle(self, game_state):
        """
        Check if we should attack down the middle by analyzing columns 7-19
        Returns dict with analysis: weak_columns, total_turrets, upgraded_turrets
        Attack middle only if: >8 weak columns AND fewer upgraded TURRETS than sides
        CRITICAL: Only counts TURRETS, not supports or other structures
        """
        columns_to_check = list(range(7, 20))  # Columns 7,8,9,10,11,12,13,14,15,16,17,18,19
        weak_columns = 0
        total_turrets = 0
        upgraded_turrets = 0
        
        for col in columns_to_check:
            column_turret_count = 0
            # Check positions [col,14] to [col,18] for enemy turrets
            for row in range(14, 19):
                location = [col, row]
                try:
                    if game_state.contains_stationary_unit(location):
                        units_at_location = game_state.game_map[location]
                        if units_at_location:  # Make sure list is not empty
                            for unit in units_at_location:
                                if (hasattr(unit, 'player_index') and unit.player_index == 1 and  # Enemy unit
                                    hasattr(unit, 'unit_type') and unit.unit_type == TURRET):  # ONLY TURRETS
                                    column_turret_count += 1
                                    total_turrets += 1
                                    if hasattr(unit, 'upgraded') and unit.upgraded:
                                        upgraded_turrets += 1
                                    break
                except Exception as e:
                    gamelib.debug_write('Error analyzing middle column {} row {}: {}'.format(col, row, str(e)))
                    continue
            
            # Column is weak if it has only 1 turret or less
            if column_turret_count <= 1:
                weak_columns += 1
                
        gamelib.debug_write('MIDDLE ANALYSIS: {}/13 columns weak, {} total turrets, {} upgraded TURRETS (ignoring supports)'.format(
            weak_columns, total_turrets, upgraded_turrets))
        
        return {
            'weak_columns': weak_columns,
            'total_turrets': total_turrets,
            'upgraded_turrets': upgraded_turrets,  # ONLY turrets
            'viable': weak_columns > 8  # Basic viability check
        }

    def analyze_side_defenses(self, game_state, side):
        """
        Analyze left or right side defenses
        Returns dict with total_turrets and upgraded_turrets counts
        CRITICAL: Only counts TURRETS, not supports or other structures
        """
        if side == "left":
            positions_to_check = [[1,14], [2,14], [3,14], [1,15], [2,15], [3,15]]
        else:  # right
            positions_to_check = [[24,14], [25,14], [26,14], [24,15], [25,15], [26,15]]
        
        total_turrets = 0
        upgraded_turrets = 0
        
        for location in positions_to_check:
            try:
                if game_state.contains_stationary_unit(location):
                    units_at_location = game_state.game_map[location]
                    if units_at_location:  # Make sure list is not empty
                        for unit in units_at_location:
                            if (hasattr(unit, 'player_index') and unit.player_index == 1 and  # Enemy unit
                                hasattr(unit, 'unit_type') and unit.unit_type == TURRET):  # ONLY TURRETS
                                total_turrets += 1
                                if hasattr(unit, 'upgraded') and unit.upgraded:
                                    upgraded_turrets += 1
                                break
            except Exception as e:
                gamelib.debug_write('Error analyzing {} position {}: {}'.format(side, location, str(e)))
                continue
        
        gamelib.debug_write('{} ANALYSIS: {} total turrets, {} upgraded TURRETS (ignoring supports)'.format(
            side.upper(), total_turrets, upgraded_turrets))
        
        return {
            'total_turrets': total_turrets,
            'upgraded_turrets': upgraded_turrets  # ONLY turrets
        }

    def should_attack_left_side(self, left_analysis, right_analysis):
        """
        Decide whether to attack left side based on comparison
        Attack the side with fewer upgraded turrets (or fewer total if tied on upgrades)
        Default to left if completely tied
        """
        left_upgraded = left_analysis['upgraded_turrets']
        right_upgraded = right_analysis['upgraded_turrets']
        left_total = left_analysis['total_turrets']
        right_total = right_analysis['total_turrets']
        
        # If right has more upgraded turrets, attack left
        if right_upgraded > left_upgraded:
            return True
        # If left has more upgraded turrets, attack right
        elif left_upgraded > right_upgraded:
            return False
        # If tied on upgraded turrets, compare total turrets
        else:
            # If right has more total turrets, attack left
            if right_total > left_total:
                return True
            # If left has more total turrets, attack right
            elif left_total > right_total:
                return False
            # If completely tied, default to left
            else:
                return True

    def set_center_attack_configuration(self):
        """Set attack positions for center attack"""
        self.scout_attack_position1 = [6, 7]
        self.scout_attack_position2 = [19, 5]
        self.blocking_turret_position2 = [[13, 13],[13,12]]  # Single position for center
        self.current_attack_direction = "center"

    def set_left_attack_configuration(self):
        """Set attack positions for left side attack"""
        self.scout_attack_position1 = [12, 1]
        self.scout_attack_position2 = [14, 0]
        self.blocking_turret_position2 = [[1,13], [1,12], [2,12]]
        self.current_attack_direction = "left"

    def set_right_attack_configuration(self):
        """Set attack positions for right side attack"""
        self.scout_attack_position1 = [16, 2]
        self.scout_attack_position2 = [13, 0]
        self.blocking_turret_position2 = [[25,12], [26,12], [26,13]]  # Note: still same blocking positions
        self.current_attack_direction = "right"

    def build_and_maintain_corner_walls(self, game_state):
        """
        Build and maintain corner walls at [0,13] and [27,13] with instant upgrades
        """
        for location in self.corner_walls:
            wall_needs_attention = False
            if self.attack_path_cleared and location in self.blocking_turret_position2:
                continue
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
                        game_state.attempt_upgrade([location])

    def build_primary_and_secondary_turrets(self, game_state):
        """
        STEP 1: Build all primary and secondary turrets (including any removed for attacks)
        CRITICAL: Never rebuild blocking turrets during Phase 2 (active scout deployment)
        """
        turrets_built = 0
        
        # Build primary turrets first - ALWAYS build all primary positions
        for location in self.primary_turrets:
            # CRITICAL FIX: Skip blocking turrets during Phase 2 (active scout deployment)
            # This prevents rebuilding turrets that would trap our scouts
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                gamelib.debug_write('STEP 1: SKIPPING blocking turret at {} during Phase 2 (scouts deploying)'.format(location))
                continue
                
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_built += 1
                    gamelib.debug_write('STEP 1: Built primary turret at {} (defensive priority)'.format(location))
        
        # Build secondary turrets after primary
        for location in self.secondary_turrets:
            # Also check secondary turrets for blocking positions (safety)
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                gamelib.debug_write('STEP 1: SKIPPING secondary blocking turret at {} during Phase 2'.format(location))
                continue
                
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_built += 1
                    gamelib.debug_write('STEP 1: Built secondary turret at {}'.format(location))
        
        if turrets_built > 0:
            gamelib.debug_write('STEP 1 COMPLETE: Built {} turrets (Phase 2 blocking skip active: {})'.format(
                turrets_built, self.attack_path_cleared and self.turret_removed_for_attack))

    def mark_damaged_turrets_for_removal(self, game_state):
        """
        STEP 2: Mark turrets below 50% health for removal (they will be rebuilt in STEP 1 next turn)
        CRITICAL: Never remove blocking turrets during Phase 2 (active scout deployment)
        """
        turrets_marked = 0
        all_turret_positions = self.primary_turrets + self.secondary_turrets + self.tertiary_turrets
        
        for location in all_turret_positions:
            # CRITICAL FIX: Skip blocking turrets during Phase 2 (active scout deployment)
            # This prevents removing/rebuilding turrets that would trap our scouts
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                gamelib.debug_write('STEP 2: SKIPPING damage check on blocking turret at {} during Phase 2'.format(location))
                continue
                
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0 and unit.health < (unit.max_health * 0.5):
                        # Mark for removal - it will be rebuilt next turn in STEP 1
                        game_state.attempt_remove([location])
                        turrets_marked += 1
                        gamelib.debug_write('STEP 2: Marked damaged turret at {} for removal (Health: {}/{})'.format(
                            location, unit.health, unit.max_health))
                        break
        
        if turrets_marked > 0:
            gamelib.debug_write('STEP 2 COMPLETE: Marked {} damaged turrets for removal (Phase 2 blocking skip active: {})'.format(
                turrets_marked, self.attack_path_cleared and self.turret_removed_for_attack))

    def build_support_structures_sequential(self, game_state):
        """
        STEP 3: Build support structures one by one, upgrading each immediately after building
        """
        # Only proceed if all turrets are built
        if not self.all_turrets_built(game_state):
            gamelib.debug_write('STEP 3 SKIPPED: Not all turrets built yet')
            return
        
        supports_built = 0
        supports_upgraded = 0
        
        # Find the first support position that needs building or upgrading
        for i, location in enumerate(self.support_positions):
            if not game_state.contains_stationary_unit(location):
                # No support exists, build it
                if game_state.can_spawn(SUPPORT, location):
                    if game_state.attempt_spawn(SUPPORT, location):
                        supports_built += 1
                        gamelib.debug_write('STEP 3: Built support at {} (position {})'.format(location, i))
                        
                        # Immediately try to upgrade it
                        if game_state.get_resource(SP) >= 5:  # Cost to upgrade support
                            if game_state.attempt_upgrade([location]):
                                supports_upgraded += 1
                                gamelib.debug_write('STEP 3: Immediately upgraded support at {}'.format(location))
                            else:
                                gamelib.debug_write('STEP 3: Built support at {} but could not upgrade (insufficient SP)'.format(location))
                        else:
                            gamelib.debug_write('STEP 3: Built support at {} but need more SP to upgrade next turn'.format(location))
                        
                        # Only build one support per turn, exit
                        break
                else:
                    gamelib.debug_write('STEP 3: Cannot afford to build support at {}'.format(location))
                    break
            else:
                # Support exists, check if it needs upgrading
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0:  # Our unit
                        if not unit.upgraded:
                            # Support exists but not upgraded, try to upgrade it
                            if game_state.get_resource(SP) >= 5:
                                if game_state.attempt_upgrade([location]):
                                    supports_upgraded += 1
                                    gamelib.debug_write('STEP 3: Upgraded existing support at {} (position {})'.format(location, i))
                                else:
                                    gamelib.debug_write('STEP 3: Failed to upgrade support at {} (insufficient SP)'.format(location))
                            else:
                                gamelib.debug_write('STEP 3: Support at {} needs upgrading but insufficient SP'.format(location))
                            # Exit after handling this unupgraded support
                            break
                        else:
                            # This support is already upgraded, continue to next position
                            continue
                # Check if we handled an unupgraded support and should exit
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
            gamelib.debug_write('STEP 3 COMPLETE: Built {} supports, upgraded {} supports'.format(supports_built, supports_upgraded))

    def upgrade_turrets_by_priority(self, game_state):
        """
        STEP 4: Upgrade turrets by priority based on where we're taking damage
        """
        sp = int(game_state.get_resource(SP))
        initial_sp = sp
        upgrades_made = 0
        
        # Complete priority list of upgradable turrets
        all_priority_turrets = [[2,13], [3,13], [3,12],[2,12],[25,13],[24,13], [24,12],[25,12], [15,12], [9,12], [18,12], [22,12], [5,12], [13,12]]
        
        # Analyze recent damage to determine priority area
        priority_order = self.determine_upgrade_priority_based_on_damage(all_priority_turrets)
        
        # Upgrade turrets in determined priority order
        for location in priority_order:
            if sp < 5:  # Not enough SP for upgrades
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
                            sp -= 5  # Assume upgrade cost is 5
                            gamelib.debug_write('STEP 4: Upgraded turret at {} (damage-based priority, SP remaining: {})'.format(
                                location, sp))
                            break
        
        # Upgrade remaining primary turrets not in priority list
        remaining_turrets = [loc for loc in self.primary_turrets if loc not in all_priority_turrets]
        for location in remaining_turrets:
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
                            sp -= 5
                            gamelib.debug_write('STEP 4: Upgraded remaining primary turret at {} (SP remaining: {})'.format(
                                location, sp))
                            break
        
        # Upgrade secondary turrets last
        for location in self.secondary_turrets:
            if sp < 5:
                break
            
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0 and not unit.upgraded:
                        if game_state.attempt_upgrade([location]):
                            upgrades_made += 1
                            sp -= 5
                            gamelib.debug_write('STEP 4: Upgraded secondary turret at {} (SP remaining: {})'.format(
                                location, sp))
                            break
        
        # Upgrade tertiary turrets after secondary (if they exist)
        for location in self.tertiary_turrets:
            if sp < 5:
                break
            
            # CRITICAL FIX: Skip blocking turrets during Phase 2 (active scout deployment)
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                gamelib.debug_write('STEP 4: SKIPPING upgrade of tertiary blocking turret at {} during Phase 2'.format(location))
                continue
            
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0 and not unit.upgraded:
                        if game_state.attempt_upgrade([location]):
                            upgrades_made += 1
                            sp -= 5
                            gamelib.debug_write('STEP 4: Upgraded tertiary turret at {} (SP remaining: {})'.format(
                                location, sp))
                            break
        
        if upgrades_made > 0:
            gamelib.debug_write('STEP 4 COMPLETE: Upgraded {} turrets (SP spent: {})'.format(
                upgrades_made, initial_sp - sp))

    def determine_upgrade_priority_based_on_damage(self, all_priority_turrets):
        """
        Analyze recent damage locations and determine turret upgrade priority order
        Based on damage patterns:
        - Left area damage ([0,13], [1,12], [2,11]): Priority turrets with x-coordinate 0-5
        - Right area damage ([27,13], [26,12], [25,11]): Priority turrets with x-coordinate 23-27  
        - Middle area damage (anywhere else): Specific order [15,12], [9,12], [18,12], [22,12], [5,12], [13,12]
        """
        # Define damage area detection zones
        left_damage_zones = [[0,13], [1,12], [2,11]]
        right_damage_zones = [[27,13], [26,12], [25,11]]
        
        # Count recent damage in each area (last 5 damage events for responsiveness)
        recent_damage = self.scored_on_locations[-5:] if len(self.scored_on_locations) > 5 else self.scored_on_locations
        
        left_damage_count = sum(1 for loc in recent_damage if loc in left_damage_zones)
        right_damage_count = sum(1 for loc in recent_damage if loc in right_damage_zones)
        middle_damage_count = len(recent_damage) - left_damage_count - right_damage_count
        
        # Determine which area has taken the most damage
        if left_damage_count > right_damage_count and left_damage_count > middle_damage_count:
            # Prioritize left area turrets (x-coordinate 0-5, but exclude [5,12] which goes to middle)
            left_turrets = [[2,13], [3,13], [3,12], [2,12]]  # Only these from the priority list
            remaining_turrets = [loc for loc in all_priority_turrets if loc not in left_turrets]
            priority_order = left_turrets + remaining_turrets
            gamelib.debug_write('DAMAGE ANALYSIS: LEFT area priority - upgrading left side turrets first (damage count: L:{} R:{} M:{})'.format(
                left_damage_count, right_damage_count, middle_damage_count))
        elif right_damage_count > left_damage_count and right_damage_count > middle_damage_count:
            # Prioritize right area turrets (x-coordinate 23-27)
            right_turrets = [[25,13], [24,13], [24,12], [25,12]]  # Only these from the priority list
            remaining_turrets = [loc for loc in all_priority_turrets if loc not in right_turrets]
            priority_order = right_turrets + remaining_turrets
            gamelib.debug_write('DAMAGE ANALYSIS: RIGHT area priority - upgrading right side turrets first (damage count: L:{} R:{} M:{})'.format(
                left_damage_count, right_damage_count, middle_damage_count))
        else:
            # Prioritize middle area turrets in specific order (includes [5,12] as specified)
            middle_priority_order = [[15,12], [9,12], [18,12], [22,12], [5,12], [13,12]]
            # Filter to only include turrets that exist in our priority list
            middle_turrets = [loc for loc in middle_priority_order if loc in all_priority_turrets]
            remaining_turrets = [loc for loc in all_priority_turrets if loc not in middle_turrets]
            priority_order = middle_turrets + remaining_turrets
            gamelib.debug_write('DAMAGE ANALYSIS: MIDDLE area priority - upgrading center turrets first (damage count: L:{} R:{} M:{})'.format(
                left_damage_count, right_damage_count, middle_damage_count))
        
        # If no damage recorded yet, default to middle priority
        if not recent_damage:
            middle_priority_order = [[15,12], [9,12], [18,12], [22,12], [5,12], [13,12]]
            middle_turrets = [loc for loc in middle_priority_order if loc in all_priority_turrets]
            remaining_turrets = [loc for loc in all_priority_turrets if loc not in middle_turrets]
            priority_order = middle_turrets + remaining_turrets
            gamelib.debug_write('DAMAGE ANALYSIS: No damage recorded yet - defaulting to MIDDLE area priority')
        
        return priority_order

    def all_turrets_built(self, game_state):
        """
        Check if all primary and secondary turrets are built
        Only skip checking blocking turrets if we're actively in attack execution phase
        """
        # Check primary turrets
        for location in self.primary_turrets:
            # Only skip checking blocking turrets if we're in Phase 2 (active attack execution)
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                continue  # Skip during active attack execution only
            if not game_state.contains_stationary_unit(location):
                return False
        
        # Check secondary turrets
        for location in self.secondary_turrets:
            if not game_state.contains_stationary_unit(location):
                return False
        
        return True

    def all_supports_built_and_upgraded(self, game_state):
        """
        Check if all support structures are built and upgraded
        """
        for location in self.support_positions:
            if not game_state.contains_stationary_unit(location):
                return False  # Support not built yet
            
            units_at_location = game_state.game_map[location]
            for unit in units_at_location:
                if unit.player_index == 0 and not unit.upgraded:
                    return False  # Support exists but not upgraded
        
        return True  # All supports are built and upgraded

    def all_primary_systems_complete(self, game_state):
        """
        Check if ALL primary systems are complete: primary turrets, secondary turrets, supports built+upgraded, and all turrets upgraded
        Only then can we build tertiary turrets
        """
        # Check that all supports are built and upgraded
        if not self.all_supports_built_and_upgraded(game_state):
            return False
            
        # Check that all primary and secondary turrets are upgraded
        all_turret_positions = self.primary_turrets + self.secondary_turrets
        for location in all_turret_positions:
            # Skip blocking turrets during Phase 2
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                continue
                
            if game_state.contains_stationary_unit(location):
                units_at_location = game_state.game_map[location]
                for unit in units_at_location:
                    if unit.player_index == 0 and not unit.upgraded:
                        return False  # Found an unupgraded turret
            else:
                return False  # Found a missing turret
        
        return True  # All primary systems are complete

    def build_tertiary_turrets(self, game_state):
        """
        STEP 5: Build tertiary turret positions (final defensive layer)
        Only builds after ALL primary/secondary turrets, supports are built+upgraded, and all turrets are upgraded
        """
        if not self.all_primary_systems_complete(game_state):
            return  # Don't build if primary systems aren't complete
            
        turrets_built = 0
        
        for location in self.tertiary_turrets:
            # CRITICAL: Respect blocking turret protection during Phase 2
            if self.attack_path_cleared and self.turret_removed_for_attack and location in self.blocking_turret_position2:
                gamelib.debug_write('STEP 5: SKIPPING tertiary blocking turret at {} during Phase 2'.format(location))
                continue
                
            if not game_state.contains_stationary_unit(location):
                if game_state.can_spawn(TURRET, location):
                    game_state.attempt_spawn(TURRET, location)
                    turrets_built += 1
                    gamelib.debug_write('STEP 5: Built tertiary turret at {} (final defensive layer)'.format(location))
        
        if turrets_built > 0:
            gamelib.debug_write('STEP 5 COMPLETE: Built {} tertiary turrets (final layer)'.format(turrets_built))

    def execute_attack_strategy(self, game_state):
        """
        Execute attack strategy: TURRET-ONLY upgrade-based scout rush (ignores supports, focuses on turrets)
        """
        mp = int(game_state.get_resource(MP))  # Convert to integer to avoid float errors
        
        # ESCALATING ATTACK SYSTEM: Check if we're ready for scout rush using dynamic threshold
        # Threshold increases by +2 after each completed attack cycle
        if mp >= self.min_attack_mp and not self.ready_for_scout_rush and not self.turret_removed_for_attack:
            self.ready_for_scout_rush = True
            expected_wave1 = 5 if self.attack_cycles_completed == 0 else 7
            expected_total_min = expected_wave1 + (mp - expected_wave1)
            
            gamelib.debug_write('🚀 TURRET-ONLY UPGRADE-BASED SCOUT RUSH ACTIVATED! 🚀')
            gamelib.debug_write('MP: {} >= Threshold: {} | Attack Cycle: {} | Direction: {} | Will use REAL-TIME analysis in Phase 2'.format(
                mp, self.min_attack_mp, self.attack_cycles_completed + 1, self.current_attack_direction.upper()))
            gamelib.debug_write('SINGLE WAVE LOGIC: If target area has 0 upgraded turrets → ALL {} MP in single wave | Otherwise → Dual wave pattern'.format(mp))
            gamelib.debug_write('TURRET-ONLY STRATEGY: Targets area with fewest upgraded TURRETS → CENTER/LEFT/RIGHT + Modified escalation!')
            gamelib.debug_write('ATTACK POSITIONS: Wave1@{} + Wave2@{} | Will Remove Blocking: {}'.format(
                self.scout_attack_position1, self.scout_attack_position2, self.blocking_turret_position2))
            gamelib.debug_write('BLOCKING TURRET SAFETY: Next turn will ensure {} blocking turrets are removed before attack!'.format(
                len(self.blocking_turret_position2)))
            
        if self.ready_for_scout_rush:
            # Execute modified escalating scout rush sequence with dynamic positioning
            self.execute_modified_escalating_scout_rush(game_state)

    def execute_modified_escalating_scout_rush(self, game_state):
        """
        Execute the 3-phase MODIFIED ESCALATING scout rush with DYNAMIC attack positioning
        """
        mp = int(game_state.get_resource(MP))  # Convert to integer to avoid float errors
        
        # Phase 1: Setup blocking turrets (uses ESCALATING MP threshold with DYNAMIC positions)
        if mp >= self.min_attack_mp and not self.turret_removed_for_attack:
            # CRITICAL FIX: ALWAYS remove ALL blocking turrets for CURRENT attack direction
            # This ensures proper path clearing regardless of previous attack direction changes
            turrets_removed = 0
            
            gamelib.debug_write('PHASE 1: Preparing {} attack - ensuring blocking turrets {} are removed'.format(
                self.current_attack_direction.upper(), self.blocking_turret_position2))
            
            # Remove ALL positions that could block ANY attack path to ensure clean slate
            all_possible_blocking_positions = [
                [13, 13], [13,12],  # Center attack blocking
                [1, 13], [1, 12], [2, 12]  # Left/Right attack blocking
            ]
            
            for location in all_possible_blocking_positions:
                if game_state.contains_stationary_unit(location):
                    # Check if this location is one of our defensive turrets we want to keep
                    if location in self.blocking_turret_position2:  # Only remove if it's blocking current attack
                        game_state.attempt_remove([location])
                        turrets_removed += 1
                        gamelib.debug_write('PHASE 1: Removed blocking turret at {} for {} attack'.format(location, self.current_attack_direction.upper()))
            
            # ADDITIONAL SAFETY: Ensure ALL current blocking positions are clear
            for location in self.blocking_turret_position2:
                if game_state.contains_stationary_unit(location):
                    game_state.attempt_remove([location])
                    turrets_removed += 1
                    gamelib.debug_write('PHASE 1: SAFETY REMOVAL - Cleared blocking turret at {} for {} attack'.format(location, self.current_attack_direction.upper()))
            
            # Set indicators - attack will happen NEXT turn
            self.turret_removed_for_attack = True
            self.attack_path_cleared = True
            gamelib.debug_write('PHASE 1: {} ATTACK PATH CLEARED (Cycle {})'.format(
                self.current_attack_direction.upper(), self.attack_cycles_completed + 1))
            gamelib.debug_write('Attack Direction: {} | MP Threshold: {} | Turrets Removed: {} | Wave incoming NEXT turn!'.format(
                self.current_attack_direction.upper(), self.min_attack_mp, turrets_removed))
            
            # DO NOT deploy scouts this turn - return immediately
            return
        
        # Phase 2: Deploy MODIFIED ESCALATING scout attack with DYNAMIC positioning
        elif self.attack_path_cleared and self.turret_removed_for_attack:
            gamelib.debug_write('🌊 PHASE 2: SCOUT DEPLOYMENT - BLOCKING TURRET PROTECTION ACTIVE! 🌊')
            gamelib.debug_write('CRITICAL: All defensive functions will skip rebuilding blocking turrets: {}'.format(self.blocking_turret_position2))
            
            # Deploy scouts with MODIFIED escalation: Wave 1 goes 5→7→stays at 7
            available_mp = mp
            
            # REAL-TIME UPGRADED TURRET CHECK: Verify current upgraded turret count in target area
            current_upgraded_turrets = self.get_real_time_upgraded_turrets_in_target_area(game_state)
            gamelib.debug_write('🔍 REAL-TIME ANALYSIS: Target {} area currently has {} upgraded turrets'.format(
                self.current_attack_direction.upper(), current_upgraded_turrets))
            
            # SINGLE WAVE ATTACK LOGIC: If target area has 0 upgraded turrets, combine all scouts into wave 2
            if current_upgraded_turrets == 0:
                wave1_scouts = 0  # No scouts in wave 1
                wave2_scouts = available_mp  # ALL scouts in wave 2 for maximum single push
                gamelib.debug_write('💥 SINGLE WAVE ATTACK: Target area has 0 upgraded turrets - deploying ALL {} scouts in wave 2 only!'.format(available_mp))
            else:
                # NORMAL DUAL WAVE LOGIC: Target area has upgraded turrets, use standard escalation
                if self.attack_cycles_completed == 0:
                    base_wave1_size = 5  # First attack: 5 scouts
                else:
                    base_wave1_size = 7  # All subsequent attacks: 7 scouts (no further increase)
                
                wave1_scouts = min(base_wave1_size, available_mp)  # Don't exceed available MP
                remaining_mp_after_wave1 = available_mp - wave1_scouts
                wave2_scouts = max(remaining_mp_after_wave1, 0)  # Use remaining MP for wave 2
                gamelib.debug_write('⚡ DUAL WAVE ATTACK: Target area has {} upgraded turrets - using standard wave pattern'.format(current_upgraded_turrets))
            
            # Deploy Wave 1: scouts at DYNAMIC position 1 (0 scouts if single wave attack)
            actual_wave1 = game_state.attempt_spawn(SCOUT, self.scout_attack_position1, wave1_scouts) if wave1_scouts > 0 else 0
            
            # Deploy Wave 2: remaining scouts at DYNAMIC position 2 (ALL scouts if single wave attack)
            actual_wave2 = game_state.attempt_spawn(SCOUT, self.scout_attack_position2, wave2_scouts) if wave2_scouts > 0 else 0
            
            # Ensure we have valid integers (handle None returns)
            actual_wave1 = actual_wave1 if actual_wave1 is not None else 0
            actual_wave2 = actual_wave2 if actual_wave2 is not None else 0
            
            total_deployed = actual_wave1 + actual_wave2
            
            attack_type = "SINGLE WAVE" if current_upgraded_turrets == 0 else "DUAL WAVE"
            gamelib.debug_write('🌊 PHASE 2: {} {} ATTACK DEPLOYED WITH CLEAR PATH! 🌊'.format(attack_type, self.current_attack_direction.upper()))
            gamelib.debug_write('Attack Cycle: {} | Direction: {} | Current Upgraded Turrets: {} | MP Used: {} | Wave 1: {} scouts @ {} | Wave 2: {} scouts @ {} | TOTAL: {} SCOUTS'.format(
                self.attack_cycles_completed + 1, self.current_attack_direction.upper(), current_upgraded_turrets, available_mp, 
                actual_wave1, self.scout_attack_position1, actual_wave2, self.scout_attack_position2, total_deployed))
            gamelib.debug_write('PATH PROTECTION: Blocking turrets {} remain REMOVED during scout movement!'.format(self.blocking_turret_position2))
            gamelib.debug_write('NEXT TURN: Will rebuild defenses in Phase 3, analyze enemy for next optimal direction')
            
            # Set flag for mandatory rebuild next turn
            self.attack_path_cleared = False  # Attack is complete, prepare for rebuild
            gamelib.debug_write('PHASE 2: Dynamic {} attack launched with protected path! Defenses will be rebuilt NEXT turn'.format(self.current_attack_direction))
        
        # Phase 3: ALWAYS rebuild defenses AND increment escalation counter
        elif not self.attack_path_cleared and self.turret_removed_for_attack:
            # CRITICAL FIX: ALWAYS rebuild ALL defensive turrets, not just current blocking ones
            # This ensures we restore our defense regardless of attack direction changes
            turrets_rebuilt = 0
            
            gamelib.debug_write('PHASE 3: Rebuilding defense after {} attack'.format(self.current_attack_direction.upper()))
            
            # Rebuild ALL possible blocking positions that are part of our main defense
            all_defensive_positions = [
                [13, 13], [13,12], # Center position - part of our main turret line
                [1, 13], [1, 12], [2, 12],  # Left side positions - part of our main defense
                [25, 12], [26, 12], [26, 13]  # Right side positions - part of our main defense
            ]
            
            for location in all_defensive_positions:
                # Only rebuild if it's actually part of our primary/secondary/tertiary turrets defense
                if ((location in self.primary_turrets or location in self.secondary_turrets or location in self.tertiary_turrets) 
                    and not game_state.contains_stationary_unit(location)):
                    if game_state.can_spawn(TURRET, location):
                        game_state.attempt_spawn(TURRET, location)
                        turrets_rebuilt += 1
                        gamelib.debug_write('PHASE 3: Rebuilt defensive turret at {} (defensive restoration)'.format(location))
            
            # ADDITIONAL SAFETY: Ensure current blocking positions are rebuilt if they're defensive turrets
            for location in self.blocking_turret_position2:
                if ((location in self.primary_turrets or location in self.secondary_turrets or location in self.tertiary_turrets) 
                    and not game_state.contains_stationary_unit(location)):
                    if game_state.can_spawn(TURRET, location):
                        game_state.attempt_spawn(TURRET, location)
                        turrets_rebuilt += 1
                        gamelib.debug_write('PHASE 3: SAFETY REBUILD - Restored turret at {} for defense'.format(location))
            
            # ESCALATION SYSTEM: Increase attack cycle counter and MP threshold
            previous_threshold = self.min_attack_mp
            self.attack_cycles_completed += 1
            self.min_attack_mp += 1  # CRITICAL: Increase threshold by 2 for next attack
            
            # Reset attack mode indicators to normal defensive state
            self.turret_removed_for_attack = False
            self.ready_for_scout_rush = False
            
            gamelib.debug_write('📈 PHASE 3: DEFENSE RESTORED & ESCALATION COMPLETE! 📈')
            gamelib.debug_write('Attack Cycle {} COMPLETED | Direction: {} | Turrets Rebuilt: {}'.format(
                self.attack_cycles_completed, self.current_attack_direction.upper(), turrets_rebuilt))
            gamelib.debug_write('ESCALATION: MP Threshold {} → {} (+2) | Wave 1: {} scouts (capped at 7)'.format(
                previous_threshold, self.min_attack_mp, 7 if self.attack_cycles_completed > 0 else 5))
            gamelib.debug_write('NEXT ATTACK: Will need MP>={}, will analyze enemy defenses for optimal direction!'.format(self.min_attack_mp))
            gamelib.debug_write('DYNAMIC PROGRESSION: Each attack cycle analyzes enemy and chooses CENTER/LEFT/RIGHT optimally!')

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