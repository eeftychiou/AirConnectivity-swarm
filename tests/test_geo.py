"""Tests for great-circle distance and flight-time estimation."""

from __future__ import annotations

import math

import pytest

from airconnectivity.geo import closest_speed, compute_time, gcd

# (lat, lon) for a handful of airports, from the original test data.
POINTS = {
    "KOAK": (37.71667, -122.21667),
    "KJFK": (40.64028, -73.77833),
    "OMDB": (25.24917, 55.36),
    "EGSS": (51.885, 0.235),
    "VOMM": (12.99361, 80.17694),
    "HEMA": (25.55806, 34.58306),
    "KMCO": (28.43333, -81.31667),
    "LTBA": (40.97611, 28.81417),
    "GMFF": (33.92722, -4.97778),
    "LEPA": (39.55167, 2.73889),
    "EDDF": (50.03333, 8.57056),
    "LCLK": (34.87889, 33.63028),
    "LGAV": (37.93667, 23.94444),
}

# Great-circle distances in nautical miles (from the original fixture data).
DISTANCES = {
    ("KOAK", "KJFK"): 2238,
    ("KOAK", "OMDB"): 7035,
    ("KOAK", "EGSS"): 4655,
    ("KOAK", "VOMM"): 7520,
    ("KOAK", "HEMA"): 6801,
    ("KOAK", "KMCO"): 2118,
    ("KOAK", "LTBA"): 5835,
    ("KOAK", "GMFF"): 5274,
    ("KOAK", "LEPA"): 5278,
    ("HEMA", "LTBA"): 967,
    ("KJFK", "EDDF"): 3350,
}


@pytest.mark.parametrize(("a", "b", "expected"), [(a, b, dist) for (a, b), dist in DISTANCES.items()])
def test_gcd_matches_known_distances(a: str, b: str, expected: float) -> None:
    assert gcd(POINTS[a], POINTS[b]) == pytest.approx(expected, abs=150)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("KJFK", "EDDF", 7.65), ("LCLK", "LGAV", 1.60)],
)
def test_compute_time(a: str, b: str, expected: float) -> None:
    assert compute_time(POINTS[a], POINTS[b]) == pytest.approx(expected, abs=0.5)


def test_gcd_is_symmetric_and_zero_for_same_point() -> None:
    assert gcd(POINTS["KOAK"], POINTS["KJFK"]) == pytest.approx(gcd(POINTS["KJFK"], POINTS["KOAK"]))
    assert gcd(POINTS["KOAK"], POINTS["KOAK"]) == pytest.approx(0.0, abs=1e-6)


def test_gcd_antipodal_is_finite() -> None:
    # No ValueError from acos, and about half the earth's circumference (10800 nm).
    assert gcd((0.0, 0.0), (0.0, 180.0)) == pytest.approx(10800.0, abs=1.0)


def test_closest_speed_picks_nearest_band() -> None:
    assert closest_speed(500) == 300
    assert closest_speed(560) == 300  # nearer to 500 than to 1500
    assert closest_speed(1400) == 395
    assert closest_speed(100000) == 500


def test_compute_time_positive() -> None:
    assert compute_time(POINTS["LCLK"], POINTS["LGAV"]) > 0
    assert math.isfinite(compute_time(POINTS["LCLK"], POINTS["LGAV"]))
