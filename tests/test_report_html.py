"""Tests for the interactive bokeh HTML report (issue #12)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from airconnectivity import cli
from airconnectivity.report_html import FIGURE_IDS, FIGURE_TITLES, build_html_report

_RANKING_COLUMNS = ["airport", "rank", "score", "window", "weight"]
_AIRPORTS = ["EGLL", "LFPG", "EHAM", "EDDF"]


def _write_rankings(directory: Path, period: str, freq: str, method: str, windows: list[str]) -> None:
    rows = []
    for window in windows:
        for rank, airport in enumerate(_AIRPORTS, start=1):
            score = (len(_AIRPORTS) - rank + 1) / 10.0
            if method == "temporal":
                score *= 0.9
            rows.append({"airport": airport, "rank": rank, "score": score, "window": window, "weight": "seats"})
    pd.DataFrame(rows, columns=_RANKING_COLUMNS).to_csv(
        directory / f"rankings_{period}_{freq}_{method}.csv", index=False
    )


@pytest.fixture
def rankings_dir(tmp_path: Path) -> Path:
    for period, days in (("202403", ["2024-03-01", "2024-03-02"]), ("202404", ["2024-04-01"])):
        for method in ("static", "temporal"):
            _write_rankings(tmp_path, period, "M", method, [days[0][:7] + "-01"])
            _write_rankings(tmp_path, period, "D", method, days)
    return tmp_path


def _coords() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "adep": ["EGLL", "LFPG", "EHAM", "EDDF"],
            "adep_latitude": [51.47, 49.0, 52.3, 50.03],
            "adep_longitude": [-0.46, 2.55, 4.76, 8.57],
        }
    )


def test_build_html_report_contains_charts(rankings_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    path = build_html_report(rankings_dir, out, top_n=4, flights=_coords(), weight="seats")

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "bokeh" in text.lower()
    for title in FIGURE_TITLES.values():
        assert title in text
    for figure_id in FIGURE_IDS.values():
        assert figure_id in text


def test_inline_report_embeds_resources(rankings_dir: Path, tmp_path: Path) -> None:
    cdn = build_html_report(rankings_dir, tmp_path / "cdn.html", top_n=4)
    inline = build_html_report(rankings_dir, tmp_path / "inline.html", top_n=4, inline=True)
    assert len(inline.read_text(encoding="utf-8")) > len(cdn.read_text(encoding="utf-8"))


def test_build_html_report_without_rankings(tmp_path: Path) -> None:
    path = build_html_report(tmp_path / "empty", tmp_path / "report.html")
    assert "No rankings found" in path.read_text(encoding="utf-8")


def test_missing_bokeh_raises(monkeypatch: pytest.MonkeyPatch, rankings_dir: Path, tmp_path: Path) -> None:
    for name in list(sys.modules):
        if name == "bokeh" or name.startswith("bokeh."):
            monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(ImportError, match="bokeh is required"):
        build_html_report(rankings_dir, tmp_path / "report.html")


def test_build_html_report_restricts_to_requested_periods(tmp_path: Path) -> None:
    for period in ("202403", "202404", "202405"):
        window = f"{period[:4]}-{period[4:]}-01"
        for method in ("static", "temporal"):
            _write_rankings(tmp_path, period, "M", method, [window])
    out = tmp_path / "report.html"
    build_html_report(tmp_path, out, top_n=4, periods=["202403", "202404"])

    text = out.read_text(encoding="utf-8")
    assert "Periods: 202403, 202404" in text
    assert "202405" not in text


def test_chart_map_uses_airport_name_lookup() -> None:
    from airconnectivity.report_html import _bokeh, _chart_map

    fig, _ = _chart_map(
        _bokeh(), {("202403", "temporal"): {"EGLL": 0.9}}, ["202403"], "temporal", 25, {"EGLL": (51.47, -0.46)}
    )
    data = [r for r in fig.renderers if hasattr(r, "data_source") and "name" in r.data_source.data][0].data_source.data
    assert data["airport"] == ["EGLL"]
    assert "Heathrow" in data["name"][0]


def test_chart_map_annotates_the_top_airport() -> None:
    from airconnectivity.report_html import _bokeh, _chart_map

    fig, _ = _chart_map(
        _bokeh(),
        {("202403", "temporal"): {"EGLL": 0.9, "LFPG": 0.5}},
        ["202403"],
        "temporal",
        25,
        {"EGLL": (51.47, -0.46), "LFPG": (49.0, 2.55)},
    )
    texts: list[str] = []
    for collection in (fig.renderers, fig.center, fig.left, fig.right, fig.above, fig.below):
        for item in collection:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                texts.append(text)
    joined = " ".join(texts)
    assert "EGLL" in joined and "Heathrow" in joined and "score" in joined and "rank" in joined


def test_chart_map_unknown_name_shows_icao_with_note() -> None:
    from airconnectivity.report_html import _bokeh, _chart_map

    fig, _ = _chart_map(
        _bokeh(), {("202403", "temporal"): {"ZZZZ": 0.9}}, ["202403"], "temporal", 25, {"ZZZZ": (0.0, 0.0)}
    )
    data = [r for r in fig.renderers if hasattr(r, "data_source") and "name" in r.data_source.data][0].data_source.data
    assert data["name"] == ["ZZZZ (name unknown)"]


def test_airport_names_data_notes_its_source() -> None:
    from importlib import resources

    path = resources.files("airconnectivity").joinpath("data/airport_names.csv")
    with resources.as_file(path) as file_path:
        text = file_path.read_text(encoding="utf-8")
    assert "OurAirports" in text
    assert "public domain" in text


def test_airport_names_cover_common_airports_beyond_top_25() -> None:
    from airconnectivity.report_html import load_airport_names

    names = load_airport_names()
    for code in ("EGLL", "EDDH", "EDDS", "LEBL", "LTFM", "OMDB", "KJFK", "LSZH"):
        assert names.get(code), f"{code} should have a name"
    assert len(names) > 300


def test_cli_report_html_from_rankings(rankings_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "cli.html"
    assert (
        cli.main(["report", "--rankings", str(rankings_dir), "--html", str(out), "--top-n", "4"]) == 0
    )
    text = out.read_text(encoding="utf-8")
    assert FIGURE_TITLES["top"] in text
    assert FIGURE_IDS["top"] in text


def test_cli_report_accepts_space_and_comma_separated_periods() -> None:
    parser = cli.build_parser().parse_args(["report", "--periods", "202403", "202404", "--html", "out.html"])
    assert parser.periods == ["202403", "202404"]
    assert cli._parse_periods(parser.periods) == ["202403", "202404"]
    assert cli._parse_periods(["202403,202404"]) == ["202403", "202404"]


def _bar_renderers(fig) -> list:
    return [
        r
        for r in fig.renderers
        if hasattr(r, "data_source") and "x_static" in getattr(r.data_source, "data", {})
    ]


def test_chart_top_shows_only_the_selected_period() -> None:
    from airconnectivity.report_html import _bokeh, _chart_top

    monthly = {
        ("202403", "temporal"): {"A": 0.9, "B": 0.1},
        ("202403", "static"): {"A": 0.8, "B": 0.2},
        ("202404", "temporal"): {"A": 0.7, "B": 0.3},
        ("202404", "static"): {"A": 0.6, "B": 0.4},
    }
    fig, _ = _chart_top(_bokeh(), monthly, ["202403", "202404"], "temporal", 2)

    bars = _bar_renderers(fig)
    assert len(bars) == 4
    assert sum(renderer.visible for renderer in bars) == 2  # only 202403's two bars


def test_chart_movers_picks_top_airports_by_rank() -> None:
    from airconnectivity.report_html import _bokeh, _chart_movers

    monthly = {
        ("202403", "temporal"): {"TOP": 0.9, "A": 0.1, "B": 0.05},
        ("202404", "temporal"): {"TOP": 0.9, "A": 0.1, "B": 0.05},
    }
    fig, _ = _chart_movers(_bokeh(), monthly, ["202403", "202404"], "temporal", 1)
    assert list(fig.x_range.factors) == ["TOP"]


def test_chart_series_single_method_and_selected_airport(rankings_dir: Path) -> None:
    from airconnectivity.report import load_rankings
    from airconnectivity.report_html import _bokeh, _chart_series

    loaded = load_rankings(rankings_dir)
    fig, _ = _chart_series(_bokeh(), loaded, 4, "temporal")

    lines = [r for r in fig.renderers if hasattr(r, "data_source") and "window" in r.data_source.data]
    assert len(lines) == 4
    assert sum(line.visible for line in lines) == 1  # only the selected airport
    assert type(fig.xaxis[0].formatter).__name__ == "DatetimeTickFormatter"  # dates, not epoch numbers
