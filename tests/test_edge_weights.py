"""Tests for the issue #3 edge-weight modes (frequency, distance, seats)."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from airconnectivity.geo import gcd
from airconnectivity.weights import (
    DEFAULT_SEATS,
    add_edge_weights,
    aggregate_edges,
    flight_distance_km,
    infer_category,
    load_seats_table,
    seats_for_types,
)

AIRPORTS = {
    "EGLL": (51.4775, -0.4614),
    "LFPG": (49.0097, 2.5479),
    "EHAM": (52.3105, 4.7683),
    "EGKK": (51.1481, -0.1903),
}


def _flights() -> pd.DataFrame:
    """Three flights: two on EGLL->LFPG, one on LFPG->EHAM."""
    rows = [
        ("EGLL", "LFPG", "A320", 350.0),
        ("EGLL", "LFPG", "B77W", 360.0),
        ("LFPG", "EHAM", "AT76", 260.0),
    ]
    df = pd.DataFrame(rows, columns=["adep", "ades", "ac_type", "actual_distance_flown"])
    for code, (lat, lon) in AIRPORTS.items():
        df.loc[df["adep"] == code, "adep_latitude"] = lat
        df.loc[df["adep"] == code, "adep_longitude"] = lon
        df.loc[df["ades"] == code, "ades_latitude"] = lat
        df.loc[df["ades"] == code, "ades_longitude"] = lon
    return df


@pytest.mark.parametrize("mode", ["frequency", "unweighted"])
def test_frequency_and_unweighted_weight_each_flight_as_one(mode: str) -> None:
    weighted = add_edge_weights(_flights(), weight=mode)
    assert (weighted["Weight"] == 1.0).all()


def test_distance_mode_uses_great_circle_km() -> None:
    df = _flights()
    weighted = add_edge_weights(df, weight="distance", distance_source="gcd")

    expected = gcd(AIRPORTS["EGLL"], AIRPORTS["LFPG"]) * 1.852
    assert weighted.iloc[0]["Weight"] == pytest.approx(expected, rel=1e-6)


def test_distance_mode_actual_source_converts_nm_to_km() -> None:
    df = _flights()
    weighted = add_edge_weights(df, weight="distance", distance_source="actual")

    assert weighted.iloc[0]["Weight"] == pytest.approx(350.0 * 1.852, rel=1e-6)
    assert flight_distance_km(df, "actual").tolist() == pytest.approx([350.0 * 1.852, 360.0 * 1.852, 260.0 * 1.852])


def test_seats_mode_uses_type_lookup() -> None:
    weighted = add_edge_weights(_flights(), weight="seats")
    assert weighted["Weight"].tolist() == [180.0, 396.0, 70.0]


def test_seats_lookup_covers_common_types() -> None:
    table = load_seats_table()
    for designator in ("A320", "B738", "B77W", "E190", "AT76"):
        assert designator in table
    assert table["A320"][0] == 180
    assert table["B77W"][1] == "widebody"


def test_unknown_types_use_per_category_default(caplog: pytest.LogCaptureFixture) -> None:
    # B77L (Boeing 777) is a widebody, E145 (Embraer ERJ) a regional jet.
    types = pd.Series(["B77L", "B77L", "E145"])

    with caplog.at_level(logging.WARNING, logger="airconnectivity.weights"):
        seats, unknown = seats_for_types(types)

    assert seats.tolist() == [300, 300, 100]
    assert unknown == ["B77L", "E145"]
    # The warning reports affected flights (3), not just distinct designators (2).
    assert "on 3 flights" in caplog.text
    assert "(2 distinct)" in caplog.text


@pytest.mark.parametrize(
    ("designator", "category"),
    [
        ("B77L", "widebody"),
        ("A359", "widebody"),
        ("E145", "regional_jet"),
        ("CRJ9", "regional_jet"),
        ("AT7X", "turboprop"),
    ],
)
def test_infer_category_families(designator: str, category: str) -> None:
    assert infer_category(designator) == category


def test_infer_category_returns_none_for_unknown_family() -> None:
    assert infer_category("ZZZZ") is None


def test_unknown_type_falls_back_and_is_counted_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    types = pd.Series(["A320", "ZZZZ", "QQQQ"])

    with caplog.at_level(logging.WARNING, logger="airconnectivity.weights"):
        seats, unknown = seats_for_types(types)

    assert seats.tolist() == [180, DEFAULT_SEATS, DEFAULT_SEATS]
    assert unknown == ["QQQQ", "ZZZZ"]
    assert "QQQQ" in caplog.text and "ZZZZ" in caplog.text


def test_empty_type_is_unknown_without_logging(caplog: pytest.LogCaptureFixture) -> None:
    types = pd.Series(["A320", None, ""])

    with caplog.at_level(logging.WARNING, logger="airconnectivity.weights"):
        seats, unknown = seats_for_types(types)

    assert seats.tolist() == [180, DEFAULT_SEATS, DEFAULT_SEATS]
    assert unknown == []
    assert caplog.text == ""


def test_aggregate_edges_sums_frequency_per_route() -> None:
    edges = aggregate_edges(_flights(), weight="frequency")

    assert edges.columns.tolist() == ["adep", "ades", "Weight"]
    egll_lfpg = edges[(edges.adep == "EGLL") & (edges.ades == "LFPG")].iloc[0]
    assert egll_lfpg["Weight"] == 2
    assert len(edges) == 2


def test_aggregate_edges_sums_seats_per_route() -> None:
    edges = aggregate_edges(_flights(), weight="seats")
    egll_lfpg = edges[(edges.adep == "EGLL") & (edges.ades == "LFPG")].iloc[0]
    assert egll_lfpg["Weight"] == 180 + 396


def test_aggregate_edges_supports_extra_grouping_columns() -> None:
    df = _flights()
    df["window"] = ["2024-03-01", "2024-03-02", "2024-03-01"]
    edges = aggregate_edges(df, weight="frequency", by=("adep", "ades", "window"))

    assert set(edges.columns) == {"adep", "ades", "window", "Weight"}
    # EGLL->LFPG split across two windows, so no aggregated pair survives.
    assert (edges["Weight"] == 1).all()
    assert len(edges) == 3


def test_invalid_weight_mode_raises() -> None:
    with pytest.raises(ValueError, match="weight must be one of"):
        add_edge_weights(_flights(), weight="onwards")


def test_invalid_distance_source_raises() -> None:
    with pytest.raises(ValueError, match="distance source must be one of"):
        flight_distance_km(_flights(), source="flown")
