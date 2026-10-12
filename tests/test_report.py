"""Tests for the ranking outputs and the month-comparison report (issue #6)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

from airconnectivity import cli
from airconnectivity.report import build_report, rank_airports, write_rankings

HEADER_LINE = (
    '"ECTRL ID","ADEP","ADEP Latitude","ADEP Longitude","ADES","ADES Latitude",'
    '"ADES Longitude","FILED OFF BLOCK TIME","FILED ARRIVAL TIME","ACTUAL OFF BLOCK TIME",'
    '"ACTUAL ARRIVAL TIME","AC Type","AC Operator","AC Registration","ICAO Flight Type",'
    '"STATFOR Market Segment","Requested FL","Actual Distance Flown (nm)"'
)

RANKING_COLUMNS = ["airport", "rank", "score", "window", "weight"]


def _row(adep: str, ades: str, off: str, arr: str, ac_type: str = "A320", market: str = "Mainline") -> list[str]:
    return [
        "1234", adep, "51.47", "-0.46", ades, "49.0", "2.5",
        off, arr, off, arr,
        ac_type, "BAW", "G-ABCD", "S", market, "FL350", "220",
    ]


def _write_period(root: Path, period: str, rows: list[list[str]]) -> Path:
    folder = root / period
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Flights_{period}01_{period}28.csv.gz"
    with gzip.open(path, "wt", newline="\n") as handle:
        handle.write(HEADER_LINE + "\n")
        for row in rows:
            handle.write(",".join(row) + "\n")
    return path


def _fixture_rows(day: str) -> list[list[str]]:
    return [
        _row("EGLL", "LFPG", f"{day}/03/2024 06:00:00", f"{day}/03/2024 07:30:00"),
        _row("LFPG", "EHAM", f"{day}/03/2024 08:30:00", f"{day}/03/2024 09:40:00"),
        _row("EHAM", "EGLL", f"{day}/03/2024 10:30:00", f"{day}/03/2024 11:40:00"),
        _row("EGLL", "EHAM", f"{day}/03/2024 13:00:00", f"{day}/03/2024 14:30:00"),
        _row("LFPG", "EDDF", f"{day}/03/2024 15:00:00", f"{day}/03/2024 16:00:00"),
        _row("EDDF", "LFPG", f"{day}/03/2024 17:00:00", f"{day}/03/2024 18:00:00"),
    ]


def _flights_frame(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["adep", "ades", "off_block_time", "arrival_time"])
    for column in ("off_block_time", "arrival_time"):
        df[column] = pd.to_datetime(df[column], utc=True)
    df["ac_type"] = "A320"
    return df


def test_rank_airports_columns_and_per_window_ranks() -> None:
    flights = _flights_frame(
        [
            ("EGLL", "LFPG", "2024-03-01 06:00:00", "2024-03-01 07:30:00"),
            ("LFPG", "EHAM", "2024-03-01 08:30:00", "2024-03-01 09:40:00"),
            ("EGLL", "EHAM", "2024-03-02 06:00:00", "2024-03-02 07:30:00"),
            ("EHAM", "EGLL", "2024-03-02 08:30:00", "2024-03-02 09:40:00"),
        ]
    )
    frames = rank_airports(flights, freq="D", weight="frequency", method="both")

    assert set(frames) == {"static", "temporal"}
    for frame in frames.values():
        assert frame.columns.tolist() == RANKING_COLUMNS
        # Day 1 has three airports (EGLL/LFPG/EHAM), day 2 has two (EGLL/EHAM).
        counts = frame.groupby("window").size().sort_index().tolist()
        assert counts == [3, 2]
        assert (frame.groupby("window")["rank"].min() == 1).all()


def test_rank_airports_method_selection() -> None:
    flights = _flights_frame([("A", "B", "2024-03-01 06:00:00", "2024-03-01 07:00:00")])
    assert set(rank_airports(flights, method="static")) == {"static"}
    assert set(rank_airports(flights, method="temporal")) == {"temporal"}
    with pytest.raises(ValueError, match="method"):
        rank_airports(flights, method="nope")


def test_write_rankings_creates_named_files(tmp_path: Path) -> None:
    flights = _flights_frame([("A", "B", "2024-03-01 06:00:00", "2024-03-01 07:00:00")])
    paths = write_rankings(flights, tmp_path, "202403", freq="M", weight="seats", method="both")

    names = {path.name for path in paths}
    assert names == {"rankings_202403_M_static.csv", "rankings_202403_M_temporal.csv"}
    assert all(path.exists() for path in paths)


def test_write_rankings_excludes_adjacent_month_windows(tmp_path: Path) -> None:
    # A real export contains a few flights whose UTC departure falls in the
    # adjacent month; those partial windows must not be written for 202403.
    flights = _flights_frame(
        [
            ("EGLL", "LFPG", "2024-02-29 23:35:00", "2024-03-01 01:00:00"),
            ("EGLL", "LFPG", "2024-03-10 06:00:00", "2024-03-10 07:30:00"),
            ("LFPG", "EHAM", "2024-03-20 08:30:00", "2024-03-20 09:40:00"),
            ("EHAM", "EGLL", "2024-04-01 01:00:00", "2024-04-01 02:00:00"),
        ]
    )
    paths = write_rankings(flights, tmp_path, "202403", freq="M", weight="frequency", method="temporal")

    frame = pd.read_csv(paths[0])
    labels = pd.to_datetime(frame["window"], utc=True).dt.strftime("%Y%m").unique().tolist()
    assert labels == ["202403"]
    assert len(frame) == 3  # EGLL, LFPG, EHAM in the March window only


def test_build_report_without_rankings(tmp_path: Path) -> None:
    path = build_report(tmp_path / "empty", tmp_path / "report.md")
    assert "No rankings found" in path.read_text(encoding="utf-8")


def test_end_to_end_rank_and_report(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    out = tmp_path / "outputs"
    _write_period(data_root, "202403", _fixture_rows("01") + _fixture_rows("02"))
    _write_period(data_root, "202404", _fixture_rows("01") + _fixture_rows("03"))

    assert (
        cli.main(
            [
                "rank",
                "--data-root", str(data_root),
                "--periods", "202403,202404",
                "--window", "M",
                "--weight", "seats",
                "--method", "both",
                "--out", str(out),
            ]
        )
        == 0
    )

    expected = [
        out / "rankings_202403_M_static.csv",
        out / "rankings_202403_M_temporal.csv",
        out / "rankings_202404_M_static.csv",
        out / "rankings_202404_M_temporal.csv",
    ]
    for path in expected:
        assert path.exists()

    frame = pd.read_csv(expected[0])
    assert frame.columns.tolist() == RANKING_COLUMNS
    # Aggregated airport-level results only, never flight rows.
    assert not {"adep", "ades", "off_block_time", "arrival_time"} & set(frame.columns)
    assert set(frame["airport"]) <= {"EGLL", "LFPG", "EHAM", "EDDF"}

    report_path = out / "report.md"
    assert cli.main(["report", "--rankings", str(out), "--out", str(report_path)]) == 0
    text = report_path.read_text(encoding="utf-8")
    assert "Top 20 per month" in text
    assert "Biggest movers between months" in text
    assert "Static vs temporal PageRank correlation" in text
    assert "202403" in text and "202404" in text
