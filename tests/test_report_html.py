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


def test_cli_report_html_from_rankings(rankings_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "cli.html"
    assert (
        cli.main(["report", "--rankings", str(rankings_dir), "--html", str(out), "--top-n", "4"]) == 0
    )
    text = out.read_text(encoding="utf-8")
    assert FIGURE_TITLES["top"] in text
    assert FIGURE_IDS["top"] in text
