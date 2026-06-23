"""
main.py
-------
Autonomous Swarm Coordination Simulator (Project B)

Run:
    python main.py

Controls:
    1-9, 0      Kill agent #1-#10 (0 = agent #10)
    K           Kill a random living agent
    R           Revive all agents (reset)
    SPACE       Pause / resume simulation
    ESC / close Quit

What you're looking for:
    - Agents (white triangles) space themselves evenly around the ring.
    - The ring heatmap (red=stale/uncovered, green=fresh/covered) should be
      almost entirely green when the swarm is healthy.
    - Press a number key to kill an agent (it turns into a red X). Watch its
      two neighbors immediately accelerate to split its territory -- the gap
      closes and the heatmap recovers to ~100% coverage with fewer agents.
    - The HUD shows live coverage %, agents alive, and max gap vs. ideal
      spacing, so the self-healing behavior is quantified, not just visual.
"""

import sys
import math
import asyncio
import pygame

from swarm import SwarmController, BORDER_LENGTH, SENSOR_RADIUS, Agent
from coverage import CoverageTracker

# ---------- Display config ----------
WIDTH, HEIGHT = 1000, 800
FPS = 60
CENTER = (WIDTH // 2, HEIGHT // 2 - 20)
RING_RADIUS = 300
NUM_AGENTS = 10

# Colors
BG_COLOR = (12, 14, 20)
RING_BASE_COLOR = (40, 44, 54)
TEXT_COLOR = (230, 230, 235)
SUBTEXT_COLOR = (150, 155, 165)
AGENT_COLOR = (255, 255, 255)
AGENT_DEAD_COLOR = (220, 60, 60)
GOOD_COVERAGE = (60, 200, 110)
WARN_COVERAGE = (230, 180, 60)
BAD_COVERAGE = (220, 70, 70)
PANEL_BG = (22, 25, 33)


def border_to_xy(position):
    """Map a 1D border coordinate [0, BORDER_LENGTH) onto the ring."""
    theta = (position / BORDER_LENGTH) * math.tau - math.pi / 2
    x = CENTER[0] + RING_RADIUS * math.cos(theta)
    y = CENTER[1] + RING_RADIUS * math.sin(theta)
    return x, y, theta


def heat_color(freshness):
    """Map freshness [0,1] -> color from BAD (stale) to GOOD (fresh)."""
    f = max(0.0, min(1.0, freshness))
    if f < 0.5:
        t = f / 0.5
        r = BAD_COVERAGE[0] + (WARN_COVERAGE[0] - BAD_COVERAGE[0]) * t
        g = BAD_COVERAGE[1] + (WARN_COVERAGE[1] - BAD_COVERAGE[1]) * t
        b = BAD_COVERAGE[2] + (WARN_COVERAGE[2] - BAD_COVERAGE[2]) * t
    else:
        t = (f - 0.5) / 0.5
        r = WARN_COVERAGE[0] + (GOOD_COVERAGE[0] - WARN_COVERAGE[0]) * t
        g = WARN_COVERAGE[1] + (GOOD_COVERAGE[1] - WARN_COVERAGE[1]) * t
        b = WARN_COVERAGE[2] + (GOOD_COVERAGE[2] - WARN_COVERAGE[2]) * t
    return (int(r), int(g), int(b))


def draw_heatmap_ring(surface, tracker):
    """Draw the coverage heatmap as colored arcs around the ring."""
    freshness = tracker.get_heatmap()
    n = tracker.n_cells
    inner_r = RING_RADIUS - 14
    outer_r = RING_RADIUS + 14

    for i in range(n):
        f = freshness[i]
        color = heat_color(f)
        theta0 = (i / n) * math.tau - math.pi / 2
        theta1 = ((i + 1) / n) * math.tau - math.pi / 2

        p1 = (CENTER[0] + inner_r * math.cos(theta0), CENTER[1] + inner_r * math.sin(theta0))
        p2 = (CENTER[0] + outer_r * math.cos(theta0), CENTER[1] + outer_r * math.sin(theta0))
        p3 = (CENTER[0] + outer_r * math.cos(theta1), CENTER[1] + outer_r * math.sin(theta1))
        p4 = (CENTER[0] + inner_r * math.cos(theta1), CENTER[1] + inner_r * math.sin(theta1))
        pygame.draw.polygon(surface, color, [p1, p2, p3, p4])


def draw_agent(surface, agent, font):
    x, y, theta = border_to_xy(agent.position)

    if not agent.alive:
        # Draw a red X at last known position.
        size = 10
        dx, dy = x, y
        pygame.draw.line(surface, AGENT_DEAD_COLOR, (dx - size, dy - size), (dx + size, dy + size), 3)
        pygame.draw.line(surface, AGENT_DEAD_COLOR, (dx - size, dy + size), (dx + size, dy - size), 3)
        return

    # Triangle pointing in direction of travel (tangent to ring).
    heading = theta + math.pi / 2 + (math.pi if agent.velocity < 0 else 0)
    size = 11
    p1 = (x + size * math.cos(heading), y + size * math.sin(heading))
    p2 = (x + size * 0.6 * math.cos(heading + 2.5), y + size * 0.6 * math.sin(heading + 2.5))
    p3 = (x + size * 0.6 * math.cos(heading - 2.5), y + size * 0.6 * math.sin(heading - 2.5))
    pygame.draw.polygon(surface, AGENT_COLOR, [p1, p2, p3])

    # Small marker dot to visualize the agent's sensor footprint center.
    pygame.draw.circle(surface, (90, 130, 200), (int(x), int(y)), 4, 1)

    label = font.render(f"#{agent.id + 1}", True, SUBTEXT_COLOR)
    surface.blit(label, (x + 12, y - 6))


def draw_hud(surface, font_big, font, swarm, tracker, paused):
    pct = tracker.coverage_percent()
    alive = swarm.num_alive()
    total = len(swarm.agents)
    max_gap, mean_gap, ideal = swarm.coverage_gap_metrics()

    panel = pygame.Rect(20, 20, 330, 168)
    s = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    pygame.draw.rect(s, (*PANEL_BG, 215), s.get_rect(), border_radius=10)
    surface.blit(s, panel.topleft)

    title = font_big.render("SWARM COVERAGE", True, TEXT_COLOR)
    surface.blit(title, (panel.x + 16, panel.y + 12))

    if pct >= 95:
        pct_color = GOOD_COVERAGE
    elif pct >= 75:
        pct_color = WARN_COVERAGE
    else:
        pct_color = BAD_COVERAGE
    pct_text = font_big.render(f"{pct:5.1f}%", True, pct_color)
    surface.blit(pct_text, (panel.x + 16, panel.y + 44))

    lines = [
        f"Agents alive:  {alive} / {total}",
        f"Ideal spacing: {ideal:6.1f}",
        f"Max gap:       {max_gap:6.1f}",
        f"Mean gap:      {mean_gap:6.1f}",
    ]
    for i, line in enumerate(lines):
        t = font.render(line, True, SUBTEXT_COLOR)
        surface.blit(t, (panel.x + 16, panel.y + 86 + i * 20))

    if paused:
        p = font_big.render("PAUSED", True, WARN_COVERAGE)
        surface.blit(p, (WIDTH - 160, 24))


def draw_controls(surface, font):
    lines = [
        "1-0: kill agent #1-#10   K: kill random   R: revive all   SPACE: pause   ESC: quit",
    ]
    for i, line in enumerate(lines):
        t = font.render(line, True, SUBTEXT_COLOR)
        surface.blit(t, (20, HEIGHT - 30 + i * 18))


async def main():
    pygame.init()
    pygame.display.set_caption("Autonomous Swarm Coordination — Border Patrol Simulator")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    # pygame.font.Font(None, size) uses Pygame's bundled default font.
    # SysFont() depends on OS font discovery, which doesn't exist in the
    # browser/WASM sandbox -- using the bundled font keeps rendering
    # identical on desktop and in-browser.
    font = pygame.font.Font(None, 18)
    font_big = pygame.font.Font(None, 30)

    swarm = SwarmController(num_agents=NUM_AGENTS)
    tracker = CoverageTracker(BORDER_LENGTH)

    paused = False
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        dt = min(dt, 0.05)  # clamp to avoid huge steps on lag spikes

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_r:
                    swarm.revive_all()
                elif event.key == pygame.K_k:
                    swarm.kill_random_agent()
                else:
                    num_keys = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
                                pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9, pygame.K_0]
                    if event.key in num_keys:
                        idx = num_keys.index(event.key)
                        swarm.kill_agent(idx)

        if not paused:
            swarm.step(dt)
            living_positions = [a.position for a in swarm.living_agents()]
            tracker.update(living_positions, SENSOR_RADIUS, dt)

        screen.fill(BG_COLOR)
        pygame.draw.circle(screen, RING_BASE_COLOR, CENTER, RING_RADIUS, 2)
        draw_heatmap_ring(screen, tracker)
        for agent in swarm.agents:
            draw_agent(screen, agent, font)
        draw_hud(screen, font_big, font, swarm, tracker, paused)
        draw_controls(screen, font)

        pygame.display.flip()

        # Required for pygbag/WASM: yields control back to the browser's
        # event loop every frame. On desktop this is a harmless no-op.
        await asyncio.sleep(0)

    pygame.quit()
    # Avoid sys.exit() here -- pygbag's docs warn against it since
    # asyncio.run() handles program teardown in the WASM runtime.
    if sys.platform not in ("emscripten", "wasi"):
        sys.exit()


if __name__ == "__main__":
    asyncio.run(main())
