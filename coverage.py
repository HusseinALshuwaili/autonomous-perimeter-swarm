"""
coverage.py
-----------
Tracks sensor coverage along the border as a 1D array (the "heatmap").
"""

import numpy as np

N_CELLS = 360                # resolution of the heatmap ring
DECAY_RATE = 0.55            # freshness decay per second (higher = stricter/faster decay)
COVERAGE_THRESHOLD = 0.5     # a cell counts as "covered" above this freshness


class CoverageTracker:
    def __init__(self, border_length, n_cells=N_CELLS):
        self.border_length = border_length
        self.n_cells = n_cells
        self.cell_size = border_length / n_cells
        self.freshness = np.zeros(n_cells, dtype=np.float64)
        self._cell_positions = (np.arange(n_cells) + 0.5) * self.cell_size

    def update(self, agent_positions, sensor_radius, dt):
        self.freshness *= max(0.0, 1.0 - DECAY_RATE * dt)

        if not agent_positions:
            return

        positions = np.array(agent_positions, dtype=np.float64).reshape(-1, 1)
        cells = self._cell_positions.reshape(1, -1)
        L = self.border_length

        diff = np.abs(positions - cells)
        circular_dist = np.minimum(diff, L - diff)

        within_sensor = (circular_dist <= sensor_radius).any(axis=0)
        self.freshness[within_sensor] = 1.0

    def coverage_percent(self):
        covered = np.count_nonzero(self.freshness >= COVERAGE_THRESHOLD)
        return 100.0 * covered / self.n_cells

    def get_heatmap(self):
        """Returns the freshness array (0=stale/uncovered ... 1=fresh/covered)."""
        return self.freshness
