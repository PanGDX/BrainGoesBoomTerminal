import pygame
import sys
import math

# Initialize Pygame
pygame.init()

# Constants
GRID_SIZE = 28  # 28x28 grid (0 to 27)
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 900
BACKGROUND_COLOR = (30, 30, 30)
GRID_COLOR = (100, 100, 100)
LINE_COLOR = (255, 255, 0)  # Yellow for boundary lines
BUTTON_COLOR = (70, 130, 180)
BUTTON_HOVER_COLOR = (100, 149, 237)
BUTTON_CLICKED_COLOR = (255, 69, 0)
TEXT_COLOR = (255, 255, 255)

# Calculate button size and spacing
MARGIN = 50
GRID_DISPLAY_SIZE = min(WINDOW_WIDTH, WINDOW_HEIGHT) - 2 * MARGIN
BUTTON_SIZE = 15
CELL_SIZE = GRID_DISPLAY_SIZE / (GRID_SIZE - 1)

class GridButton:
    def __init__(self, x, y, screen_x, screen_y):
        self.grid_x = x
        self.grid_y = y
        self.screen_x = screen_x
        self.screen_y = screen_y
        self.clicked = False
        self.rect = pygame.Rect(screen_x - BUTTON_SIZE//2, screen_y - BUTTON_SIZE//2, BUTTON_SIZE, BUTTON_SIZE)
        
    def draw(self, screen, mouse_pos):
        # Determine color based on state
        if self.clicked:
            color = BUTTON_CLICKED_COLOR
        elif self.rect.collidepoint(mouse_pos):
            color = BUTTON_HOVER_COLOR
        else:
            color = BUTTON_COLOR
            
        pygame.draw.circle(screen, color, (self.screen_x, self.screen_y), BUTTON_SIZE//2)
        pygame.draw.circle(screen, (255, 255, 255), (self.screen_x, self.screen_y), BUTTON_SIZE//2, 1)
        
    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.clicked = not self.clicked
            return True
        return False

def grid_to_screen(grid_x, grid_y):
    """Convert grid coordinates to screen coordinates"""
    # Grid (0,0) is bottom-left, screen (0,0) is top-left
    screen_x = MARGIN + grid_x * CELL_SIZE
    screen_y = WINDOW_HEIGHT - MARGIN - grid_y * CELL_SIZE  # Flip Y axis
    return int(screen_x), int(screen_y)

def draw_grid_lines(screen):
    """Draw the grid lines"""
    # Vertical lines
    for x in range(GRID_SIZE):
        start_x, start_y = grid_to_screen(x, 0)
        end_x, end_y = grid_to_screen(x, GRID_SIZE - 1)
        pygame.draw.line(screen, GRID_COLOR, (start_x, start_y), (end_x, end_y), 1)
    
    # Horizontal lines
    for y in range(GRID_SIZE):
        start_x, start_y = grid_to_screen(0, y)
        end_x, end_y = grid_to_screen(GRID_SIZE - 1, y)
        pygame.draw.line(screen, GRID_COLOR, (start_x, start_y), (end_x, end_y), 1)

def draw_boundary_lines(screen):
    """Draw the four boundary lines: y=-x+13, y=x+13, y=-x+39, y=x-13"""
    
    # Line 1: y = -x + 13
    points1 = []
    for x in range(GRID_SIZE):
        y = -x + 13
        if 0 <= y < GRID_SIZE:
            screen_x, screen_y = grid_to_screen(x, y)
            points1.append((screen_x, screen_y))
    if len(points1) >= 2:
        pygame.draw.lines(screen, LINE_COLOR, False, points1, 3)
    
    # Line 2: y = x + 13
    points2 = []
    for x in range(GRID_SIZE):
        y = x + 14
        if 0 <= y < GRID_SIZE:
            screen_x, screen_y = grid_to_screen(x, y)
            points2.append((screen_x, screen_y))
    if len(points2) >= 2:
        pygame.draw.lines(screen, LINE_COLOR, False, points2, 3)
    
    # Line 3: y = -x + 39
    points3 = []
    for x in range(GRID_SIZE):
        y = -x + 41
        if 0 <= y < GRID_SIZE:
            screen_x, screen_y = grid_to_screen(x, y)
            points3.append((screen_x, screen_y))
    if len(points3) >= 2:
        pygame.draw.lines(screen, LINE_COLOR, False, points3, 3)
    
    # Line 4: y = x - 13
    points4 = []
    for x in range(GRID_SIZE):
        y = x - 14
        if 0 <= y < GRID_SIZE:
            screen_x, screen_y = grid_to_screen(x, y)
            points4.append((screen_x, screen_y))
    if len(points4) >= 2:
        pygame.draw.lines(screen, LINE_COLOR, False, points4, 3)

def main():
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("28x28 Grid with Boundary Lines")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 24)
    small_font = pygame.font.Font(None, 16)
    
    # Create buttons for all grid points
    buttons = []
    
    for x in range(GRID_SIZE):
        for y in range(GRID_SIZE):
            screen_x, screen_y = grid_to_screen(x, y)
            button = GridButton(x, y, screen_x, screen_y)
            buttons.append(button)
    
    # Instructions
    instruction_text = [
        "Click on lattice points to select them",
        "Selected points will turn orange",
        "Yellow lines: y=-x+13, y=x+13, y=-x+39, y=x-13",
        "Press SPACE to print coordinates",
        "Press ESC to quit"
    ]
    
    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    # Print selected coordinates
                    selected_coordinates = [[button.grid_x, button.grid_y] for button in buttons if button.clicked]
                    if selected_coordinates:
                        print("Selected coordinates:")
                        coord_str = str(selected_coordinates).replace(' ', '')
                        print(coord_str)
                    else:
                        print("No coordinates selected")
                        
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    for button in buttons:
                        button.handle_click(mouse_pos)
        
        # Clear screen
        screen.fill(BACKGROUND_COLOR)
        
        # Draw grid lines
        draw_grid_lines(screen)
        
        # Draw boundary lines
        draw_boundary_lines(screen)
        
        # Draw coordinate labels for key points
        # Label some key coordinates
        key_points = [(0, 0), (0, 27), (27, 0), (27, 27), (13, 13)]
        for gx, gy in key_points:
            sx, sy = grid_to_screen(gx, gy)
            label = small_font.render(f"({gx},{gy})", True, TEXT_COLOR)
            screen.blit(label, (sx + 10, sy - 10))
        
        # Draw buttons
        for button in buttons:
            button.draw(screen, mouse_pos)
        
        # Draw instructions
        y_offset = 10
        for i, text in enumerate(instruction_text):
            text_surface = font.render(text, True, TEXT_COLOR)
            screen.blit(text_surface, (10, y_offset + i * 25))
        
        # Show selected count
        selected_count = sum(1 for button in buttons if button.clicked)
        count_text = f"Selected: {selected_count} points"
        count_surface = font.render(count_text, True, TEXT_COLOR)
        screen.blit(count_surface, (10, WINDOW_HEIGHT - 50))
        
        # Show coordinate under mouse
        # Find closest grid point to mouse
        closest_button = None
        min_dist = float('inf')
        for button in buttons:
            dist = math.sqrt((button.screen_x - mouse_pos[0])**2 + (button.screen_y - mouse_pos[1])**2)
            if dist < min_dist and dist < 20:  # Within 20 pixels
                min_dist = dist
                closest_button = button
        
        if closest_button:
            coord_text = f"({closest_button.grid_x}, {closest_button.grid_y})"
            coord_surface = font.render(coord_text, True, TEXT_COLOR)
            screen.blit(coord_surface, (10, WINDOW_HEIGHT - 25))
        
        pygame.display.flip()
        clock.tick(60)
    
    # Print final coordinates when exiting
    selected_coordinates = [[button.grid_x, button.grid_y] for button in buttons if button.clicked]
    if selected_coordinates:
        print("\nFinal selected coordinates:")
        coord_str = str(selected_coordinates).replace(' ', '')
        print(coord_str)
    
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()