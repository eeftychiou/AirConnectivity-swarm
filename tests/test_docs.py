"""Tests for the documentation screenshots and guides (issue #16)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"

#: Screenshots committed under docs/img (see scripts/make_screenshots.py).
SCREENSHOTS = (
    "01_report_full.png",
    "02_static_vs_temporal.png",
    "03_rank_change.png",
    "04_time_series.png",
    "05_airport_map.png",
    "06_cli_and_report.png",
)
_SIZE_LIMIT = 500 * 1024


@pytest.mark.parametrize("name", SCREENSHOTS)
def test_screenshot_exists_and_is_small(name: str) -> None:
    path = IMG / name
    assert path.exists(), f"{name} is missing"
    assert path.stat().st_size <= _SIZE_LIMIT, f"{name} is larger than 500 KB"


def test_readme_embeds_the_screenshots_and_quickstart() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in SCREENSHOTS:
        assert f"docs/img/{name}" in text
    for command in ("airconn load", "airconn rank", "airconn report", "--html"):
        assert command in text
    assert "pip install -e" in text


def test_usage_doc_covers_the_key_topics() -> None:
    text = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
    for token in (
        "airconn load",
        "airconn rank",
        "airconn report",
        "--top-n",
        "--weight",
        "MCT",
        "Rozenshtein",
        "Not Classified",
        "airport_names.csv",
        "ac_type_seats.csv",
    ):
        assert token in text, f"docs/usage.md should mention {token!r}"
