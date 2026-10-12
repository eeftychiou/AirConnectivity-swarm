"""Temporal connections and temporal PageRank.

Feasible connections
--------------------
A flight ``b`` connects after a flight ``a`` when ``a.ades == b.adep`` and the
layover at the connecting airport satisfies
``mct(airport) <= b.dep - a.arr <= max_wait``. MCT is 45 minutes by default and
can be overridden per airport via a dict or a CSV. ``max_wait`` is 6 hours.

Temporal PageRank
-----------------
Implemented with the streaming algorithm of Rozenshtein & Gionis, *Temporal
PageRank* (ECML PKDD 2016), Algorithm 1. Given the flight stream ordered by
departure and parameters ``alpha`` (jumping/damping probability) and ``beta``
(transition probability in ``(0, 1]``), it keeps a temporal PageRank estimate
``r`` and an active mass ``s`` per airport and, for every flight ``(u -> v)``::

    r[u] += (1 - alpha)
    s[u] += (1 - alpha)
    r[v] += s[u] * alpha
    if beta < 1:  s[v] += s[u] * (1 - beta) * alpha ; s[u] = s[u] * beta
    else:         s[v] += s[u] * alpha              ; s[u] = 0
    normalize(r)

We add the air-connectivity constraint: mass that arrives at an airport becomes
available for onward flights only after that airport's MCT and expires after
``max_wait`` (the paper's model has no wait limit). Each flight's fresh mass is
scaled by its #3 edge weight.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from scipy import stats

from .weights import add_edge_weights

#: Default minimum connecting time, in minutes.
DEFAULT_MCT_MINUTES = 45

#: Default maximum connection wait, in minutes (6 hours).
DEFAULT_MAX_WAIT_MINUTES = 360

_NS_PER_MINUTE = 60_000_000_000


def load_mct_table(path: str | Path) -> dict[str, int]:
    """Load a per-airport MCT override from a CSV with ``airport,mct_minutes`` columns."""
    overrides: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            airport = (row.get("airport") or "").strip().upper()
            if airport:
                overrides[airport] = int(float(row["mct_minutes"]))
    return overrides


def _mct_ns(airport: str, default_ns: int, overrides: dict[str, int]) -> int:
    minutes = overrides.get(airport)
    return default_ns if minutes is None else int(minutes) * _NS_PER_MINUTE


def _time_ns(flights: pd.DataFrame, column: str) -> Any:
    """Column as numpy int64 nanoseconds since the epoch (UTC).

    Converts explicitly to ``datetime64[ns]`` so the result does not depend on
    pandas' default datetime resolution (microseconds in pandas 3).
    """
    values = flights[column]
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        values = values.dt.tz_convert("UTC").dt.tz_localize(None)
    return values.to_numpy(dtype="datetime64[ns]").astype("int64")


def connections(
    flights: pd.DataFrame,
    mct: int = DEFAULT_MCT_MINUTES,
    max_wait: int = DEFAULT_MAX_WAIT_MINUTES,
    mct_overrides: dict[str, int] | None = None,
    off_block_column: str = "off_block_time",
    arrival_column: str = "arrival_time",
) -> pd.DataFrame:
    """Return the feasible connections between flights.

    Columns: ``a_idx`` (incoming flight), ``b_idx`` (onward flight) and
    ``wait`` (layover in minutes). Indices are positional into ``flights``.
    """
    df = flights.reset_index(drop=True)
    adep = df["adep"].to_numpy()
    ades = df["ades"].to_numpy()
    dep = _time_ns(df, off_block_column)
    arr = _time_ns(df, arrival_column)

    overrides = {a.upper(): m for a, m in (mct_overrides or {}).items()}
    default_ns = mct * _NS_PER_MINUTE
    max_wait_ns = max_wait * _NS_PER_MINUTE

    arrivals_at: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, airport in enumerate(ades):
        arrivals_at[airport].append((int(arr[index]), index))
    for entries in arrivals_at.values():
        entries.sort()

    rows: list[tuple[int, int, float]] = []
    for b_idx, airport in enumerate(adep):
        arrivals = arrivals_at.get(airport)
        if not arrivals:
            continue
        mct_ns = _mct_ns(airport, default_ns, overrides)
        low = int(dep[b_idx]) - max_wait_ns
        high = int(dep[b_idx]) - mct_ns
        for arr_ns, a_idx in arrivals:
            if arr_ns > high:
                break
            if arr_ns >= low:
                rows.append((a_idx, b_idx, (int(dep[b_idx]) - arr_ns) / _NS_PER_MINUTE))

    return pd.DataFrame(rows, columns=["a_idx", "b_idx", "wait"])


def temporal_pagerank(
    flights: pd.DataFrame,
    alpha: float = 0.85,
    beta: float = 1.0,
    weight: str = "frequency",
    mct: int = DEFAULT_MCT_MINUTES,
    max_wait: int = DEFAULT_MAX_WAIT_MINUTES,
    mct_overrides: dict[str, int] | None = None,
    off_block_column: str = "off_block_time",
    arrival_column: str = "arrival_time",
) -> dict[str, float]:
    """Temporal PageRank over the flight stream (Rozenshtein & Gionis 2016).

    See the module docstring for the exact update rule and how MCT/``max_wait``
    constrain the active mass. ``weight`` is a #3 mode used to scale each
    flight's fresh mass. Returns normalized scores keyed by airport.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if not 0.0 < beta <= 1.0:
        raise ValueError(f"beta must be in (0, 1], got {beta!r}")

    df = flights.reset_index(drop=True)
    if df.empty:
        return {}

    edge_weights = add_edge_weights(df, weight=weight)["Weight"].to_numpy(dtype=float)
    adep = df["adep"].to_numpy()
    ades = df["ades"].to_numpy()
    dep = _time_ns(df, off_block_column)
    arr = _time_ns(df, arrival_column)

    overrides = {a.upper(): int(m) for a, m in (mct_overrides or {}).items()}
    default_mct_ns = mct * _NS_PER_MINUTE
    max_wait_ns = max_wait * _NS_PER_MINUTE

    order = df[off_block_column].argsort(kind="stable").to_numpy()

    rank: dict[str, float] = defaultdict(float)
    # Active mass waiting at an airport: [available_ns, expiry_ns, mass].
    waiting: dict[str, list[list[float]]] = defaultdict(list)

    for i in order:
        u, v = adep[i], ades[i]
        fresh = (1.0 - alpha) * edge_weights[i]
        rank[u] += fresh

        buckets = waiting.get(u)
        available = 0.0
        if buckets:
            now = int(dep[i])
            kept: list[list[float]] = []
            for available_at, expiry, mass in buckets:
                if now < available_at:
                    kept.append([available_at, expiry, mass])
                elif now <= expiry:
                    available += mass
            waiting[u] = kept

        carry = fresh + available
        rank[v] += alpha * carry

        cont = alpha * carry if beta >= 1.0 else alpha * (1.0 - beta) * carry
        if cont > 0.0:
            mct_v = _mct_ns(v, default_mct_ns, overrides)
            waiting[v].append([int(arr[i]) + mct_v, int(arr[i]) + max_wait_ns, cont])
        if beta < 1.0:
            retain = beta * carry
            if retain > 0.0:
                waiting[u].append([int(dep[i]), int(dep[i]) + max_wait_ns, retain])

    total = sum(rank.values())
    if total <= 0.0:
        return dict.fromkeys(rank, 0.0)
    return {airport: value / total for airport, value in rank.items()}


@dataclass
class RankComparison:
    """Agreement between a temporal and a static PageRank ordering."""

    spearman: float
    kendall: float
    top_k_overlap: float
    k: int
    nodes: int


def compare_pagerank(
    temporal: dict[str, float],
    static: dict[str, float],
    k: int = 10,
) -> RankComparison:
    """Compare temporal and static PageRank: Spearman, Kendall and top-k overlap."""
    nodes = sorted(set(temporal) | set(static))
    if not nodes:
        return RankComparison(spearman=float("nan"), kendall=float("nan"), top_k_overlap=0.0, k=k, nodes=0)

    t = [temporal.get(node, 0.0) for node in nodes]
    s = [static.get(node, 0.0) for node in nodes]

    spearman = float(stats.spearmanr(t, s).statistic) if len(nodes) > 1 else float("nan")
    kendall = float(stats.kendalltau(t, s).statistic) if len(nodes) > 1 else float("nan")

    top_temporal = {node for node, _ in sorted(temporal.items(), key=lambda kv: kv[1], reverse=True)[:k]}
    top_static = {node for node, _ in sorted(static.items(), key=lambda kv: kv[1], reverse=True)[:k]}
    overlap = len(top_temporal & top_static) / k if k else 0.0

    return RankComparison(
        spearman=spearman, kendall=kendall, top_k_overlap=overlap, k=k, nodes=len(nodes)
    )
