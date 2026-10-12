"""Explicit configuration, replacing the global ``settings`` module.

The 2021 scripts mutated a module-level ``settings`` dict at import time. That
made the code impossible to import twice with different options and impossible to
test in isolation. All tunables now live in this dataclass and are passed
explicitly to the functions that need them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Market segments kept when filtering for passenger flights. These are the
#: post-2022 EUROCONTROL segment rules (retroactive to 2019), which is what the
#: 2020+ data uses.
DEFAULT_MARKET_SEGMENTS: tuple[str, ...] = (
    "Mainline",
    "Regional",
    "Low-Cost",
    "Charter",
)

#: ICAO flight type marking a scheduled/passenger flight.
DEFAULT_FLIGHT_TYPES: tuple[str, ...] = ("S",)


@dataclass
class Config:
    """Runtime configuration for loading and analysing flights.

    Attributes mirror the keys the old ``settings`` dict used, with the same
    defaults, but every field is explicit and overridable.
    """

    #: Root directory holding ``<YYYYMM>/`` data folders. Never hard-code a path;
    #: callers pass it in (CLI ``--data-root`` or ``AIRCONN_DATA_ROOT``).
    data_root: Path = Path("data")

    #: ``"raw"`` for EUROCONTROL files, ``"processed"`` for a previously weighted CSV.
    data_source: str = "raw"

    #: File name to load, relative to :attr:`data_root`.
    data_file: str | None = None

    #: Edge weight scheme: ``"simple"``, ``"onwards"`` or ``"seats"``.
    edge_weight: str = "onwards"

    #: Keep only a sample of days from the period instead of the whole file.
    sample: bool = True
    start_day: int = 0
    sample_size: int = 14

    #: Maximum number of rows to read; ``None`` reads everything.
    load_rows: int | None = 1_000_000

    #: Connection layover bounds in minutes.
    min_layover: int = 30
    max_layover: int = 240

    def __post_init__(self) -> None:
        # Accept str paths for convenience (CLI, tests).
        if not isinstance(self.data_root, Path):
            self.data_root = Path(self.data_root)
