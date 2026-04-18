# Greedy Turret Placer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-turn greedy turret placer to `python-2l-c` that maximizes coverage of likely enemy walker paths in the upper half of our side, with depth-decay bias and an upgrade-fallback phase.

**Architecture:** New module `turret_placer.py` exposes `place_turrets(game_state, anchor_locations, scoring)`. Pure helpers (range checks, depth factor, scoring weights) are unit-tested with pytest. Engine-coupled helpers (threat surface, candidate cells, orchestrator) use stub-injected game-state objects for tests, then verified live via match. `algo_strategy.py` calls the placer after the build-order pass; `build-order.json` keeps SUPPORTs and the 8 anchor turrets only.

**Tech Stack:** Python 3, gamelib (Terminal C1 SDK), pytest 8 (already installed).

**Spec:** `docs/superpowers/specs/2026-04-18-greedy-turret-placer-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `python-algo/python-2l-c/turret_placer.py` (NEW) | All placer logic — pure helpers + greedy orchestrator |
| `python-algo/python-2l-c/tests/__init__.py` (NEW) | Test package marker |
| `python-algo/python-2l-c/tests/test_turret_placer.py` (NEW) | Unit tests for `turret_placer` (pure helpers + stub-driven orchestrator tests) |
| `python-algo/python-2l-c/algo_strategy.py` (MODIFY) | Wire placer into per-turn pipeline; remove dead funnel-attack branch dead-code paths if exposed |
| `python-algo/python-2l-c/build-order.json` (MODIFY) | Remove turret entries from `frontline`, `catchline`, `funnel`, `supportstructure`. Keep `start` (anchors + supports) and SUPPORT entries elsewhere. |

---

## Task 1: Test scaffolding

**Files:**
- Create: `python-algo/python-2l-c/tests/__init__.py`
- Create: `python-algo/python-2l-c/tests/conftest.py`

- [ ] **Step 1: Create the tests package**

```bash
mkdir -p python-algo/python-2l-c/tests
touch python-algo/python-2l-c/tests/__init__.py
```

- [ ] **Step 2: Add a `conftest.py` with sys.path injection so tests can import `turret_placer`**

`python-algo/python-2l-c/tests/conftest.py`:

```python
import os
import sys

# Add the parent directory (python-2l-c) to sys.path so `import turret_placer` works.
HERE = os.path.dirname(__file__)
PARENT = os.path.abspath(os.path.join(HERE, ".."))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
```

- [ ] **Step 3: Verify pytest discovers the (currently empty) test directory**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: `no tests ran in 0.0X seconds` — exit code 5 is fine; we just need pytest to find the dir.

- [ ] **Step 4: Commit**

```bash
git add python-algo/python-2l-c/tests/
git commit -m "test: scaffold tests package for python-2l-c"
```

---

## Task 2: `depth_factor` pure function

**Files:**
- Create: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

`python-algo/python-2l-c/tests/test_turret_placer.py`:

```python
import pytest
from turret_placer import depth_factor


@pytest.mark.parametrize("y,expected", [
    (13, 0.90),
    (12, 0.95),
    (11, 0.95),
    (10, 0.95),
    (9, 0.70),
    (8, 0.60),
])
def test_depth_factor_table(y, expected):
    assert depth_factor(y) == pytest.approx(expected)


def test_depth_factor_below_range_raises():
    with pytest.raises(ValueError):
        depth_factor(7)


def test_depth_factor_above_range_raises():
    with pytest.raises(ValueError):
        depth_factor(14)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'turret_placer'`.

- [ ] **Step 3: Implement minimal code**

`python-algo/python-2l-c/turret_placer.py`:

```python
"""Greedy turret placer for python-2l-c.

See docs/superpowers/specs/2026-04-18-greedy-turret-placer-design.md.
"""

_DEPTH_FACTORS = {
    13: 0.90,
    12: 0.95,
    11: 0.95,
    10: 0.95,
    9: 0.70,
    8: 0.60,
}

UPPER_HALF_Y_RANGE = (8, 13)  # inclusive on both ends


def depth_factor(y):
    if y not in _DEPTH_FACTORS:
        raise ValueError(f"y={y} outside upper-half range {UPPER_HALF_Y_RANGE}")
    return _DEPTH_FACTORS[y]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add depth_factor with row-by-row decay"
```

---

## Task 3: `in_range` Euclidean check

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import in_range


def test_in_range_same_cell():
    assert in_range((10, 10), (10, 10), 2.5) is True


def test_in_range_two_cells_apart_within_25():
    # Cell-center to cell-center distance: math.dist((10.5,10.5),(12.5,10.5)) == 2.0 ≤ 2.5
    assert in_range((10, 10), (12, 10), 2.5) is True


def test_in_range_three_cells_apart_outside_25():
    # Distance 3.0 > 2.5
    assert in_range((10, 10), (13, 10), 2.5) is False


def test_in_range_diagonal_within_upgraded_range():
    # math.dist((10.5,10.5),(12.5,12.5)) == sqrt(8) ≈ 2.83, > 2.5 but ≤ 3.5
    assert in_range((10, 10), (12, 12), 2.5) is False
    assert in_range((10, 10), (12, 12), 3.5) is True


def test_in_range_at_exact_boundary():
    # math.dist((10.5,10.5),(13.0,10.5)) == 2.5, but cells are integer so test (10,10)→(12,10) above.
    # Test (10,10)→(13,10): center-to-center 3.0, never ≤ 2.5.
    assert in_range((10, 10), (13, 10), 3.0) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py::test_in_range_same_cell -v`
Expected: FAIL with `ImportError: cannot import name 'in_range'`.

- [ ] **Step 3: Implement minimal code**

Append to `turret_placer.py`:

```python
import math


def in_range(turret_loc, target_loc, attack_range):
    """Cell-center Euclidean range check, matching engine attackRange semantics."""
    tx, ty = turret_loc
    px, py = target_loc
    return math.dist((tx + 0.5, ty + 0.5), (px + 0.5, py + 0.5)) <= attack_range
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add in_range Euclidean cell-center check"
```

---

## Task 4: Per-tile weight functions (3 scoring modes)

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import tile_weight


def test_tile_weight_gap_fill_uncovered():
    coverage = {(5, 13): 0, (6, 13): 2}
    threat_count = {(5, 13): 3, (6, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "gap_fill") == 1.0


def test_tile_weight_gap_fill_already_covered():
    coverage = {(5, 13): 2}
    threat_count = {(5, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "gap_fill") == 0.2


def test_tile_weight_stacking_constant():
    coverage = {(5, 13): 0}
    threat_count = {(5, 13): 3}
    assert tile_weight((5, 13), coverage, threat_count, "stacking") == 1.0
    coverage = {(5, 13): 5}
    assert tile_weight((5, 13), coverage, threat_count, "stacking") == 1.0


def test_tile_weight_path_freq_normalized():
    coverage = {}
    threat_count = {(5, 13): 4, (6, 13): 8, (7, 13): 2}
    # max threat = 8
    assert tile_weight((6, 13), coverage, threat_count, "path_freq") == 1.0
    assert tile_weight((5, 13), coverage, threat_count, "path_freq") == 0.5
    assert tile_weight((7, 13), coverage, threat_count, "path_freq") == 0.25


def test_tile_weight_path_freq_empty_threat_count():
    assert tile_weight((5, 13), {}, {}, "path_freq") == 0.0


def test_tile_weight_unknown_mode_raises():
    with pytest.raises(ValueError):
        tile_weight((5, 13), {}, {}, "bogus")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k tile_weight`
Expected: 6 errors with `ImportError: cannot import name 'tile_weight'`.

- [ ] **Step 3: Implement minimal code**

Append to `turret_placer.py`:

```python
SCORING_MODES = ("gap_fill", "stacking", "path_freq")


def tile_weight(tile, coverage, threat_count, mode):
    """Return a per-tile weight in [0, 1] under the chosen scoring mode."""
    if mode == "gap_fill":
        return 1.0 if coverage.get(tile, 0) == 0 else 0.2
    if mode == "stacking":
        return 1.0
    if mode == "path_freq":
        if not threat_count:
            return 0.0
        peak = max(threat_count.values())
        if peak == 0:
            return 0.0
        return threat_count.get(tile, 0) / peak
    raise ValueError(f"unknown scoring mode: {mode!r}")
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add tile_weight scoring modes"
```

---

## Task 5: `score_placement` — depth-weighted coverage sum

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import score_placement


def test_score_placement_no_threat_in_range_returns_zero():
    cell = (5, 13)
    threat_count = {(20, 13): 5}  # far away
    coverage = {(20, 13): 0}
    score = score_placement(cell, threat_count, coverage, attack_range=2.5, mode="path_freq")
    assert score == 0.0


def test_score_placement_in_range_path_freq():
    # Turret at (10,12), tile (10,13) → distance 1.0, in range.
    # path_freq weight: threat_count[10,13]=4 / max=4 → weight 1.0
    # depth_factor(12) = 0.95
    # Expected: 1.0 * 0.95 = 0.95
    cell = (10, 12)
    threat_count = {(10, 13): 4, (20, 13): 4}
    coverage = {(10, 13): 0, (20, 13): 0}
    score = score_placement(cell, threat_count, coverage, attack_range=2.5, mode="path_freq")
    assert score == pytest.approx(0.95)


def test_score_placement_gap_fill_prefers_uncovered():
    cell = (10, 12)
    threat_count = {(10, 13): 1, (11, 13): 1}
    coverage_uncov = {(10, 13): 0, (11, 13): 0}
    coverage_cov = {(10, 13): 2, (11, 13): 2}
    s_uncov = score_placement(cell, threat_count, coverage_uncov, attack_range=2.5, mode="gap_fill")
    s_cov = score_placement(cell, threat_count, coverage_cov, attack_range=2.5, mode="gap_fill")
    assert s_uncov > s_cov


def test_score_placement_depth_decay_applies():
    # Same neighbor tile, two candidate y rows.
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 0}
    s_y13 = score_placement((10, 13), threat_count, coverage, 2.5, "stacking")
    s_y8 = score_placement((10, 8), threat_count, coverage, 2.5, "stacking")
    # (10,13) is in range of itself, depth_factor(13)=0.90 → 0.90.
    # (10,8) is distance 5 from (10,13), out of 2.5 range → 0.
    assert s_y13 == pytest.approx(0.90)
    assert s_y8 == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k score_placement`
Expected: 4 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
def score_placement(cell, threat_count, coverage, attack_range, mode):
    """Score for placing a fresh turret at `cell`.

    Sums tile_weight × depth_factor over all threat tiles in range.
    """
    cx, cy = cell
    df = depth_factor(cy)
    total = 0.0
    for tile in threat_count:
        if in_range(cell, tile, attack_range):
            total += tile_weight(tile, coverage, threat_count, mode)
    return df * total
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 23 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add score_placement with depth decay"
```

---

## Task 6: `score_upgrade` — raw + annulus damage gain

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import score_upgrade

# Damage constants from the spec
RAW_DMG = 6
UP_DMG = 20


def test_score_upgrade_in_raw_only():
    # Tile at distance 1.0 from turret — already in raw 2.5 range.
    # Gain per tile: (UP_DMG - RAW_DMG) * weight = 14 * 1.0
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 1}
    s = score_upgrade((10, 12), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == pytest.approx(14.0)


def test_score_upgrade_in_annulus_only():
    # Tile at distance 3.0 from turret — outside raw, inside upgraded.
    # Gain: UP_DMG * weight = 20 * 1.0
    threat_count = {(13, 13): 1}
    coverage = {(13, 13): 0}
    s = score_upgrade((10, 13), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == pytest.approx(20.0)


def test_score_upgrade_outside_upgraded_range_zero():
    threat_count = {(20, 13): 1}
    coverage = {(20, 13): 0}
    s = score_upgrade((5, 13), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    assert s == 0.0


def test_score_upgrade_no_depth_factor_applied():
    # depth_factor must NOT scale upgrade scores (turret already exists at its location).
    threat_count = {(10, 13): 1}
    coverage = {(10, 13): 1}
    s_y8 = score_upgrade((10, 8), threat_count, coverage, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    # (10,8) → (10,13) distance 5.0, outside upgraded 3.5 → 0
    assert s_y8 == 0.0
    # Test a tile actually in range with low-y turret:
    threat_count2 = {(10, 9): 1}
    coverage2 = {(10, 9): 1}
    s_y8_close = score_upgrade((10, 8), threat_count2, coverage2, raw_range=2.5, upgraded_range=3.5, mode="path_freq")
    # Tile in raw range, weight=1.0, gain=14, NO depth multiplier
    assert s_y8_close == pytest.approx(14.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k score_upgrade`
Expected: 4 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
RAW_TURRET_DAMAGE = 6
UPGRADED_TURRET_DAMAGE = 20


def score_upgrade(turret_loc, threat_count, coverage, raw_range, upgraded_range, mode):
    """Damage gain from upgrading the turret at `turret_loc`.

    Two contributions, summed:
      - tiles already in raw range: (upgraded_dmg - raw_dmg) * weight
      - tiles in the annulus (raw_range < d <= upgraded_range): upgraded_dmg * weight

    No depth_factor — the turret already sits where it sits.
    """
    raw_gain_factor = UPGRADED_TURRET_DAMAGE - RAW_TURRET_DAMAGE
    annulus_gain_factor = UPGRADED_TURRET_DAMAGE
    total = 0.0
    for tile in threat_count:
        w = tile_weight(tile, coverage, threat_count, mode)
        if w == 0:
            continue
        if in_range(turret_loc, tile, raw_range):
            total += raw_gain_factor * w
        elif in_range(turret_loc, tile, upgraded_range):
            total += annulus_gain_factor * w
    return total
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add score_upgrade with raw + annulus damage model"
```

---

## Task 7: `compute_threat_surface` — engine-coupled, stub-driven test

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test using a duck-typed game-state stub**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import compute_threat_surface


class _StubGameMap:
    TOP_LEFT = "TL"
    TOP_RIGHT = "TR"
    BOTTOM_LEFT = "BL"
    BOTTOM_RIGHT = "BR"

    def __init__(self, edge_locs):
        self._edge_locs = edge_locs

    def get_edge_locations(self, edge):
        return self._edge_locs[edge]


class _StubGameState:
    def __init__(self, edge_locs, paths):
        self.game_map = _StubGameMap(edge_locs)
        self._paths = paths  # {(start_tuple, target_str): [path_cells]}

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))


def test_compute_threat_surface_counts_paths_on_our_side_only():
    # Two enemy edge cells, each with a path. Tiles at y<=13 should count.
    edges = {
        "TL": [[0, 14]],  # one enemy top-left cell
        "TR": [[27, 14]],  # one enemy top-right cell
    }
    paths = {
        ((0, 14), "BR"): [[0, 14], [1, 13], [2, 12], [3, 11]],
        ((27, 14), "BL"): [[27, 14], [26, 13], [25, 12]],
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    # Enemy-side cells (y >= 14) excluded; only y <= 13 cells counted.
    assert threat == {
        (1, 13): 1,
        (2, 12): 1,
        (3, 11): 1,
        (26, 13): 1,
        (25, 12): 1,
    }


def test_compute_threat_surface_skips_blocked_cells():
    edges = {"TL": [[0, 14]], "TR": [[27, 14]]}
    paths = {
        ((0, 14), "BR"): None,  # blocked — no path
        ((27, 14), "BL"): [[27, 14], [26, 13]],
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    assert threat == {(26, 13): 1}


def test_compute_threat_surface_increments_shared_tiles():
    edges = {"TL": [[0, 14], [1, 14]], "TR": []}
    paths = {
        ((0, 14), "BR"): [[0, 14], [5, 13]],
        ((1, 14), "BR"): [[1, 14], [5, 13]],  # same tile both paths
    }
    gs = _StubGameState(edges, paths)
    threat = compute_threat_surface(gs)
    assert threat[(5, 13)] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k compute_threat_surface`
Expected: 3 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
def compute_threat_surface(game_state):
    """Build a path-frequency map of cells on our side that enemy walkers may cross.

    Iterates every cell on the enemy edges (TOP_LEFT + TOP_RIGHT). Each
    successful path contributes +1 to threat_count[(x, y)] for every cell
    on the path with y <= 13.
    """
    gm = game_state.game_map
    threat_count = {}
    edge_targets = [
        (gm.TOP_LEFT, gm.BOTTOM_RIGHT),
        (gm.TOP_RIGHT, gm.BOTTOM_LEFT),
    ]
    for start_edge, target_edge in edge_targets:
        for start in gm.get_edge_locations(start_edge):
            path = game_state.find_path_to_edge(start, target_edge)
            if not path:
                continue
            for cell in path:
                x, y = cell[0], cell[1]
                if y <= 13:
                    key = (x, y)
                    threat_count[key] = threat_count.get(key, 0) + 1
    return threat_count
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 30 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add compute_threat_surface from enemy edge paths"
```

---

## Task 8: `candidate_cells` — empty cells in upper half

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import candidate_cells


class _StubGameStateOccupancy:
    def __init__(self, occupied):
        self._occupied = {tuple(c) for c in occupied}

    def contains_stationary_unit(self, loc):
        return tuple(loc) in self._occupied


def test_candidate_cells_returns_only_upper_half_diamond():
    gs = _StubGameStateOccupancy(occupied=[])
    cells = candidate_cells(gs)
    # Spot-check: the arena is a diamond. At y=13 our row is x in [0,27]; at y=8 it shrinks.
    assert (0, 13) in cells
    assert (27, 13) in cells
    # y=7 is excluded (below upper half)
    assert (10, 7) not in cells
    # y=14 is enemy side
    assert (10, 14) not in cells


def test_candidate_cells_excludes_occupied():
    gs = _StubGameStateOccupancy(occupied=[[10, 13], [11, 12]])
    cells = candidate_cells(gs)
    assert (10, 13) not in cells
    assert (11, 12) not in cells
    assert (12, 12) in cells  # neighbor still candidate


def test_candidate_cells_y_range_strict():
    gs = _StubGameStateOccupancy(occupied=[])
    cells = candidate_cells(gs)
    ys = {y for (_, y) in cells}
    assert ys == {8, 9, 10, 11, 12, 13}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k candidate_cells`
Expected: 3 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
ARENA_SIZE = 28
HALF_ARENA = 14


def _enumerate_friendly_diamond():
    """Generator over every (x, y) inside the friendly half-diamond, y in [0, 13]."""
    for x in range(ARENA_SIZE):
        if x < HALF_ARENA:
            for y in range(HALF_ARENA - x - 1, HALF_ARENA):
                yield (x, y)
        else:
            for y in range(x - HALF_ARENA, HALF_ARENA):
                yield (x, y)


def candidate_cells(game_state):
    """Empty cells inside the upper half of the friendly diamond, y in [8, 13]."""
    y_lo, y_hi = UPPER_HALF_Y_RANGE
    out = []
    for cell in _enumerate_friendly_diamond():
        x, y = cell
        if y < y_lo or y > y_hi:
            continue
        if game_state.contains_stationary_unit(list(cell)):
            continue
        out.append(cell)
    return out
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 33 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add candidate_cells with diamond + upper-half filter"
```

---

## Task 9: `existing_turrets` — find anchors + previously-placed turrets

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import existing_turrets


class _Unit:
    def __init__(self, unit_type, upgraded=False):
        self.unit_type = unit_type
        self.upgraded = upgraded


class _StubGameStateUnits:
    def __init__(self, units):
        # units: dict[(x,y)] -> _Unit or None
        self._units = {tuple(k): v for k, v in units.items()}

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))


def test_existing_turrets_returns_only_unupgraded_turrets():
    units = {
        (2, 12): _Unit("TURRET", upgraded=False),
        (6, 13): _Unit("TURRET", upgraded=True),  # already upgraded — exclude
        (13, 12): _Unit("SUPPORT"),                # not a turret
        (10, 10): _Unit("WALL"),                   # not a turret
    }
    gs = _StubGameStateUnits(units)
    result = existing_turrets(gs, turret_shorthand="TURRET")
    assert (2, 12) in result
    assert (6, 13) not in result
    assert (13, 12) not in result
    assert (10, 10) not in result


def test_existing_turrets_only_upper_half():
    units = {
        (10, 5): _Unit("TURRET"),   # below upper half — exclude
        (10, 13): _Unit("TURRET"),  # in upper half
    }
    gs = _StubGameStateUnits(units)
    result = existing_turrets(gs, turret_shorthand="TURRET")
    assert (10, 5) not in result
    assert (10, 13) in result
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k existing_turrets`
Expected: 2 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
def existing_turrets(game_state, turret_shorthand):
    """Return upper-half cells where a non-upgraded turret currently sits."""
    out = []
    y_lo, y_hi = UPPER_HALF_Y_RANGE
    for cell in _enumerate_friendly_diamond():
        x, y = cell
        if y < y_lo or y > y_hi:
            continue
        unit = game_state.contains_stationary_unit(list(cell))
        if not unit:
            continue
        if unit.unit_type != turret_shorthand:
            continue
        if getattr(unit, "upgraded", False):
            continue
        out.append(cell)
    return out
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 35 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add existing_turrets enumerator"
```

---

## Task 10: `init_coverage` — seed coverage map from existing turrets

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import init_coverage


def test_init_coverage_counts_anchors_in_range_of_threat():
    threat = {(10, 13): 1, (11, 13): 1, (20, 13): 1}
    anchors = [(10, 12)]  # in range of (10,13) and (11,13), not (20,13)
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov[(10, 13)] == 1
    assert cov[(11, 13)] == 1
    assert cov[(20, 13)] == 0


def test_init_coverage_stacks_multiple_anchors():
    threat = {(10, 13): 1}
    anchors = [(10, 12), (11, 12)]  # both in range of (10,13)
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov[(10, 13)] == 2


def test_init_coverage_initializes_uncovered_to_zero():
    threat = {(10, 13): 1, (20, 13): 1}
    anchors = []
    cov = init_coverage(threat, anchors, raw_range=2.5)
    assert cov == {(10, 13): 0, (20, 13): 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k init_coverage`
Expected: 3 errors with `ImportError`.

- [ ] **Step 3: Implement**

Append to `turret_placer.py`:

```python
def init_coverage(threat_count, turret_locs, raw_range):
    """Build coverage map: how many turrets currently cover each threat tile."""
    cov = {tile: 0 for tile in threat_count}
    for tile in cov:
        for t in turret_locs:
            if in_range(t, tile, raw_range):
                cov[tile] += 1
    return cov
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 38 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add init_coverage seeding from existing turrets"
```

---

## Task 11: `place_turrets` — orchestrator with greedy + upgrade-fallback

**Files:**
- Modify: `python-algo/python-2l-c/turret_placer.py`
- Modify: `python-algo/python-2l-c/tests/test_turret_placer.py`

- [ ] **Step 1: Write the failing tests using a comprehensive game-state stub**

Append to `tests/test_turret_placer.py`:

```python
from turret_placer import place_turrets


class _OrchestratorStub:
    """Combines map, paths, occupancy, units, SP, and spawn/upgrade actions."""

    TURRET_COST = 3
    UPGRADE_COST = 8

    def __init__(self, sp, edges, paths, units):
        self._sp = sp
        self._edges = edges
        self._paths = paths
        self._units = {tuple(k): v for k, v in units.items()}
        self.spawn_calls = []
        self.upgrade_calls = []
        self.game_map = _StubGameMap(edges)

    def find_path_to_edge(self, start, target):
        return self._paths.get((tuple(start), target))

    def contains_stationary_unit(self, loc):
        return self._units.get(tuple(loc))

    def get_resource(self, resource_type, _player=0):
        return self._sp

    def type_cost(self, unit_type, upgrade=False):
        # Return [SP, MP] cost. Index 0 (SP) is what placer reads.
        if upgrade:
            return [self.UPGRADE_COST, 0]
        return [self.TURRET_COST, 0]

    def attempt_spawn(self, unit_type, loc, count=1):
        loc = tuple(loc)
        if self._sp < self.TURRET_COST:
            return 0
        self._sp -= self.TURRET_COST
        self.spawn_calls.append(loc)
        self._units[loc] = _Unit("TURRET", upgraded=False)
        return 1

    def attempt_upgrade(self, loc):
        loc = tuple(loc)
        if self._sp < self.UPGRADE_COST:
            return 0
        if loc not in self._units:
            return 0
        self._sp -= self.UPGRADE_COST
        self.upgrade_calls.append(loc)
        self._units[loc].upgraded = True
        return 1


def _make_simple_stub(sp, anchors=()):
    # Single enemy path going straight down through x=14.
    edges = {"TL": [], "TR": [[14, 27]], "BL": [], "BR": []}
    path = [[14, 27 - i] for i in range(28)]  # crosses y=13..0 at x=14
    paths = {((14, 27), "BL"): path}
    units = {tuple(a): _Unit("TURRET", upgraded=False) for a in anchors}
    return _OrchestratorStub(sp, edges, paths, units)


def test_place_turrets_spends_until_sp_below_3():
    stub = _make_simple_stub(sp=10)  # 3 turrets affordable, 1 SP left
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert len(stub.spawn_calls) == 3
    assert stub._sp == 1
    assert result["stopped_reason"] in ("budget_exhausted", "no_positive_score")


def test_place_turrets_upgrade_fallback_runs_after_placement():
    # Anchor at (14,12) covers (14,13) etc. After all candidate placements
    # (in the simple-path stub, every relevant placement has already been made),
    # leftover SP >= 8 should trigger upgrade.
    # SP = 9: too little for upgrade after spending most on placements.
    # SP = 100: plenty for upgrades.
    stub = _make_simple_stub(sp=100, anchors=[(14, 12)])
    result = place_turrets(stub, anchor_locations=[(14, 12)], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    # At least one upgrade should fire (some turret is in range of threat tiles).
    assert len(stub.upgrade_calls) >= 1


def test_place_turrets_strict_priority_no_upgrade_until_placement_exhausted():
    # Tiny budget — only 3 SP. Placement gets the spend, no upgrade ever.
    stub = _make_simple_stub(sp=3, anchors=[(14, 12)])
    place_turrets(stub, anchor_locations=[(14, 12)], turret_shorthand="TURRET",
                   scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert len(stub.spawn_calls) == 1
    assert len(stub.upgrade_calls) == 0


def test_place_turrets_returns_action_log():
    stub = _make_simple_stub(sp=6)
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert "placed" in result
    assert "upgraded" in result
    assert "stopped_reason" in result
    assert len(result["placed"]) == 2  # 6 SP / 3 = 2 turrets


def test_place_turrets_no_threat_does_nothing():
    # Path is blocked from every enemy edge → empty threat surface.
    edges = {"TL": [[0, 14]], "TR": [[27, 14]], "BL": [], "BR": []}
    paths = {((0, 14), "BR"): None, ((27, 14), "BL"): None}
    stub = _OrchestratorStub(sp=10, edges=edges, paths=paths, units={})
    result = place_turrets(stub, anchor_locations=[], turret_shorthand="TURRET",
                            scoring="path_freq", raw_range=2.5, upgraded_range=3.5)
    assert stub.spawn_calls == []
    assert result["stopped_reason"] == "no_threat"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/test_turret_placer.py -v -k place_turrets`
Expected: 5 errors with `ImportError`.

- [ ] **Step 3: Implement the orchestrator**

Append to `turret_placer.py`:

```python
SP_RESOURCE_INDEX = 0  # game_state.get_resource(SP_RESOURCE_INDEX) returns SP


def place_turrets(
    game_state,
    anchor_locations,
    turret_shorthand,
    scoring="path_freq",
    raw_range=2.5,
    upgraded_range=3.5,
    min_placement_score=0.0,
):
    """Greedy turret placer + upgrade-fallback. See spec for full design."""
    placed = []
    upgraded = []

    threat = compute_threat_surface(game_state)
    if not threat:
        return {"placed": placed, "upgraded": upgraded, "stopped_reason": "no_threat"}

    candidates = candidate_cells(game_state)
    coverage = init_coverage(threat, list(anchor_locations), raw_range)

    # --- Phase 3: Greedy placement ---
    turret_cost = game_state.type_cost("TURRET")[SP_RESOURCE_INDEX]
    stopped = "budget_exhausted"
    while game_state.get_resource(SP_RESOURCE_INDEX) >= turret_cost and candidates:
        best, best_score = None, min_placement_score
        for c in candidates:
            s = score_placement(c, threat, coverage, raw_range, scoring)
            if s > best_score:
                best, best_score = c, s
        if best is None:
            stopped = "no_positive_score"
            break
        sent = game_state.attempt_spawn(turret_shorthand, list(best))
        if sent <= 0:
            candidates.remove(best)
            continue
        placed.append(best)
        candidates.remove(best)
        for tile in threat:
            if in_range(best, tile, raw_range):
                coverage[tile] = coverage.get(tile, 0) + 1

    # --- Phase 4: Upgrade fallback ---
    upgrade_cost = game_state.type_cost("TURRET", upgrade=True)[SP_RESOURCE_INDEX]
    upgrade_pool = list(anchor_locations) + placed
    # Re-fetch existing turrets in case anchors weren't passed and we want to upgrade
    # whatever turrets are present in the upper half (defensive).
    for t in existing_turrets(game_state, turret_shorthand):
        if t not in upgrade_pool:
            upgrade_pool.append(t)

    while game_state.get_resource(SP_RESOURCE_INDEX) >= upgrade_cost and upgrade_pool:
        best, best_score = None, 0.0
        for t in upgrade_pool:
            s = score_upgrade(t, threat, coverage, raw_range, upgraded_range, scoring)
            if s > best_score:
                best, best_score = t, s
        if best is None:
            break
        sent = game_state.attempt_upgrade(list(best))
        if sent <= 0:
            upgrade_pool.remove(best)
            continue
        upgraded.append(best)
        upgrade_pool.remove(best)
        # Update coverage for the newly-covered annulus tiles (upgrades extend range).
        for tile in threat:
            if in_range(best, tile, upgraded_range) and not in_range(best, tile, raw_range):
                coverage[tile] = coverage.get(tile, 0) + 1

    return {"placed": placed, "upgraded": upgraded, "stopped_reason": stopped}
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 43 passed.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/turret_placer.py python-algo/python-2l-c/tests/test_turret_placer.py
git commit -m "feat(2l-c): add place_turrets orchestrator (greedy + upgrade fallback)"
```

---

## Task 12: Strip non-anchor turret entries from `build-order.json`

**Files:**
- Modify: `python-algo/python-2l-c/build-order.json`

- [ ] **Step 1: Read current build-order.json to understand the layout**

Run: `cat /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c/build-order.json`

Expected current top-level keys: `start`, `frontline`, `catchline`, `funnel`, `supportstructure`.

- [ ] **Step 2: Replace file content (preserve `start` anchors + supports + their upgrades; preserve all SUPPORT entries elsewhere; drop all TURRET entries from non-`start` tiers; drop `funnel` entirely since it was turrets-only)**

Write `python-algo/python-2l-c/build-order.json`:

```json
{
  "start": [
    { "type": "spawn", "unit": "TURRET", "location": [6, 13] },
    { "type": "spawn", "unit": "TURRET", "location": [12, 12] },
    { "type": "spawn", "unit": "TURRET", "location": [13, 13] },
    { "type": "spawn", "unit": "TURRET", "location": [14, 13] },
    { "type": "spawn", "unit": "TURRET", "location": [15, 12] },
    { "type": "spawn", "unit": "TURRET", "location": [21, 13] },
    { "type": "spawn", "unit": "SUPPORT", "location": [13, 12] },
    { "type": "spawn", "unit": "SUPPORT", "location": [14, 12] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [13, 12] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [14, 12] },
    { "type": "spawn", "unit": "TURRET", "location": [2, 12] },
    { "type": "spawn", "unit": "TURRET", "location": [25, 12] }
  ],
  "frontline": [],
  "catchline": [],
  "supportstructure": [
    { "type": "spawn", "unit": "SUPPORT", "location": [13, 11] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [13, 11] },
    { "type": "spawn", "unit": "SUPPORT", "location": [14, 11] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [14, 11] },
    { "type": "spawn", "unit": "SUPPORT", "location": [13, 10] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [13, 10] },
    { "type": "spawn", "unit": "SUPPORT", "location": [14, 10] },
    { "type": "upgrade", "unit": "SUPPORT", "location": [14, 10] }
  ]
}
```

- [ ] **Step 3: Validate JSON syntax**

Run: `python3 -m json.tool /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c/build-order.json > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 4: Verify the algo's `build_default_defences` priority list still matches the keys present**

Run: `grep -n 'frontline\|catchline\|supportstructure\|funnel' /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c/algo_strategy.py`
Expected: line 229 lists `["start", "frontline","catchline", "supportstructure"]` (no `funnel`). All four keys exist in the JSON (frontline/catchline empty arrays). OK.

- [ ] **Step 5: Commit**

```bash
git add python-algo/python-2l-c/build-order.json
git commit -m "refactor(2l-c): drop non-anchor turret entries from build-order"
```

---

## Task 13: Wire `turret_placer.place_turrets` into `algo_strategy.py`

**Files:**
- Modify: `python-algo/python-2l-c/algo_strategy.py`

- [ ] **Step 1: Read the current `build_defences` and `starter_strategy` to find insertion point**

Run: `grep -n 'def build_defences\|def starter_strategy\|def build_default_defences' /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c/algo_strategy.py`
Expected: `starter_strategy` ~line 101, `build_defences` ~line 194, `build_default_defences` ~line 223.

- [ ] **Step 2: Add the import at the top of the file (after the existing imports)**

Edit `python-algo/python-2l-c/algo_strategy.py`. Find the line:

```python
import os
```

And add immediately below:

```python

from turret_placer import place_turrets
```

- [ ] **Step 3: Define the anchor list as a module-level constant**

Edit `python-algo/python-2l-c/algo_strategy.py`. Find the line containing `MIN_SP_TO_SAVE`-equivalent or the end of the `on_game_start` constants block. Add as a module-level constant near the top (after `import os`/`from turret_placer ...` block):

```python

# Anchor turrets — these are spawned by the build-order `start` tier and
# treated by the placer as already-present (their coverage seeds the map).
# Must match the TURRET entries in build-order.json `start` tier.
ANCHOR_TURRETS = [
    (6, 13), (12, 12), (13, 13), (14, 13), (15, 12),
    (21, 13), (2, 12), (25, 12),
]
TURRET_SCORING_MODE = "path_freq"  # one of: "gap_fill", "stacking", "path_freq"
```

- [ ] **Step 4: Modify `build_defences` to call the placer after the static build pass**

Find the current `build_defences` method (around line 194):

```python
    def build_defences(self, game_state):
        self.refund_low_health_structures(game_state)
        self.build_default_defences(game_state)
```

Replace it with:

```python
    def build_defences(self, game_state):
        self.refund_low_health_structures(game_state)
        self.build_default_defences(game_state)
        result = place_turrets(
            game_state,
            anchor_locations=ANCHOR_TURRETS,
            turret_shorthand=TURRET,
            scoring=TURRET_SCORING_MODE,
        )
        gamelib.debug_write(
            f"placer: placed={len(result['placed'])} "
            f"upgraded={len(result['upgraded'])} "
            f"stop={result['stopped_reason']}"
        )
```

- [ ] **Step 5: Run unit tests once more to confirm placer still imports cleanly**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -m pytest tests/ -v`
Expected: 43 passed.

- [ ] **Step 6: Verify the algo file is syntactically valid Python**

Run: `cd /Users/kevinwu/Coding/BrainGoesBoomTerminal/python-algo/python-2l-c && python3 -c "import ast; ast.parse(open('algo_strategy.py').read()); print('OK')"`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add python-algo/python-2l-c/algo_strategy.py
git commit -m "feat(2l-c): wire turret_placer into build_defences pipeline"
```

---

## Task 14: Live smoke test — single match vs python-2l-b

**Files:** None modified. Verification only.

- [ ] **Step 1: Find the local match-runner script**

Run: `ls /Users/kevinwu/Coding/BrainGoesBoomTerminal/scripts/`
Expected: a script like `run_match.py` or similar. If it's not present, skip to Step 4 (manual upload to terminal.c1games.com playground).

- [ ] **Step 2: If a local runner exists, run python-2l-c vs python-2l-b**

Run (substitute the actual runner script name):

```bash
cd /Users/kevinwu/Coding/BrainGoesBoomTerminal && \
  python3 scripts/run_match.py python-algo/python-2l-c python-algo/python-2l-b
```

Expected: a replay file is generated in `replays/` and the engine prints a winner line.

- [ ] **Step 3: Inspect the placer debug output in the replay/log**

Look for `placer: placed=N upgraded=M stop=...` lines in the engine log. Expected:
- Turn 1: `placed >= 1, upgraded = 0` (no anchors yet matter much; greedy spends remaining SP after build-order).
- Turn 5+: `placed > 0` typical; `upgraded > 0` once SP saturates and placements are exhausted.
- `stop` is one of `budget_exhausted` (most common) or `no_positive_score`.

- [ ] **Step 4: If no local runner, upload to the playground**

Open `https://terminal.c1games.com/playground` in browser. Upload `python-2l-c` as a zip; pit against `python-2l-b`. Watch replay, confirm turrets appear at non-anchor locations (especially y ∈ [10, 13] interior spots that build-order doesn't cover).

- [ ] **Step 5: Commit nothing — this is verification. If a regression is found, file a follow-up TODO and revert/patch.**

---

## Self-Review

**Spec coverage check:**
- §1 module layout → Task 11 (orchestrator) + Task 13 (wiring) ✓
- §2 threat surface → Task 7 ✓
- §3 three scoring modes → Task 4 (weights) + Task 5 (placement score) ✓ — A/B testing is post-implementation TODO, captured by `TURRET_SCORING_MODE` constant in Task 13
- §4 depth factor table → Task 2 ✓
- §5 4-phase pipeline → Task 11 phase 3 + phase 4; phase 1/2 are existing 2l-c logic ✓
- Build-order changes → Task 12 ✓
- `upgrade-order.json` already empty → no task needed ✓
- Damage model proxy (`6 × tiles`) → Task 5 implicit, Task 6 explicit (raw 14 + annulus 20) ✓

**Placeholder scan:** None found. All steps have concrete code or commands.

**Type consistency:** `place_turrets` signature matches Task 11 implementation and Task 13 call site (`anchor_locations=`, `turret_shorthand=`, `scoring=`). `tile_weight`, `score_placement`, `score_upgrade`, `compute_threat_surface`, `candidate_cells`, `existing_turrets`, `init_coverage`, `in_range`, `depth_factor` are all defined in the order they're consumed.

**Caveats acknowledged:**
- Stub-driven tests for `compute_threat_surface` use a duck-typed `_StubGameMap`; real `GameMap` exposes the same methods, so the stub is faithful.
- `attempt_spawn` in tests returns 1; the real engine returns the count actually spawned. Placer treats `<=0` as failure, which is correct.
- Task 14 has a fallback path (Step 4) for environments without a local match runner.
