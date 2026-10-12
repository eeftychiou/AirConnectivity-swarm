"""Tests for the EUROCONTROL period discovery and filtered loader.

A small synthetic gz fixture is built inside the tests; no real data is used.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest

from airconnectivity import cli
from airconnectivity.io import discover_periods, load_flights, summarise_flights

HEADER_LINE = (
    '"ECTRL ID","ADEP","ADEP Latitude","ADEP Longitude","ADES","ADES Latitude",'
    '"ADES Longitude","FILED OFF BLOCK TIME","FILED ARRIVAL TIME","ACTUAL OFF BLOCK TIME",'
    '"ACTUAL ARRIVAL TIME","AC Type","AC Operator","AC Registration","ICAO Flight Type",'
    '"STATFOR Market Segment","Requested FL","Actual Distance Flown (nm)"'
)


def _row(
    adep: str = "EGLL",
    ades: str = "LFPG",
    market: str = "Mainline",
    flight_type: str = "S",
    filed_off: str = "01/03/2024 06:00:00",
    filed_arr: str = "01/03/2024 08:00:00",
    actual_off: str = "01/03/2024 06:05:00",
    actual_arr: str = "01/03/2024 08:05:00",
) -> list[str]:
    return [
        "1234", adep, "51.47", "-0.46", ades, "49.0", "2.5",
        filed_off, filed_arr, actual_off, actual_arr,
        "A320", "BAW", "G-ABCD", flight_type, market, "FL350", "220",
    ]


def _fixture_rows() -> list[list[str]]:
    return [
        _row(),                                                        # 1 keep (Mainline)
        _row(adep="EGKK", ades="EHAM", market="Low-Cost"),             # 2 keep
        _row(adep="LIRF", ades="LIPZ", market="Regional"),             # 3 keep
        _row(adep="EGKK", ades="LGAV", market="Charter", flight_type="N"),   # 4 excluded: type N
        _row(adep="EDDF", ades="KJFK", market="All-Cargo"),            # 5 excluded: segment
        _row(adep="LSZH", market="Business Aviation"),                 # 6 excluded: segment
        _row(adep="LEMD", market="Military"),                          # 7 excluded: segment
        _row(adep="LPPT", market="Other"),                             # 8 excluded: segment
        _row(adep="EGBB", ades="EIDW", actual_arr=""),                 # 9 dropped: no arrival
        _row(adep="EGCC", ades="EIDW", actual_off=""),                 # 10 dropped: no off-block
        _row(adep="", ades="EIDW"),                                    # 11 dropped: no ADEP
        _row(adep="EGGW", ades=""),                                    # 12 dropped: no ADES
        _row(adep="EGLL", ades="EGLL"),                                # 13 dropped: ADEP == ADES
        _row(adep="EGPH", ades="EINN", filed_off="", filed_arr=""),    # 14 kept on actual only
        _row(adep="EGSS", ades="EDDM"),                                # 15 keep
        _row(adep="EGGD", ades="LOWW"),                                # 16 keep
        _row(adep="EGNX", ades="EKCH"),                                # 17 keep
        _row(adep="EGPF", ades="ENGM"),                                # 18 keep
        _row(adep="EGFF", ades="ESSA"),                                # 19 keep
        _row(adep="EGHH", ades="EFHK"),                                # 20 keep
    ]


def _write_fixture(root: Path, period: str, rows: list[list[str]]) -> Path:
    folder = root / period
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Flights_{period}01_{period}28.csv.gz"
    with gzip.open(path, "wt", newline="\n") as handle:
        handle.write(HEADER_LINE + "\n")
        for row in rows:
            handle.write(",".join(row) + "\n")
    return path


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    _write_fixture(tmp_path, "202403", _fixture_rows())
    _write_fixture(tmp_path, "202406", _fixture_rows()[:3])
    return tmp_path


def test_default_filter_keeps_historical_and_unclassified_labels(tmp_path: Path) -> None:
    rows = [
        _row(market="Traditional Scheduled"),
        _row(market="Lowcost"),
        _row(market="Regional Aircraft"),
        _row(market="Not Classified"),
        _row(market="All-Cargo"),  # still excluded
        _row(market="Business Aviation"),  # still excluded
    ]
    _write_fixture(tmp_path, "202003", rows)

    df = load_flights(tmp_path, periods=["202003"])

    assert set(df["statfor_market_segment"]) == {
        "Traditional Scheduled",
        "Lowcost",
        "Regional Aircraft",
        "Not Classified",
    }


def test_load_flights_handles_nested_period_layout(tmp_path: Path) -> None:
    # Some exports nest the archive: <root>/202403/202403/Flights_*.csv.gz
    nested = tmp_path / "202403" / "202403"
    nested.mkdir(parents=True)
    path = nested / "Flights_20240301_20240331.csv.gz"
    with gzip.open(path, "wt", newline="\n") as handle:
        handle.write(HEADER_LINE + "\n")
        handle.write(",".join(_row()) + "\n")

    assert discover_periods(tmp_path) == ["202403"]
    assert len(load_flights(tmp_path, periods=["202403"])) == 1


def test_discover_periods_lists_numeric_folders_and_skips_others(data_root: Path) -> None:
    for name in ("candidates", "shared", "submissions"):
        (data_root / name).mkdir()
    (data_root / "README.txt").write_text("not a period")

    assert discover_periods(data_root) == ["202403", "202406"]


def test_discover_periods_missing_root_is_empty(tmp_path: Path) -> None:
    assert discover_periods(tmp_path / "nope") == []


def test_load_flights_applies_default_passenger_filters(data_root: Path) -> None:
    df = load_flights(data_root, periods=["202403"])

    # 20 rows in, 10 kept (see the fixture comments above).
    assert len(df) == 10
    assert set(df["statfor_market_segment"]) == {"Mainline", "Low-Cost", "Regional"}
    assert set(df["icao_flight_type"]) == {"S"}
    assert (df["adep"] != df["ades"]).all()
    assert df[["adep", "ades", "off_block_time", "arrival_time"]].notna().all().all()


def test_load_flights_parses_utc_datetimes(data_root: Path) -> None:
    df = load_flights(data_root, periods=["202403"])

    assert df["off_block_time"].dt.tz is not None
    assert df["arrival_time"].dt.tz is not None
    first = df.iloc[0]
    assert first["off_block_time"] == pd.Timestamp("2024-03-01 06:05:00", tz="UTC")
    assert first["arrival_time"] == pd.Timestamp("2024-03-01 08:05:00", tz="UTC")


def test_time_basis_filed_uses_filed_times(data_root: Path) -> None:
    actual = load_flights(data_root, periods=["202403"], time_basis="actual")
    filed = load_flights(data_root, periods=["202403"], time_basis="filed")

    assert len(actual) == 10
    # Rows 9/10 have filed but no actual times -> only filed keeps them;
    # row 14 has actual but no filed times -> only actual keeps it.
    assert len(filed) == 11
    assert filed.iloc[0]["off_block_time"] == pd.Timestamp("2024-03-01 06:00:00", tz="UTC")


def test_invalid_time_basis_raises(data_root: Path) -> None:
    with pytest.raises(ValueError, match="time_basis"):
        load_flights(data_root, periods=["202403"], time_basis="estimate")


def test_configurable_filters_include_cargo_and_charter(data_root: Path) -> None:
    df = load_flights(
        data_root,
        periods=["202403"],
        market_segments=["Charter", "All-Cargo"],
        flight_types=["N", "S"],
    )
    # Charter/N and All-Cargo/S both survive when both filters allow them.
    assert set(df["statfor_market_segment"]) == {"Charter", "All-Cargo"}
    assert len(df) == 2


def test_load_flights_all_discovered_periods(data_root: Path) -> None:
    df = load_flights(data_root)
    assert len(df) == 10 + 3


def test_chunked_reading_matches_single_chunk(data_root: Path) -> None:
    chunked = load_flights(data_root, periods=["202403"], chunksize=2)
    whole = load_flights(data_root, periods=["202403"], chunksize=50_000)
    pd.testing.assert_frame_equal(chunked, whole)


def test_loader_writes_no_files(data_root: Path) -> None:
    before = {p.relative_to(data_root) for p in data_root.rglob("*")}
    load_flights(data_root, periods=["202403"])
    after = {p.relative_to(data_root) for p in data_root.rglob("*")}
    assert before == after


def test_summarise_flights_is_aggregate_only(data_root: Path) -> None:
    df = load_flights(data_root, periods=["202403"])
    summary = summarise_flights(df)

    assert summary["rows"] == 10
    assert summary["by_flight_type"] == {"S": 10}
    assert summary["by_market_segment"] == {"Mainline": 8, "Low-Cost": 1, "Regional": 1}


def test_cli_load_summary(data_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["--data-root", str(data_root), "load", "--period", "202403", "--summary"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "rows: 10" in out
    assert "Mainline: 8" in out
    assert "Regional: 1" in out


def test_cli_load_without_summary_omits_breakdown(
    data_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["--data-root", str(data_root), "load", "--period", "202403"])
    out = capsys.readouterr().out
    assert "rows: 10" in out
    assert "by market segment" not in out
