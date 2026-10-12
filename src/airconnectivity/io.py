"""Loading EUROCONTROL R&D flight files.

Two layers live here:

* the low-level chunked CSV readers ported from ``airctools.py`` (2021), used
  for the legacy "processed" files; and
* the period-oriented :func:`discover_periods` / :func:`load_flights` API that
  reads the gzipped ``<root>/<YYYYMM>/Flights_*.csv.gz`` files in place, applies
  the passenger filters and returns a typed DataFrame with snake_case columns.

Nothing here ever writes data or row-level extracts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .config import DEFAULT_FLIGHT_TYPES, DEFAULT_MARKET_SEGMENTS, Config

#: Column names of the EUROCONTROL ``Flights_*.csv`` files (header is skipped).
HEADER: list[str] = [
    "ECTRL_ID",
    "ADEP",
    "ADEP_Latitude",
    "ADEP_Longitude",
    "ADES",
    "ADES_Latitude",
    "ADES_Longitude",
    "FILED_OFF_BLOCK_TIME",
    "FILED_ARRIVAL_TIME",
    "ACTUAL_OFF_BLOCK_TIME",
    "ACTUAL_ARRIVAL_TIME",
    "AC_Type",
    "AC_Operator",
    "AC_Registration",
    "ICAO_Flight_Type",
    "STATFOR_Market_Segment",
    "Requested_FL",
    "Actual_Distance_Flown",
]

#: Map of EUROCONTROL column names to snake_case output names.
COLUMNS: dict[str, str] = {
    "ECTRL_ID": "ectrl_id",
    "ADEP": "adep",
    "ADEP_Latitude": "adep_latitude",
    "ADEP_Longitude": "adep_longitude",
    "ADES": "ades",
    "ADES_Latitude": "ades_latitude",
    "ADES_Longitude": "ades_longitude",
    "FILED_OFF_BLOCK_TIME": "filed_off_block_time",
    "FILED_ARRIVAL_TIME": "filed_arrival_time",
    "ACTUAL_OFF_BLOCK_TIME": "actual_off_block_time",
    "ACTUAL_ARRIVAL_TIME": "actual_arrival_time",
    "AC_Type": "ac_type",
    "AC_Operator": "ac_operator",
    "AC_Registration": "ac_registration",
    "ICAO_Flight_Type": "icao_flight_type",
    "STATFOR_Market_Segment": "statfor_market_segment",
    "Requested_FL": "requested_fl",
    "Actual_Distance_Flown": "actual_distance_flown",
}

#: Timestamp columns, in both snake_case names.
_DATETIME_COLUMNS = [
    "filed_off_block_time",
    "filed_arrival_time",
    "actual_off_block_time",
    "actual_arrival_time",
]

#: Which off-block/arrival pair a ``time_basis`` selects, as snake_case names.
TIME_BASES: dict[str, tuple[str, str]] = {
    "actual": ("actual_off_block_time", "actual_arrival_time"),
    "filed": ("filed_off_block_time", "filed_arrival_time"),
}

#: Legacy loaders parse dates at read time; these are the raw column names.
_RAW_DATETIME_COLUMNS = [
    "FILED_OFF_BLOCK_TIME",
    "FILED_ARRIVAL_TIME",
    "ACTUAL_OFF_BLOCK_TIME",
    "ACTUAL_ARRIVAL_TIME",
]

_NUMERIC_COLUMNS = [
    "adep_latitude",
    "adep_longitude",
    "ades_latitude",
    "ades_longitude",
    "requested_fl",
    "actual_distance_flown",
]

_STRIP_COLUMNS = [
    "adep",
    "ades",
    "ac_type",
    "icao_flight_type",
    "statfor_market_segment",
]

_CATEGORY_COLUMNS = {
    "STATFOR_Market_Segment": "category",
    "AC_Type": "category",
    "ICAO_Flight_Type": "category",
    "ADES": "category",
    "ADEP": "category",
}

_CHUNK_SIZE = 50_000

_PERIOD_RE = re.compile(r"^\d{6}$")


def _read_chunks(path: Path, names: list[str], load_rows: int | None) -> pd.DataFrame:
    """Read a CSV in chunks and concatenate, preserving the original logging."""
    chunks: list[pd.DataFrame] = []
    reader = pd.read_csv(
        path,
        parse_dates=[c for c in names if c in _RAW_DATETIME_COLUMNS],
        dayfirst=True,
        names=names,
        skiprows=1,
        chunksize=_CHUNK_SIZE,
        nrows=load_rows,
        dtype={k: v for k, v in _CATEGORY_COLUMNS.items() if k in names},
    )
    for index, chunk in enumerate(reader):
        print("Chunk:", index)
        print("Chunk:", chunk.shape)
        chunks.append(chunk)
    return pd.concat(chunks)


def load_raw_ectl_flights(
    config: Config,
    filter_market: list[str] | None = None,
) -> pd.DataFrame:
    """Load an unprocessed EUROCONTROL flight file, optionally filtered by market."""
    path = config.data_root / str(config.data_file)
    airc_df = _read_chunks(path, HEADER, config.load_rows)
    print("File contains: ", airc_df.shape)

    if filter_market:
        airc_df = airc_df[airc_df.STATFOR_Market_Segment.isin(filter_market)]
        print("Filtering for ", filter_market, " Final Size ", airc_df.shape)
    return airc_df


def load_raw_processed_flights(
    config: Config,
    filter_market: list[str] | None = None,
) -> pd.DataFrame:
    """Load a previously processed (weighted) flight file."""
    names = [*HEADER, "Weight"]
    path = config.data_root / str(config.data_file)
    airc_df = _read_chunks(path, names, config.load_rows)
    print("File contains: ", airc_df.shape)

    if filter_market:
        airc_df = airc_df[airc_df.STATFOR_Market_Segment.isin(list(DEFAULT_MARKET_SEGMENTS))]
        print("Filtering for ", filter_market, " Final Size ", airc_df.shape)
    return airc_df


def discover_periods(root: str | Path) -> list[str]:
    """Return the sorted ``YYYYMM`` period folders under ``root``.

    Non-numeric folders (``candidates/``, ``shared/``, ...) are skipped.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir() and _PERIOD_RE.match(entry.name))


def _period_files(root: Path, period: str) -> list[Path]:
    """The ``Flights_*.csv.gz`` files for one period, sorted."""
    return sorted((root / period).glob("Flights_*.csv.gz"))


def _read_period_file(path: Path, chunksize: int) -> pd.DataFrame:
    """Read one gzipped flight file in chunks, without parsing dates yet."""
    chunks = [chunk for chunk in pd.read_csv(path, names=HEADER, skiprows=1, chunksize=chunksize)]
    if not chunks:
        return pd.DataFrame(columns=HEADER)
    return pd.concat(chunks, ignore_index=True)


def _to_typed_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename to snake_case, parse UTC datetimes and coerce numeric columns."""
    df = raw.rename(columns=COLUMNS)

    for column in _DATETIME_COLUMNS:
        df[column] = pd.to_datetime(df[column], errors="coerce", dayfirst=True, utc=True)

    for column in _STRIP_COLUMNS:
        df[column] = df[column].astype("string").str.strip()

    for column in _NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return df


def load_flights(
    root: str | Path,
    periods: list[str] | None = None,
    market_segments: tuple[str, ...] | list[str] = DEFAULT_MARKET_SEGMENTS,
    flight_types: tuple[str, ...] | list[str] = DEFAULT_FLIGHT_TYPES,
    time_basis: str = "actual",
    chunksize: int = _CHUNK_SIZE,
) -> pd.DataFrame:
    """Load passenger flights for ``periods`` from ``<root>/<YYYYMM>/Flights_*.csv.gz``.

    The gz files are read in place, in chunks; no extract is ever written.

    Parameters
    ----------
    root:
        Data root holding the ``YYYYMM`` folders.
    periods:
        Periods to load; defaults to every folder returned by
        :func:`discover_periods`.
    market_segments:
        STATFOR market segments to keep. Defaults to the passenger segments
        Mainline, Regional, Low-Cost and Charter.
    flight_types:
        ICAO flight types to keep. Defaults to ``("S",)`` (scheduled). Note the
        type filter is applied *in addition to* the segment filter, so Charter
        flights (type ``N``) need ``"N"`` added here to survive.
    time_basis:
        ``"actual"`` uses the actual off-block/arrival times, ``"filed"`` the
        filed ones. Both are parsed as UTC.
    chunksize:
        Rows read per chunk.

    Returns
    -------
    DataFrame with snake_case columns, UTC datetimes, and ``off_block_time`` /
    ``arrival_time`` selected from ``time_basis``. Rows missing ADEP, ADES or the
    selected times, and rows with ADEP == ADES, are dropped.
    """
    if time_basis not in TIME_BASES:
        raise ValueError(f"time_basis must be one of {sorted(TIME_BASES)}, got {time_basis!r}")

    root = Path(root)
    if periods is None:
        periods = discover_periods(root)

    frames = [
        _read_period_file(path, chunksize)
        for period in periods
        for path in _period_files(root, period)
    ]
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=HEADER)

    df = _to_typed_frame(raw)

    off_column, arrival_column = TIME_BASES[time_basis]
    df["off_block_time"] = df[off_column]
    df["arrival_time"] = df[arrival_column]

    df = df[df["icao_flight_type"].isin(list(flight_types))]
    df = df[df["statfor_market_segment"].isin(list(market_segments))]
    df = df.dropna(subset=["adep", "ades", "off_block_time", "arrival_time"])
    df = df[df["adep"] != df["ades"]]

    return df.reset_index(drop=True)


def summarise_flights(df: pd.DataFrame) -> dict[str, object]:
    """Aggregate counts per market segment and flight type (no row-level data)."""
    return {
        "rows": int(len(df)),
        "by_market_segment": {str(k): int(v) for k, v in df["statfor_market_segment"].value_counts().items()},
        "by_flight_type": {str(k): int(v) for k, v in df["icao_flight_type"].value_counts().items()},
    }
