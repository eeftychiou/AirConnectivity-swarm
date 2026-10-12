# Pagerank Air Connectivity Indicator and optimizer

Air Connectivity Indicator using PageRank. Loads EUROCONTROL R&D Data to
calculate a connectivity indicator using weighted PageRank and other network
metrics.

The weight of an edge can be a simple connection, proportional to the onwards
connectivity at the destination airport, or (TODO) proportional to the passenger
capacity of the flight.

Data can be downloaded from the
[EUROCONTROL R&D Data Archive](https://www.eurocontrol.int/dashboard/rnd-data-archive).

## Install

Python >= 3.10 is required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate ; POSIX: source .venv/bin/activate
pip install -e .
```

Optional visualisation extras (bokeh, matplotlib, igraph) and developer tools:

```bash
pip install -e ".[viz,dev]"
```

## Usage

The data root is passed in — either with `--data-root` or the
`AIRCONN_DATA_ROOT` environment variable. No path is ever hard-coded, and no
data or row-level extracts are committed to git.

```bash
airconn --help
airconn --data-root /path/to/data load --period 202403 --summary
airconn --data-root /path/to/data rank --period 202403
airconn --data-root /path/to/data report --period 202403 --period 202406
```

Data is expected as `<data-root>/<YYYYMM>/Flights_*.csv.gz` (EUROCONTROL
export). Folders are not contiguous months: 2020–2023 are quarterly, 2024–2025
are mostly monthly.

`airconn load --period 202403 --summary` reads the gz files in place and prints
aggregate counts per market segment and flight type only — no row-level data is
written. In Python:

```python
from airconnectivity.io import discover_periods, load_flights

periods = discover_periods("path/to/data")          # e.g. ["202403", "202406"]
df = load_flights("path/to/data", periods=["202403"])
```

`load_flights` returns a typed DataFrame with snake_case columns and UTC
datetimes. By default it keeps ICAO flight type `S` and the passenger market
segments `Mainline`, `Regional`, `Low-Cost` and `Charter`; both filters are
configurable, and `time_basis="actual"` (default) or `"filed"` picks the
timestamp pair. Rows missing ADEP, ADES or the selected times, and rows with
`ADEP == ADES`, are dropped.

Edge weights are chosen with `weight="frequency"|"unweighted"|"distance"|"seats"`
(`airconnectivity.weights`):

```python
from airconnectivity.weights import aggregate_edges

edges = aggregate_edges(df, weight="seats")   # adep, ades, Weight
```

`distance` uses great-circle km from the coordinates (or `distance_source="actual"`
for the flown distance); `seats` uses the committed
`src/airconnectivity/data/ac_type_seats.csv` lookup (ICAO type -> typical seats),
falling back to 150 seats for unknown types, which are counted and logged.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

CI runs ruff and pytest on Python 3.10 and 3.12.

## Package layout

```
src/airconnectivity/
  config.py    explicit Config dataclass (replaces the old global settings module)
  geo.py       great-circle distance and flight-time estimates
  io.py        period discovery + EUROCONTROL flight-file loaders
  weights.py   edge weighting schemes
  cli.py       the `airconn` command-line entry point
tests/         pytest suite (small synthetic fixtures only)
```
