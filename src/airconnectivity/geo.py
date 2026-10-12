"""Great-circle distance and flight-time estimates.

Ported from ``airctools.py`` (2021). The only behavioural change is that the
``sortedcontainers`` dependency is dropped in favour of a plain nearest-key
lookup, so the package keeps to its core dependencies.
"""

from __future__ import annotations

import math

#: Cruising speed (nm/h) keyed by the upper bound of a great-circle distance
#: band in nautical miles, ported from the original ``computeTime``.
_SPEED_BY_DISTANCE: dict[int, int] = {
    500: 300,
    1500: 395,
    2500: 433,
    3500: 450,
    4500: 462,
    5500: 467,
    6500: 477,
    7500: 487,
    8500: 500,
}


def gcd(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Great-circle distance between two ``(lat, lon)`` points in nautical miles.

    Uses the law of cosines, as in the original implementation.
    """
    x1, y1 = math.radians(point_a[0]), math.radians(point_a[1])
    x2, y2 = math.radians(point_b[0]), math.radians(point_b[1])

    # Law of cosines; clamp to [-1, 1] to keep acos in domain for antipodal points.
    cos_angle = math.sin(x1) * math.sin(x2) + math.cos(x1) * math.cos(x2) * math.cos(y1 - y2)
    angle_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_angle))))

    # Each degree on a great circle is 60 nautical miles.
    return 60.0 * angle_deg


def closest_speed(distance_nm: float) -> int:
    """Return the cruising speed whose distance band is nearest ``distance_nm``."""
    nearest = min(_SPEED_BY_DISTANCE, key=lambda bound: abs(distance_nm - bound))
    return _SPEED_BY_DISTANCE[nearest]


def compute_time(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Estimated flight time in hours between two ``(lat, lon)`` points."""
    distance = gcd(point_a, point_b)
    return distance / closest_speed(distance)
