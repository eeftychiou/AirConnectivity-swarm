"""Edge weighting schemes.

Two families live here:

* :func:`add_weights` — the original "onwards connectivity" weighting ported
  from ``airctools.add_weights`` (2021); and
* the issue #3 modes :func:`add_edge_weights` / :func:`aggregate_edges`, which
  weight each flight by frequency, great-circle distance or estimated seats and
  aggregate flights into directed ``(ADEP, ADES)`` edges.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from importlib import resources
from typing import Literal

import pandas as pd

from .geo import gcd

logger = logging.getLogger(__name__)

#: Distance of one nautical mile in kilometres.
_NM_TO_KM = 1.852

#: Supported edge-weight modes.
WeightMode = Literal["frequency", "unweighted", "distance", "seats"]
WEIGHT_MODES: tuple[str, ...] = ("frequency", "unweighted", "distance", "seats")

#: Distance source for the ``distance`` mode.
DISTANCE_SOURCES: tuple[str, ...] = ("gcd", "actual")

#: Fallback seat count used when a designator's category cannot be inferred.
DEFAULT_SEATS = 150

#: Per-category fallback seat counts for designators not in the lookup table.
#: ``unknown`` is the row-level fallback for a designator whose family cannot be
#: inferred, so every flight resolves to a category default.
CATEGORY_DEFAULTS: dict[str, int] = {
    "narrowbody": 180,
    "widebody": 300,
    "regional_jet": 100,
    "turboprop": 70,
    "unknown": DEFAULT_SEATS,
}

#: Category used when a designator's family cannot be inferred.
UNKNOWN_CATEGORY = "unknown"

#: Manufacturer/model families used to infer a category for an unknown
#: designator, checked in order (specific families first). Lets an off-table type
#: like ``B77L`` (widebody) or ``E145`` (regional jet) fall back to the right
#: category default instead of one global value.
CATEGORY_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    # Airbus
    (("A318", "A319", "A320", "A321", "A19N", "A20N", "A21N", "A220", "BCS1", "BCS3"), "narrowbody"),
    (
        (
            "A300", "A310", "A330", "A331", "A332", "A333", "A337", "A338", "A339",
            "A340", "A342", "A343", "A345", "A346", "A350", "A358", "A359", "A35K",
            "A380", "A388",
        ),
        "widebody",
    ),
    # Boeing
    (
        (
            "B731", "B732", "B733", "B734", "B735", "B736", "B737", "B738", "B739",
            "B37M", "B38M", "B39M", "B752", "B753",
        ),
        "narrowbody",
    ),
    (
        (
            "B741", "B742", "B743", "B744", "B748", "B74", "B762", "B763", "B764",
            "B76", "B772", "B773", "B77", "B788", "B789", "B78",
        ),
        "widebody",
    ),
    # Regional jets (Embraer, Bombardier, Fokker)
    (
        ("E13", "E14", "E17", "E19", "E29", "E75", "E190", "E195", "CRJ", "RJ", "F70", "F10", "B717", "B71"),
        "regional_jet",
    ),
    # Turboprops
    (("AT", "DH", "DHC", "SB", "JS", "BE", "E110"), "turboprop"),
)

_SEATS_RESOURCE = ("airconnectivity", "data/ac_type_seats.csv")


@lru_cache(maxsize=1)
def load_seats_table() -> dict[str, tuple[int | None, str]]:
    """Load the committed ICAO type -> (seats, category) lookup from package data."""
    resource = resources.files(_SEATS_RESOURCE[0]).joinpath(_SEATS_RESOURCE[1])
    with resources.as_file(resource) as path:
        table = pd.read_csv(path, comment="#")
    table["icao_type"] = table["icao_type"].astype(str).str.strip().str.upper()
    return {
        row.icao_type: (int(row.seats) if not pd.isna(row.seats) else None, str(row.category).strip())
        for row in table.itertuples(index=False)
    }


def infer_category(designator: str) -> str | None:
    """Infer an aircraft category from a designator's manufacturer/model family."""
    code = designator.strip().upper()
    for prefixes, category in CATEGORY_PREFIXES:
        if code.startswith(prefixes):
            return category
    return None


def category_for(designator: str) -> str:
    """Row-level category for a designator: its inferred family, else ``unknown``."""
    return infer_category(designator) or UNKNOWN_CATEGORY


def seats_for_types(ac_types: pd.Series) -> tuple[pd.Series, list[str]]:
    """Estimate seats per flight from ICAO type designators (row-level fallback).

    Returns the seat counts and the sorted list of unknown designators. A
    designator missing from the lookup is resolved **per row** to a category
    (its inferred family, or :data:`UNKNOWN_CATEGORY`) and takes that category's
    :data:`CATEGORY_DEFAULTS` value. The log reports the number of affected
    flights per category as well as the distinct designators. An empty designator
    uses :data:`DEFAULT_SEATS` without being logged.
    """
    table = load_seats_table()
    normalized = ac_types.astype("string").str.strip().str.upper()

    resolved: list[int] = []
    unknown: set[str] = set()
    affected: dict[str, int] = {}
    for value in normalized:
        if value is None or pd.isna(value) or value == "":
            resolved.append(DEFAULT_SEATS)
            continue
        if value in table:
            seats, category = table[value]
            resolved.append(CATEGORY_DEFAULTS.get(category, DEFAULT_SEATS) if seats is None else int(seats))
            continue
        category = category_for(str(value))
        resolved.append(CATEGORY_DEFAULTS.get(category, DEFAULT_SEATS))
        unknown.add(str(value))
        affected[category] = affected.get(category, 0) + 1

    if unknown:
        breakdown = ", ".join(f"{category}={count}" for category, count in sorted(affected.items()))
        logger.warning(
            "Unknown ICAO aircraft types on %d flights (%d distinct) resolved via category defaults [%s]: %s",
            sum(affected.values()),
            len(unknown),
            breakdown,
            ", ".join(sorted(unknown)),
        )

    return pd.Series(resolved, index=ac_types.index, dtype="int64"), sorted(unknown)


def seats_for_flights(flights: pd.DataFrame, ac_type_column: str = "ac_type") -> pd.Series:
    """Row-level seat estimate for a flights DataFrame, from its ``ac_type`` column."""
    if ac_type_column not in flights.columns:
        raise KeyError(f"column {ac_type_column!r} not in flights")
    seats, _ = seats_for_types(flights[ac_type_column])
    return seats


def _gcd_distance_km(df: pd.DataFrame) -> pd.Series:
    """Great-circle distance in km from the ADEP/ADES coordinates of each flight."""
    return pd.Series(
        [
            gcd((lat1, lon1), (lat2, lon2)) * _NM_TO_KM
            for lat1, lon1, lat2, lon2 in zip(
                df["adep_latitude"],
                df["adep_longitude"],
                df["ades_latitude"],
                df["ades_longitude"],
                strict=True,
            )
        ],
        index=df.index,
        dtype="float64",
    )


def flight_distance_km(df: pd.DataFrame, source: str = "gcd") -> pd.Series:
    """Per-flight distance in km, either great-circle (``gcd``) or ``actual``."""
    if source not in DISTANCE_SOURCES:
        raise ValueError(f"distance source must be one of {DISTANCE_SOURCES}, got {source!r}")
    if source == "actual":
        return pd.to_numeric(df["actual_distance_flown"], errors="coerce") * _NM_TO_KM
    return _gcd_distance_km(df)


def add_edge_weights(
    df: pd.DataFrame,
    weight: str = "frequency",
    distance_source: str = "gcd",
) -> pd.DataFrame:
    """Add a per-flight ``Weight`` column for the chosen scheme.

    * ``frequency`` / ``unweighted`` — every flight counts as 1.
    * ``distance`` — great-circle km (or ``actual_distance_flown`` in km).
    * ``seats`` — estimated seats from the ICAO aircraft type.
    """
    if weight not in WEIGHT_MODES:
        raise ValueError(f"weight must be one of {WEIGHT_MODES}, got {weight!r}")

    out = df.copy()
    if weight in ("frequency", "unweighted"):
        out["Weight"] = 1.0
    elif weight == "distance":
        out["Weight"] = flight_distance_km(out, distance_source)
    else:  # seats
        out["Weight"] = seats_for_flights(out).astype("float64")
    return out


def aggregate_edges(
    df: pd.DataFrame,
    weight: str = "frequency",
    distance_source: str = "gcd",
    by: tuple[str, ...] = ("adep", "ades"),
) -> pd.DataFrame:
    """Aggregate flights into directed edges, summing the chosen weight.

    Pass ``by`` (e.g. ``("adep", "ades", "window")``) to aggregate per time
    window; the default groups by route only.
    """
    weighted = add_edge_weights(df, weight=weight, distance_source=distance_source)
    return weighted.groupby(list(by), as_index=False)["Weight"].sum()


def add_weights(airc_df: pd.DataFrame, min_layover: int, max_layover: int) -> pd.DataFrame:
    """Weight each flight by the onwards connectivity at its destination.

    For every flight the destination airport is checked for onward departures
    between ``min_layover`` and ``max_layover`` minutes after arrival; the count
    (plus one) becomes the ``Weight`` column.
    """
    off_block = airc_df["FILED_OFF_BLOCK_TIME"]

    for i, row in airc_df.iterrows():
        arrival = row["FILED_ARRIVAL_TIME"]
        onward_mask = (
            (airc_df["ADEP"] == row["ADES"])
            & (off_block >= arrival + pd.Timedelta(minutes=min_layover))
            & (off_block <= arrival + pd.Timedelta(minutes=max_layover))
        )
        airc_df.at[i, "Weight"] = int(onward_mask.sum()) + 1

    return airc_df
