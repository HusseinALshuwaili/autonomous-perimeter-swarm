# Autonomous Perimeter Swarm

A real-time 2D simulator demonstrating **self-healing coverage**: 10 autonomous
agents patrol a closed border, and when an agent fails, its neighbors
automatically redistribute to close the gap — with no central planner and no
retraining required.

## Why this matters

Companies building drone or underwater vehicle swarms (Anduril's Ghost,
Roadrunner, and Dive-LD systems, for example) need units to survive
individual losses — getting shot down, jammed, or running out of power —
without a human operator manually re-tasking the rest of the fleet. This
project demonstrates that capability in miniature: a decentralized control
law where each agent reacts only to its immediate neighbors, so coverage
degrades gracefully instead of catastrophically when agents are lost.

## How it works

- **The border** is modeled as a closed loop (visualized as a ring). Each
  agent's position is a single number along that loop.
- **Spacing control law:** every frame, each agent recalculates the "ideal"
  gap to its neighbors as `border_length / number_of_living_agents`. This
  single line is what makes the swarm self-heal — the moment an agent dies,
  this number changes for everyone, and neighbors on either side of the gap
  immediately have a reason to spread out and cover it.
- **Acceleration limiting:** agents have a maximum acceleration (not just a
  maximum speed), so they ramp up to closing a gap rather than teleporting
  instantly to full speed — a closer approximation of how a real vehicle
  with mass and thrust limits would behave.
- **Communication realism:** agents don't see their neighbors' positions
  instantly or perfectly. A configurable latency (`COMMS_LATENCY`) delays
  what an agent "knows" about its neighbors, and a packet-loss chance
  (`PACKET_LOSS_CHANCE`) randomly drops updates entirely, simulating a real,
  imperfect radio link rather than a magic instant one.
- **Coverage heatmap:** the border is discretized into cells that track how
  recently they were "sensed" by a nearby agent, decaying over time. This
  produces both the visual heatmap and the single coverage % metric used to
  evaluate the system.

## Results

Tested by killing 20% of agents (2 of 10) and measuring recovery:

| Scenario | Coverage |
|---|---|
| Healthy swarm (10/10 agents) | ~100% |
| Immediately after losing 2 agents | dips, then recovers |
| After ~10-15s of recovery (8/10 agents) | ~94-97% |

The system remained stable and recovered correctly even under degraded
communication conditions (tested up to 0.6s latency and 40% packet loss),
demonstrating the control law's robustness isn't dependent on idealized
communication.

## Running it

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Controls

| Key | Action |
|---|---|
| `1`-`9`, `0` | Kill agent #1-#10 |
| `K` | Kill a random living agent |
| `R` | Revive all agents |
| `SPACE` | Pause / resume |
| `ESC` | Quit |

## Design choice: control law over Q-Learning

This implementation uses a deterministic flocking-style control law rather
than reinforcement learning. A P-controller on inter-agent spacing error is
verifiable and converges predictably — for a capability like border-patrol
coverage, where predictable behavior matters as much as adaptiveness, this
is a deliberate tradeoff, not a shortcut. The codebase is structured so the
control law in `swarm.py`'s `step()` method could be swapped for a learned
policy as a future comparison.

## File structure

```
autonomous-perimeter-swarm/
├── main.py          # Pygame rendering, input handling, game loop
├── swarm.py          # Agent + SwarmController: the coordination algorithm
├── coverage.py       # Coverage heatmap tracking and the coverage % metric
└── requirements.txt
```
