# Greedy Turret Placer for python-2l-c

**Date:** 2026-04-18
**Target algo:** `python-algo/python-2l-c/`

## Goal

Replace the static turret entries in `build-order.json` with a per-turn greedy algorithm that places turrets where they cover the most likely enemy walker paths. Concentrate turrets in the upper half of our side (y ∈ [8, 13]) with depth-decay so deeper rows are sparser. Spend SP each turn fully; allow turret upgrades only after every profitable placement is exhausted.

## Non-Goals

- Adaptive enemy detection (Heavy port from `python-2021custom`) — paused, separate spec.
- Walls — removed from build-order in a prior step; placer does not place walls.
- Two-turn siege state machine (option F) — out of scope.
- Frame-accurate damage simulation — placer uses a coarse `dmg × tiles-in-range` proxy.

## Pipeline (per turn)

1. **Refund** low-HP structures (existing `refund_low_health_structures`).
2. **Build-order pass** — runs spawns + interleaved SUPPORT upgrades from `build-order.json`. Builds the 8 anchor turrets (`start` tier) and all SUPPORTs.
3. **Greedy placement** — loop until `SP < 3` or no candidate has positive marginal score.
4. **Upgrade fallback** — while `SP ≥ 8`, pick the existing turret with highest upgrade-ROI; upgrade if positive, else stop.

Strict ordering: even a high-ROI upgrade waits behind any low-ROI placement (placement is preferred per user). Tunable via `MIN_PLACEMENT_SCORE` knob (default 0).

## Module Layout

New file: `python-algo/python-2l-c/turret_placer.py`

```python
def place_turrets(game_state, anchor_locations, scoring="path_freq") -> dict
    # anchor_locations: list of (x, y) — turrets already built by build-order pass.
    #   Used to seed the coverage map. The placer does NOT (re)spawn anchors.
    # Returns {"placed": [...], "upgraded": [...], "stopped_reason": str}
```

Range checks use Euclidean distance from cell-center to cell-center: `math.dist((cx+0.5, cy+0.5), (px+0.5, py+0.5)) ≤ 2.5` (or 3.5 for upgraded). Matches the engine's `attackRange` semantics.

Helpers (private):
- `_compute_threat_surface(game_state) -> dict[(x,y), int]`  — path-frequency counts
- `_candidate_cells(game_state) -> list[(x,y)]`              — empty cells in upper-half
- `_in_range(turret_loc, target_loc, range) -> bool`         — Euclidean range check
- `_score_placement(cell, threat_surface, coverage, scoring)` — see Scoring
- `_score_upgrade(existing_turret, threat_surface, coverage)` — see ROI

Called from `algo_strategy.py` after the build-order pass and before `execute_scout_rush`.

## Build-order Changes

**Keep:**
- `start` tier — 8 anchor turrets at `[6,13], [12,12], [13,13], [14,13], [15,12], [21,13], [2,12], [25,12]` + SUPPORTs at `[13,12], [14,12]` + their upgrades.
- `supportstructure` tier — SUPPORTs at `[13,11], [14,11], [13,10], [14,10]` + their upgrades.

**Remove:**
- All TURRET entries in `frontline`, `catchline`, `funnel`, `supportstructure`. Placer owns these.

**`upgrade-order.json`:** stays empty. Placer is sole turret-upgrade authority.

## Threat Surface

Each turn, before placement:

1. For every cell in `gm.TOP_LEFT ∪ gm.TOP_RIGHT` (56 enemy edge cells), call `find_path_to_edge` toward the opposite friendly edge.
2. For each path returned, every (x, y) where y ≤ 13 contributes one count to `threat_count[(x,y)]`.
3. Skip enemy edge cells already blocked by enemy structures (no path returned).

Estimated cost: ~56 BFS calls × ~1ms ≈ 60ms/turn. Acceptable inside 5s/turn budget.

## Candidate Cells

- Friendly side, y ∈ [8, 13].
- Inside arena diamond (use existing `enumerate_friendly_side_locations` pattern).
- Cell currently empty (no stationary unit).
- Excludes cells where existing structures sit (anchors, supports already built).

## Scoring (3 switchable functions)

Each per-tile weight:

```
"gap_fill"  : weight(p) = 1 if coverage[p] == 0 else 0.2
"stacking"  : weight(p) = 1
"path_freq" : weight(p) = threat_count[p] / max(threat_count.values())
```

Score for candidate `c`:

```
score(c) = depth_factor(c.y) × Σ_{p ∈ threat_surface, in_range(c, p, 2.5)} weight(p)
```

`depth_factor(y)`:

| y | factor |
|---|--------|
| 13 | 0.90 |
| 12 | 0.95 |
| 11 | 0.95 |
| 10 | 0.95 |
| 9  | 0.70 |
| 8  | 0.60 |

Range = `gamelib.GameUnit(TURRET, config).attackRange` (raw 2.5, no upgrades).

**TODO (post-implementation):** A/B test `gap_fill` vs `stacking` vs `path_freq` across 3+ matches each vs `python-2l-b`; log avg HP retained and damage dealt; pick winner as default.

## Upgrade ROI

Existing turret `t` (anchor or previously placed) considered for upgrade:

- Cost: 8 SP.
- Damage gain inside raw range (already covered): `(20 - 6) × Σ weight(p)` for `p` within 2.5 of `t`.
- Damage gain in expanded annulus (newly covered by upgrade): `20 × Σ weight(p)` for `p` within 3.5 but outside 2.5 of `t`.
- ROI = total damage gain / 8.

Within the upgrade-fallback phase (phase 4), upgrades are ranked by ROI; the highest-ROI positive candidate is picked each iteration. The strict-priority rule (placement before any upgrade) is enforced by pipeline order — phase 4 only runs after phase 3 exits.

`depth_factor` does **not** apply to upgrade scoring — the turret already sits at its location; depth-decay was a placement-time bias against deep new placements only.

## Stop Conditions

- Placement: `SP < 3` OR all remaining candidates score `≤ MIN_PLACEMENT_SCORE` (default 0).
- Upgrade: `SP < 8` OR no existing turret has positive upgrade-ROI.
- Cross-turn SP saving: emergent — if budget runs out mid-evaluation, leftover SP rolls to next turn naturally.

## Coverage Model

`coverage[(x,y)]` = number of currently-placed turrets whose range covers (x,y). Initialized from anchors after build-order pass. Updated incrementally as greedy places each new turret. Used by `gap_fill` weight only — `stacking` and `path_freq` ignore it.

## Damage Model Caveat

`6 × tiles-in-range` is a coarse proxy for "shots on walker" (ignores per-frame fire rate, walker speed, walker HP, attack-priority resolution). Adequate for *relative* placement decisions, which is all greedy needs. Frame-by-frame simulation would cost 10–100× more compute for marginal accuracy gain.

## File Diff Summary

| File | Change |
|---|---|
| `python-2l-c/turret_placer.py` | NEW — module described above |
| `python-2l-c/algo_strategy.py` | Add `place_turrets` call after `build_default_defences`; pass anchor list |
| `python-2l-c/build-order.json` | Remove turret entries from `frontline`, `catchline`, `funnel`, `supportstructure` |
| `python-2l-c/upgrade-order.json` | Already empty; no further change |

## Open Questions / Future Work

- A/B-test scoring functions and lock the winner.
- Re-evaluate `MIN_PLACEMENT_SCORE` after first set of replays — strict 0 may waste SP on dead-coverage placements.
- Consider extending placer to walls (currently out of scope, walls were removed).
- Consider plugging adaptive enemy detection (paused Heavy port) into the threat-surface estimator: weight tiles on the predicted attack flank higher.
