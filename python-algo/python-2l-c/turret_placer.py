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
