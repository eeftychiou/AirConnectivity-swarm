"""Edge weighting schemes.

Ported from ``airctools.add_weights`` (2021). Only the ``onwards`` scheme is
implemented here; ``simple`` and ``seats`` are handled by later issues.
"""

from __future__ import annotations

import pandas as pd


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
