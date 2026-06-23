"""
swarm.py
--------
Core simulation logic for autonomous swarm border patrol.

Design:
- Agents patrol along a 1D border parameterized by `position` in [0, BORDER_LENGTH].
  (Visualized as a 2D path in main.py — could be a straight line, a perimeter, etc.)
- Each agent tries to maintain EQUAL SPACING from its two neighbors (the agents
  immediately ahead of / behind it along the border), not just avoid collisions.
  This is the key behavior: when an agent dies, the spacing target for its
  neighbors instantly changes, and they drift to cover the gap.
- This is a flocking-style (Boids-derived) control law rather than full RL:
  it's deterministic, fast, debuggable, and demonstrates the exact capability
  Anduril cares about (graceful degradation / self-healing coverage) without
  the sample-inefficiency and black-box risk of training a Q-learner for a demo.
- A CoverageTracker independently records how recently each point on the
  border was sensed, decaying over time, which drives both the heatmap and
  the single coverage % metric.
"""

import random
import math

BORDER_LENGTH = 1000.0          # length of the patrol border (abstract units)
SENSOR_RADIUS = 60.0            # how far an agent "sees" along the border
MAX_SPEED = 90.0                # units/sec, max agent speed along the border
MAX_ACCEL = 60.0                 # units/sec^2 -- how fast velocity itself can change
SPACING_GAIN = 2.2              # how aggressively agents close gaps (P-controller gain)
SMOOTHING = 0.18                # velocity smoothing factor (0-1), avoids jittery motion

COMMS_LATENCY = 0.2             # seconds of delay before a neighbor's position update "arrives"
PACKET_LOSS_CHANCE = 0.1        # probability (0-1) that a given position update never arrives at all
POSITION_HISTORY_SECONDS = 1.0  # how far back each agent keeps a position log (must exceed COMMS_LATENCY)


class Agent:
    """A single autonomous patrol agent (e.g. a drone or USV)."""

    _next_id = 0

    def __init__(self, position=None):
        self.id = Agent._next_id
        Agent._next_id += 1

        self.position = position if position is not None else random.uniform(0, BORDER_LENGTH)
        self.velocity = 0.0          # signed scalar velocity along the border
        self.acceleration = 0.0      # current acceleration, set each frame in step()
        self.alive = True
        # (timestamp, position) pairs, oldest first -- a short log of where this
        # agent has actually been, so OTHER agents can simulate seeing a delayed
        # version of it (a real radio link isn't instantaneous).
        self.position_history = []
        # cache of the last successfully "received" position for each neighbor
        # id this agent has looked up -- used to simulate packet loss: if a
        # lookup fails, the agent just keeps believing the last good value.
        self.last_known_neighbor_position = {}
        self.target_spacing = 0.0    # ideal gap to maintain, updated each frame
        self.gap_ahead = 0.0
        self.gap_behind = 0.0
        # small per-agent jitter so paths aren't perfectly robotic in the viz
        self.phase = random.uniform(0, math.tau)

    def kill(self):
        self.alive = False
        self.velocity = 0.0
        self.position_history = []
        self.last_known_neighbor_position = {}

    def revive(self, position=None):
        self.alive = True
        self.position = position if position is not None else random.uniform(0, BORDER_LENGTH)
        self.velocity = 0.0
        self.position_history = []
        self.last_known_neighbor_position = {}

    def record_position_history(self, t):
        """Append (timestamp, position) and trim anything older than we'll ever need."""
        self.position_history.append((t, self.position))
        cutoff = t - POSITION_HISTORY_SECONDS
        while len(self.position_history) > 1 and self.position_history[0][0] < cutoff:
            self.position_history.pop(0)

    def position_at_time(self, t):
        """
        Returns this agent's position as it was at time `t`, using its own
        history log. Falls back to the oldest/newest known sample if `t` is
        out of range (clamping rather than crashing on a missing exact match).
        """
        if not self.position_history:
            return self.position
        if t <= self.position_history[0][0]:
            return self.position_history[0][1]
        if t >= self.position_history[-1][0]:
            return self.position_history[-1][1]
        # Linear interpolation between the two samples bracketing time t.
        for (t0, p0), (t1, p1) in zip(self.position_history, self.position_history[1:]):
            if t0 <= t <= t1:
                if t1 == t0:
                    return p0
                frac = (t - t0) / (t1 - t0)
                return p0 + (p1 - p0) * frac
        return self.position_history[-1][1]


class SwarmController:
    """
    Owns all agents and runs the coordination step each tick.

    Coordination rule (the "self-healing" logic):
      1. Sort LIVING agents by position along the border (circular).
      2. Ideal spacing = BORDER_LENGTH / num_living_agents.
      3. Each agent computes signed gaps to its left/right living neighbor.
      4. Velocity command = SPACING_GAIN * (gap_ahead - gap_behind) / 2
         -> if the agent ahead is farther away than the agent behind, move
            forward to re-center in the gap (and vice versa). This is exactly
            the rule that makes neighbors of a dead agent flow outward to
            split its territory evenly.
      5. Velocity is clamped to MAX_SPEED and smoothed for visual stability.

    Dead agents are simply excluded from steps 1-4, which is what causes the
    "instant recalculation" the moment an agent is killed.
    """

    def __init__(self, num_agents=10):
        self.agents = [Agent(position=(BORDER_LENGTH / num_agents) * i + random.uniform(-20, 20))
                       for i in range(num_agents)]
        self.sim_time = 0.0  # running clock, needed so agents can query "position N seconds ago"

    def living_agents(self):
        return [a for a in self.agents if a.alive]

    def kill_agent(self, index):
        if 0 <= index < len(self.agents):
            self.agents[index].kill()
            return True
        return False

    def kill_random_agent(self):
        living = self.living_agents()
        if living:
            random.choice(living).kill()
            return True
        return False

    def revive_all(self):
        for a in self.agents:
            a.revive()

    def num_alive(self):
        return len(self.living_agents())

    def step(self, dt):
        self.sim_time += dt

        living = sorted(self.living_agents(), key=lambda a: a.position)
        n = len(living)

        # Every living agent logs its OWN current position, every frame,
        # regardless of n -- this is what lets neighbors look up "where were
        # you a moment ago" later.
        for agent in living:
            agent.record_position_history(self.sim_time)

        if n == 0:
            return
        if n == 1:
            # Lone agent: just patrol back and forth / drift, nothing to space against.
            a = living[0]
            a.target_spacing = BORDER_LENGTH
            a.gap_ahead = a.gap_behind = BORDER_LENGTH / 2
            a.velocity = MAX_SPEED * 0.3 * math.sin(a.phase)
            a.position = (a.position + a.velocity * dt) % BORDER_LENGTH
            return

        ideal_spacing = BORDER_LENGTH / n
        delayed_t = self.sim_time - COMMS_LATENCY

        for i, agent in enumerate(living):
            nxt = living[(i + 1) % n]
            prv = living[(i - 1) % n]

            nxt_position = self._received_neighbor_position(agent, nxt, delayed_t)
            prv_position = self._received_neighbor_position(agent, prv, delayed_t)

            gap_ahead = (nxt_position - agent.position) % BORDER_LENGTH
            gap_behind = (agent.position - prv_position) % BORDER_LENGTH

            agent.gap_ahead = gap_ahead
            agent.gap_behind = gap_behind
            agent.target_spacing = ideal_spacing

            # Error signal: want gap_ahead == gap_behind == ideal_spacing.
            # Move toward whichever side has more room (positive = move forward).
            error = (gap_ahead - gap_behind) / 2.0
            desired_velocity = max(-MAX_SPEED, min(MAX_SPEED, SPACING_GAIN * error * 0.1))

            velocity_change_wanted = desired_velocity - agent.velocity
            max_change_this_frame = MAX_ACCEL * dt
            velocity_change = max(-max_change_this_frame, min(max_change_this_frame, velocity_change_wanted))
            agent.acceleration = velocity_change / dt if dt > 0 else 0.0
            agent.velocity += velocity_change

        for agent in living:
            agent.position = (agent.position + agent.velocity * dt) % BORDER_LENGTH

    def _received_neighbor_position(self, observer, neighbor, delayed_t):
        """
        Simulates `observer` receiving a delayed, occasionally-dropped position
        update about `neighbor`, instead of reading neighbor.position directly.

        - With probability PACKET_LOSS_CHANCE, this update is "lost in transit":
          observer just keeps believing whatever it last successfully received.
        - Otherwise, observer receives neighbor's position as it was
          COMMS_LATENCY seconds ago (looked up from neighbor's own history).
        """
        if random.random() < PACKET_LOSS_CHANCE:
            # Packet dropped -- fall back to last known value (or current
            # position if we've genuinely never heard from this neighbor yet,
            # e.g. the very first frame).
            return observer.last_known_neighbor_position.get(neighbor.id, neighbor.position)

        received_position = neighbor.position_at_time(delayed_t)
        observer.last_known_neighbor_position[neighbor.id] = received_position
        return received_position

    def coverage_gap_metrics(self):
        """Returns (max_gap, mean_gap, ideal_spacing) among living agents — useful for HUD."""
        living = sorted(self.living_agents(), key=lambda a: a.position)
        n = len(living)
        if n == 0:
            return 0.0, 0.0, 0.0
        if n == 1:
            return BORDER_LENGTH, BORDER_LENGTH, BORDER_LENGTH
        gaps = []
        for i in range(n):
            nxt = living[(i + 1) % n]
            gaps.append((nxt.position - living[i].position) % BORDER_LENGTH)
        return max(gaps), sum(gaps) / len(gaps), BORDER_LENGTH / n
