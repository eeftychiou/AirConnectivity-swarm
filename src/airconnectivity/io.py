"""Loading EUROCONTROL R&D flight files.

Ported from ``airctools.py`` (2021). Issue #2 builds the period-discovery and
filtered-loader API on top of this; here we keep the original chunked CSV
reading behaviour, made path-relative to :class:`~airconnectivity.config.Config`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DEFAULT_MARKET_SEGMENTS, Config

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

#: Columns parsed as datetimes; ``dayfirst`` matches the EUROCONTROL export.
_DATETIME_COLUMNS = [
    "FILED_OFF_BLOCK_TIME",
    "FILED_ARRIVAL_TIME",
    "ACTUAL_OFF_BLOCK_TIME",
    "ACTUAL_ARRIVAL_TIME",
]

_CATEGORY_COLUMNS = {
    "STATFOR_Market_Segment": "category",
    "AC_Type": "category",
    "ICAO_Flight_Type": "category",
    "ADES": "category",
    "ADEP": "category",
}

_CHUNK_SIZE = 50_000


def _read_chunks(path: Path, names: list[str], load_rows: int | None) -> pd.DataFrame:
    """Read a CSV in chunks and concatenate, preserving the original logging."""
    chunks: list[pd.DataFrame] = []
    reader = pd.read_csv(
        path,
        parse_dates=_DATETIME_COLUMNS,
        dayfirst=True,
        names=names,
        skiprows=1,
        chunksize=_CHUNK_SIZE,
        nrows=load_rows,
        dtype=_CATEGORY_COLUMNS,
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
