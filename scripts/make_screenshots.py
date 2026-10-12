"""Regenerate the documentation screenshots from a real two-period report run.

Usage (from the repo root, after building a report and CLI captures)::

    python scripts/make_screenshots.py \
        --report /tmp/shots/report.html --out docs/img \
        --load-202403 /tmp/shots/load_202403.txt \
        --load-202404 /tmp/shots/load_202404.txt \
        --markdown /tmp/shots/report.md

Requires the optional extras plus Playwright's Chromium::

    pip install -e ".[viz]" bokeh playwright
    playwright install chromium

The report is expected to be a self-contained (``--inline``) page so it renders
offline. Only aggregated charts and rankings are captured; no flight rows.
Images are optimised to stay under ~500 KB.

The default ``docs/img`` filenames are also asserted by ``tests/test_docs.py``.
"""

from __future__ import annotations

import argparse
import html
import tempfile
from pathlib import Path

from PIL import Image

#: Output file names, in the order they are written.
CHART_FILES = (
    "02_static_vs_temporal.png",
    "03_rank_change.png",
    "04_time_series.png",
    "05_airport_map.png",
)
FULL_PAGE_FILE = "01_report_full.png"
CLI_FILE = "06_cli_and_report.png"

_SIZE_LIMIT = 500 * 1024
#: Tall enough that the whole report fits without scrolling, so the mouse can
#: reach the map chart and screenshot clip coordinates match the page.
_VIEWPORT = {"width": 760, "height": 2800}


def _shrink(path: Path, limit: int = _SIZE_LIMIT) -> None:
    """Re-save a PNG under ``limit`` bytes, downscaling if needed."""
    if path.stat().st_size <= limit:
        return
    image = Image.open(path).convert("RGB")
    image.save(path, optimize=True)
    scale = 0.85
    while path.stat().st_size > limit and scale > 0.3:
        width, height = image.size
        image.resize((max(1, int(width * scale)), max(1, int(height * scale)))).save(path, optimize=True)
        scale -= 0.1


def _hover_a_point(page, figure) -> bool:
    """Try to hover a plotted glyph until a non-empty bokeh tooltip shows.

    Returns whether a tooltip appeared. Headless browsers do not always dispatch
    the pointer events bokeh's hover needs, so this is best-effort: the map
    chart also annotates its top airport, and the caller falls back to a plain
    figure screenshot when no tooltip is available.
    """
    box = figure.bounding_box()
    tooltip = page.locator("div.bk-Tooltip")
    step = 18
    y = box["y"] + 6
    while y < box["y"] + box["height"]:
        x = box["x"] + 6
        while x < box["x"] + box["width"]:
            page.mouse.move(x, y)
            page.wait_for_timeout(15)
            if tooltip.count() and tooltip.first.is_visible() and tooltip.first.inner_text().strip():
                return True
            x += step
        y += step
    return False


def _cli_html(load_files: list[Path], markdown: Path) -> str:
    """A dark "terminal" page holding the CLI captures and the report excerpt."""
    blocks = []
    for path in load_files:
        blocks.append(f"<h3>{html.escape(path.name)}</h3><pre>{html.escape(path.read_text(encoding='utf-8'))}</pre>")
    excerpt = "\n".join(markdown.read_text(encoding="utf-8").splitlines()[:28])
    blocks.append(f"<h3>report.md (excerpt)</h3><pre>{html.escape(excerpt)}</pre>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;padding:24px;}"
        "h3{color:#4ec9b0;margin:16px 0 6px;font-size:15px;}"
        "pre{background:#252526;padding:12px;border-radius:6px;font-size:13px;line-height:1.4;}"
        "</style></head><body>" + "".join(blocks) + "</body></html>"
    )


def make_screenshots(report: Path, out_dir: Path, load_files: list[Path], markdown: Path) -> list[Path]:
    """Write the six screenshots and return their paths."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=_VIEWPORT, device_scale_factor=1)
        page.goto(report.resolve().as_uri())
        page.wait_for_timeout(3000)

        full_page = out_dir / FULL_PAGE_FILE
        page.screenshot(path=str(full_page), full_page=True)
        written.append(full_page)

        figures = page.locator(".bk-Figure")
        for index, name in enumerate(CHART_FILES):
            figure = figures.nth(index)
            figure.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            target = out_dir / name
            if name == "05_airport_map.png":  # try to show a hover tooltip
                if _hover_a_point(page, figure):
                    box = figure.bounding_box()
                    tip = page.locator("div.bk-Tooltip").first.bounding_box()
                    left = min(box["x"], tip["x"]) - 10
                    top = min(box["y"], tip["y"]) - 10
                    right = max(box["x"] + box["width"], tip["x"] + tip["width"]) + 10
                    bottom = max(box["y"] + box["height"], tip["y"] + tip["height"]) + 10
                    clip = {"x": max(0, left), "y": max(0, top), "width": right - left, "height": bottom - top}
                    page.screenshot(path=str(target), clip=clip)
                else:  # no hover in this browser: the top airport is annotated anyway
                    figure.screenshot(path=str(target))
            else:
                figure.screenshot(path=str(target))
            written.append(target)

        cli_page = browser.new_page(viewport=_VIEWPORT, device_scale_factor=1)
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as handle:
            handle.write(_cli_html(load_files, markdown))
            cli_path = Path(handle.name)
        cli_page.goto(cli_path.as_uri())
        cli_page.wait_for_timeout(300)
        cli_target = out_dir / CLI_FILE
        cli_page.screenshot(path=str(cli_target), full_page=True)
        written.append(cli_target)

        browser.close()
        cli_path.unlink(missing_ok=True)

    for path in written:
        _shrink(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="the --inline report.html")
    parser.add_argument("--out", required=True, type=Path, help="output directory, e.g. docs/img")
    parser.add_argument("--load-202403", required=True, type=Path, dest="load_202403")
    parser.add_argument("--load-202404", required=True, type=Path, dest="load_202404")
    parser.add_argument("--markdown", required=True, type=Path, help="the report.md")
    args = parser.parse_args()

    written = make_screenshots(
        args.report, args.out, [args.load_202403, args.load_202404], args.markdown
    )
    for path in written:
        print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
