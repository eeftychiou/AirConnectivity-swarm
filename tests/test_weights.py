"""Tests for the onwards-connectivity edge weighting."""

from __future__ import annotations

import pandas as pd

from airconnectivity.weights import add_weights


def _flights() -> pd.DataFrame:
    """Two airports with two onward departures inside the layover window."""
    rows = [
        # flight arriving at HEMA, then two departures HEMA->XXX inside 30-240 min
        ("AAA", "HEMA", "2024-03-01 08:00:00", "2024-03-01 10:00:00"),
        ("HEMA", "BBB", "2024-03-01 10:30:00", "2024-03-01 12:00:00"),
        ("HEMA", "CCC", "2024-03-01 12:30:00", "2024-03-01 14:00:00"),
        # a departure too late to count as onward
        ("HEMA", "DDD", "2024-03-01 20:00:00", "2024-03-01 22:00:00"),
    ]
    df = pd.DataFrame(rows, columns=["ADEP", "ADES", "FILED_OFF_BLOCK_TIME", "FILED_ARRIVAL_TIME"])
    df["FILED_OFF_BLOCK_TIME"] = pd.to_datetime(df["FILED_OFF_BLOCK_TIME"])
    df["FILED_ARRIVAL_TIME"] = pd.to_datetime(df["FILED_ARRIVAL_TIME"])
    return df


def test_add_weights_counts_onward_connections() -> None:
    df = add_weights(_flights(), min_layover=30, max_layover=240)

    assert "Weight" in df.columns
    # First flight arrives at HEMA at 10:00; onward departures at 10:30 and 12:30 are
    # within 30-240 min, the 20:00 one is not -> 2 + 1 = 3.
    assert df.loc[0, "Weight"] == 3


def test_add_weights_always_at_least_one() -> None:
    df = add_weights(_flights(), min_layover=30, max_layover=240)
    assert (df["Weight"] >= 1).all()


def test_add_weights_respects_window_bounds() -> None:
    # Widening the window to 12 hours pulls in the 20:00 onward departure.
    df = add_weights(_flights(), min_layover=30, max_layover=720)
    assert df.loc[0, "Weight"] == 4


def test_add_weights_are_whole_numbers() -> None:
    df = add_weights(_flights(), min_layover=30, max_layover=240)
    assert (df["Weight"] == df["Weight"].round()).all()
