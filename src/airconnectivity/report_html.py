"""Interactive bokeh HTML report (issue #12).

Builds one self-contained HTML page from the #6 ranking CSVs with four charts:
top airports static vs temporal, rank change between months, one airport's
PageRank over time, and a map of airports sized by PageRank.

``bokeh`` is an optional dependency (``pip install .[viz]``); importing this
module does not import bokeh, and :func:`build_html_report` raises a clear error
if it is missing.
"""

from __future__ import annotations

import math
import types
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .report import load_rankings

#: Stable figure names and titles (also used by the tests).
FIGURE_IDS = {
    "top": "chart-top-airports",
    "movers": "chart-rank-change",
    "series": "chart-pagerank-over-time",
    "map": "chart-airport-map",
}
FIGURE_TITLES = {
    "top": "Top airports: static vs temporal PageRank",
    "movers": "Rank change between months",
    "series": "PageRank over time",
    "map": "Airport map (sized by PageRank)",
}


def _bokeh() -> types.SimpleNamespace:
    """Import bokeh lazily, with a clear error when the viz extra is missing."""
    try:
        from bokeh.embed import file_html
        from bokeh.layouts import column
        from bokeh.models import ColumnDataSource, CustomJS, Div, FixedTicker, HoverTool, Select
        from bokeh.plotting import figure
        from bokeh.resources import CDN, INLINE
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise ImportError("bokeh is required for the HTML report; install it with `pip install .[viz]`") from exc
    return types.SimpleNamespace(
        file_html=file_html,
        column=column,
        ColumnDataSource=ColumnDataSource,
        CustomJS=CustomJS,
        Div=Div,
        FixedTicker=FixedTicker,
        HoverTool=HoverTool,
        Select=Select,
        figure=figure,
        CDN=CDN,
        INLINE=INLINE,
    )


def _monthly(frame: pd.DataFrame) -> dict[str, float]:
    return frame.groupby("airport")["score"].mean().to_dict()


def _top_airports(
    monthly: dict[tuple[str, str], dict[str, float]], periods: list[str], method: str, top_n: int
) -> list[str]:
    totals: dict[str, float] = defaultdict(float)
    for period in periods:
        for airport, score in monthly.get((period, method), {}).items():
            totals[airport] += score
    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [airport for airport, _ in ordered[:top_n]]


def _airport_coords(flights: pd.DataFrame | None) -> dict[str, tuple[float, float]]:
    """Mean departure coordinates per airport, from the flights if available."""
    if flights is None or flights.empty:
        return {}
    required = {"adep", "adep_latitude", "adep_longitude"}
    if not required <= set(flights.columns):
        return {}
    grouped = flights.dropna(subset=["adep_latitude", "adep_longitude"]).groupby("adep")
    return {
        str(airport): (float(lat), float(lon))
        for airport, (lat, lon) in grouped[["adep_latitude", "adep_longitude"]].mean().iterrows()
    }


def _chart_top(bk, monthly, periods, method, top_n):
    airports = _top_airports(monthly, periods, method, top_n)
    if not airports:
        return None, None
    indices = list(range(len(airports)))
    fig = bk.figure(height=380, title=FIGURE_TITLES["top"], name=FIGURE_IDS["top"])
    fig.xaxis.ticker = bk.FixedTicker(ticks=indices)
    fig.xaxis.major_label_overrides = {index: airport for index, airport in enumerate(airports)}
    renderers: dict[str, list] = {}
    for period in periods:
        static = monthly.get((period, "static"), {})
        temporal = monthly.get((period, "temporal"), {})
        source = bk.ColumnDataSource(
            {
                "airport": airports,
                "x_static": [index - 0.2 for index in indices],
                "x_temporal": [index + 0.2 for index in indices],
                "static": [static.get(a, 0.0) for a in airports],
                "temporal": [temporal.get(a, 0.0) for a in airports],
            }
        )
        bars = [
            fig.vbar(
                x="x_static", top="static", width=0.4, color="#4c78a8", legend_label=f"{period} static", source=source
            ),
            fig.vbar(
                x="x_temporal",
                top="temporal",
                width=0.4,
                color="#f58518",
                legend_label=f"{period} temporal",
                source=source,
            ),
        ]
        renderers[period] = bars
    fig.add_tools(
        bk.HoverTool(
            renderers=[r for bars in renderers.values() for r in bars],
            tooltips=[("airport", "@airport"), ("static", "@static{0.0000}"), ("temporal", "@temporal{0.0000}")],
        )
    )
    selector = bk.Select(title="Period", value=periods[0], options=list(periods))
    selector.js_on_change(
        "value",
        bk.CustomJS(
            args={"renderers": renderers, "selector": selector},
            code="for (const p in renderers) { for (const r of renderers[p]) { r.visible = (p == selector.value); } }",
        ),
    )
    return fig, selector


def _chart_movers(bk, monthly, periods, method, top_n):
    if len(periods) < 2:
        return None, None
    airport_ranks: dict[tuple[str, str], dict[str, int]] = {}
    for period in periods:
        scores = monthly.get((period, method), {})
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        airport_ranks[period] = {airport: rank for rank, (airport, _) in enumerate(ordered, start=1)}

    previous, current = periods[0], periods[-1]
    common = sorted(set(airport_ranks[previous]) & set(airport_ranks[current]))[:top_n]
    if not common:
        return None, None
    fig = bk.figure(
        x_range=common,
        height=380,
        title=f"{FIGURE_TITLES['movers']}: {previous} vs {current}",
        name=FIGURE_IDS["movers"],
    )
    fig.xaxis.major_label_orientation = 1.0
    fig.yaxis.axis_label = "rank (1 = best)"
    source = bk.ColumnDataSource(
        {
            "airport": common,
            "previous": [airport_ranks[previous][a] for a in common],
            "current": [airport_ranks[current][a] for a in common],
        }
    )
    fig.segment(x0="airport", y0="previous", x1="airport", y1="current", source=source, line_color="#888")
    prev_r = fig.scatter(x="airport", y="previous", source=source, size=8, color="#4c78a8", legend_label=previous)
    curr_r = fig.scatter(x="airport", y="current", source=source, size=8, color="#f58518", legend_label=current)
    fig.add_tools(
        bk.HoverTool(
            renderers=[prev_r, curr_r],
            tooltips=[("airport", "@airport"), (previous, "@previous"), (current, "@current")],
        )
    )
    return fig, None


def _chart_series(bk, loaded, top_n):
    # Prefer daily, then weekly, ranking files for the time series.
    for freq in ("D", "W"):
        series_by_airport: dict[str, list[tuple[pd.Timestamp, float]]] = defaultdict(list)
        for _period, file_freq, method, frame in loaded:
            if file_freq != freq or method not in ("temporal", "static"):
                continue
            for _, row in frame.iterrows():
                series_by_airport[row["airport"]].append((pd.Timestamp(row["window"]), float(row["score"])))
        airports = sorted(series_by_airport, key=lambda a: -max(score for _, score in series_by_airport[a]))[:top_n]
        if not airports:
            continue
        fig = bk.figure(height=380, title=f"{FIGURE_TITLES['series']} (per {freq} window)", name=FIGURE_IDS["series"])
        fig.xaxis.axis_label = "window"
        fig.yaxis.axis_label = "PageRank"
        renderers: dict[str, object] = {}
        for airport in airports:
            points = sorted(series_by_airport[airport])
            source = bk.ColumnDataSource(
                {"window": [w for w, _ in points], "score": [s for _, s in points], "airport": [airport] * len(points)}
            )
            renderers[airport] = fig.line(x="window", y="score", source=source, legend_label=airport)
        fig.add_tools(bk.HoverTool(tooltips=[("airport", "@airport"), ("score", "@score{0.0000}")]))
        selector = bk.Select(title="Airport", value=airports[0], options=list(airports))
        selector.js_on_change(
            "value",
            bk.CustomJS(
                args={"renderers": renderers, "selector": selector},
                code="for (const a in renderers) { renderers[a].visible = (a == selector.value); }",
            ),
        )
        return fig, selector
    return None, None


def _chart_map(bk, monthly, periods, method, top_n, coords):
    if not coords:
        return None, None
    totals: dict[str, float] = defaultdict(float)
    for period in periods:
        for airport, score in monthly.get((period, method), {}).items():
            totals[airport] += score
    airports = [a for a in _top_airports(monthly, periods, method, top_n) if a in coords]
    if not airports:
        return None, None
    lats = [coords[a][0] for a in airports]
    lons = [coords[a][1] for a in airports]
    scores = [totals[a] for a in airports]
    ordered = sorted(airports, key=lambda a: -totals[a])
    ranks = {a: i + 1 for i, a in enumerate(ordered)}
    source = bk.ColumnDataSource(
        {
            "airport": airports,
            "name": airports,
            "lat": lats,
            "lon": lons,
            "score": scores,
            "rank": [ranks[a] for a in airports],
            "size": [8 + 60 * math.sqrt(s / max(scores)) for s in scores],
        }
    )
    fig = bk.figure(height=420, title=FIGURE_TITLES["map"], name=FIGURE_IDS["map"], match_aspect=True)
    fig.xaxis.axis_label = "longitude"
    fig.yaxis.axis_label = "latitude"
    circles = fig.scatter(x="lon", y="lat", size="size", source=source, fill_alpha=0.6, line_color="#333")
    fig.add_tools(
        bk.HoverTool(
            renderers=[circles],
            tooltips=[("ICAO", "@airport"), ("name", "@name"), ("score", "@score{0.0000}"), ("rank", "@rank")],
        )
    )
    return fig, None


def build_html_report(
    rankings_dir: str | Path,
    out_path: str | Path,
    *,
    top_n: int = 25,
    inline: bool = False,
    flights: pd.DataFrame | None = None,
    weight: str | None = None,
) -> Path:
    """Write a self-contained bokeh HTML report built from the ranking CSVs."""
    bk = _bokeh()
    loaded = load_rankings(rankings_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not loaded:
        out_path.write_text(
            "<html><body><h1>AirConnectivity report</h1><p>No rankings found.</p></body></html>", encoding="utf-8"
        )
        return out_path

    periods = sorted({period for period, _, _, _ in loaded})
    monthly = {(period, method): _monthly(frame) for period, _, method, frame in loaded}
    methods = {method for _, _, method, _ in loaded}
    method = "temporal" if "temporal" in methods else sorted(methods)[0]

    top_fig, top_sel = _chart_top(bk, monthly, periods, method, top_n)
    movers_fig, movers_sel = _chart_movers(bk, monthly, periods, method, top_n)
    series_fig, series_sel = _chart_series(bk, loaded, top_n)
    map_fig, map_sel = _chart_map(bk, monthly, periods, method, top_n, _airport_coords(flights))

    header = bk.Div(
        text=(
            "<h1>AirConnectivity report</h1>"
            f"<p>Periods: {', '.join(periods)} &middot; top-N: {top_n} &middot; "
            f"weight: {weight or 'n/a'} &middot; method: {method}</p>"
        )
    )
    blocks = [header]
    for fig, sel in ((top_fig, top_sel), (movers_fig, movers_sel), (series_fig, series_sel), (map_fig, map_sel)):
        if fig is not None:
            blocks.append(sel if sel is not None else bk.Div(text=""))
            blocks.append(fig)

    resources = bk.INLINE if inline else bk.CDN
    html = bk.file_html(bk.column(*blocks), resources, "AirConnectivity report")
    out_path.write_text(html, encoding="utf-8")
    return out_path
