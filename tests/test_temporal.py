"""Tests for temporal connections and temporal PageRank."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest

from airconnectivity.temporal import (
    compare_pagerank,
    connections,
    load_mct_table,
    temporal_pagerank,
)


def _flights(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    """Rows are (adep, ades, off_block_time, arrival_time), all UTC."""
    df = pd.DataFrame(rows, columns=["adep", "ades", "off_block_time", "arrival_time"])
    for column in ("off_block_time", "arrival_time"):
        df[column] = pd.to_datetime(df[column], utc=True)
    df["ac_type"] = "A320"
    return df


def _static_pagerank(flights: pd.DataFrame) -> dict[str, float]:
    edges = flights.groupby(["adep", "ades"]).size().reset_index(name="Weight")
    graph = nx.from_pandas_edgelist(edges, source="adep", target="ades", edge_attr="Weight", create_using=nx.DiGraph())
    return dict(nx.pagerank(graph, alpha=0.85, weight="Weight"))


def test_connections_mct_boundary() -> None:
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),  # arrives 09:00
            ("HUB", "BBB", "2024-03-01 09:44:00", "2024-03-01 11:00:00"),  # 44 min -> too short
            ("HUB", "CCC", "2024-03-01 09:45:00", "2024-03-01 11:00:00"),  # 45 min -> ok
        ]
    )
    result = connections(flights, mct=45, max_wait=360)

    pairs = set(zip(result["a_idx"], result["b_idx"], strict=True))
    assert (0, 2) in pairs  # AAA->HUB connects to the 45-minute onward flight
    assert (0, 1) not in pairs  # but not the 44-minute one
    assert result[result["b_idx"] == 2]["wait"].iloc[0] == pytest.approx(45.0)


def test_connections_max_wait_boundary() -> None:
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),
            ("HUB", "BBB", "2024-03-01 15:00:00", "2024-03-01 16:00:00"),  # 360 min -> ok
            ("HUB", "CCC", "2024-03-01 15:01:00", "2024-03-01 16:00:00"),  # 361 min -> too long
        ]
    )
    result = connections(flights, mct=45, max_wait=360)
    connected = set(result["b_idx"])
    assert 1 in connected
    assert 2 not in connected


def test_connections_respects_per_airport_mct_dict() -> None:
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),
            ("HUB", "BBB", "2024-03-01 09:30:00", "2024-03-01 11:00:00"),  # 30 min
        ]
    )
    assert not connections(flights, mct=45).shape[0]
    assert connections(flights, mct=45, mct_overrides={"HUB": 20}).shape[0] == 1


def test_load_mct_table(tmp_path: pytest.TempPathFactory) -> None:
    path = tmp_path / "mct.csv"  # type: ignore[operator]
    path.write_text("airport,mct_minutes\nEGLL,30\nKJFK,25\n", encoding="utf-8")
    assert load_mct_table(path) == {"EGLL": 30, "KJFK": 25}


def test_temporal_pagerank_is_deterministic() -> None:
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),
            ("HUB", "BBB", "2024-03-01 09:45:00", "2024-03-01 11:00:00"),
            ("CCC", "HUB", "2024-03-01 07:30:00", "2024-03-01 09:10:00"),
        ]
    )
    assert temporal_pagerank(flights) == temporal_pagerank(flights)


def test_temporal_pagerank_normalized_and_covers_nodes() -> None:
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),
            ("HUB", "BBB", "2024-03-01 09:45:00", "2024-03-01 11:00:00"),
        ]
    )
    ranks = temporal_pagerank(flights)
    assert set(ranks) == {"AAA", "HUB", "BBB"}
    assert sum(ranks.values()) == pytest.approx(1.0)


def test_hub_without_feasible_connections_propagates_no_onward_mass() -> None:
    # Same flights, only the MCT differs: with 45 min the HUB connection is
    # feasible and mass reaches BBB; with a huge MCT nothing passes through.
    flights = _flights(
        [
            ("AAA", "HUB", "2024-03-01 07:00:00", "2024-03-01 09:00:00"),
            ("HUB", "BBB", "2024-03-01 09:45:00", "2024-03-01 11:00:00"),
        ]
    )
    feasible = temporal_pagerank(flights, mct=45)
    blocked = temporal_pagerank(flights, mct=1000)

    # BBB only receives fresh-start mass when the connection is blocked; the
    # onward (propagated) mass makes it rank higher when the connection is feasible.
    assert feasible["BBB"] > blocked["BBB"]


def test_hub_ranks_lower_temporally_when_connections_are_infeasible() -> None:
    # Each inbound flight into HUB is itself reached through a feasible feeder
    # connection of 60 minutes. With MCT 30 the feeders connect and boost the
    # mass flowing into HUB; with MCT 100 nothing connects, so HUB drops.
    rows: list[tuple[str, str, str, str]] = []
    for i in range(4):
        rows.append((f"F{i}", f"G{i}", f"2024-03-01 06:{i * 5:02d}:00", f"2024-03-01 07:{i * 5:02d}:00"))
        rows.append((f"G{i}", "HUB", f"2024-03-01 08:{i * 5:02d}:00", f"2024-03-01 09:{i * 5:02d}:00"))
        rows.append(("HUB", f"X{i}", f"2024-03-01 10:{i * 5:02d}:00", f"2024-03-01 11:{i * 5:02d}:00"))
    flights = _flights(rows)

    static = _static_pagerank(flights)
    connected = temporal_pagerank(flights, mct=30)
    blocked = temporal_pagerank(flights, mct=100)

    assert max(static, key=static.get) == "HUB"  # HUB is the static hub
    assert connected["HUB"] > blocked["HUB"]  # but its temporal mass needs the connections


def test_compare_pagerank_identical_and_reversed() -> None:
    same = {"A": 0.5, "B": 0.3, "C": 0.2}
    identical = compare_pagerank(same, dict(same), k=3)
    assert identical.spearman == pytest.approx(1.0)
    assert identical.kendall == pytest.approx(1.0)
    assert identical.top_k_overlap == pytest.approx(1.0)

    reversed_ranks = compare_pagerank({"A": 0.2, "B": 0.3, "C": 0.5}, same, k=1)
    assert reversed_ranks.spearman == pytest.approx(-1.0)
    assert reversed_ranks.top_k_overlap == pytest.approx(0.0)


def test_temporal_pagerank_argument_validation() -> None:
    flights = _flights([("A", "B", "2024-03-01 06:00:00", "2024-03-01 07:00:00")])
    with pytest.raises(ValueError, match="alpha"):
        temporal_pagerank(flights, alpha=1.0)
    with pytest.raises(ValueError, match="beta"):
        temporal_pagerank(flights, beta=0.0)
