# AirConnectivity usage

`airconn` has three subcommands — `load`, `rank`, `report` — plus `--help` and
`--version`. The data root is always passed in with `--data-root` (or the
`AIRCONN_DATA_ROOT` environment variable); no path is hard-coded.

```
airconn [--data-root PATH] COMMAND ...
```

`--data-root` may be given before or after the subcommand.

## `airconn load`

Load one or more periods and print aggregate counts (never row-level data).

```bash
airconn load --data-root "$DATA" --period 202403 --summary
```

| Option | Meaning |
| --- | --- |
| `--period PERIOD` | period folder, e.g. `202403`; repeatable (default: every folder found) |
| `--segments SEGMENT` | keep only these STATFOR market segments; repeatable; overrides the default set |
| `--summary` | also print the counts per market segment and flight type |

For every period the loader logs the number of retained flights and the number
of `Not Classified` flights, e.g.
`period 202403: 667465 flights retained, 667465 Not Classified (ICAO type S)`.

### Default passenger filter

A flight is kept when its **ICAO flight type is `S`** (scheduled) **and** its
STATFOR market segment is one of

```
Mainline, Regional, Regional Aircraft, Low-Cost, Lowcost, Charter,
Traditional Scheduled, Not Classified
```

The set spans both EUROCONTROL labelling eras (2020–2021 used
`Traditional Scheduled`/`Lowcost`; later exports use `Mainline`/`Regional
Aircraft`). `Not Classified` is included so periods whose exports carry no
STATFOR classification (e.g. `202403`) are not empty; use `--segments` to
exclude it. `All-Cargo`, `Business Aviation`, `Military` and `Other Types` are
excluded by default. Rows missing ADEP, ADES or the selected times, and rows
where `ADEP == ADES`, are dropped.

Times are parsed as UTC. The output DataFrame has snake_case columns and both
`off_block_time`/`arrival_time` (the basis selected by `time_basis="actual"`
(default) or `"filed"`).

## `airconn rank`

Write per-period airport rankings as CSV.

```bash
airconn rank --data-root "$DATA" --periods 202403,202404 \
    --window M --weight seats --method both --out outputs
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--periods` | all discovered | comma-separated periods, e.g. `202403,202404` |
| `--window` | `M` | window frequency: `D` (day), `W` (ISO week), `M` (month), UTC |
| `--weight` | `seats` | edge weight scheme (see below) |
| `--method` | `both` | `static`, `temporal` or `both` |
| `--out` | `outputs` | output directory |

Each period produces `rankings_<period>_<window>_<method>.csv` containing only
the requested period's windows (flights whose UTC departure falls in an
adjacent month are not included). Columns:

| Column | Meaning |
| --- | --- |
| `airport` | ICAO code |
| `rank` | 1-based rank within the window (1 = best) |
| `score` | PageRank score |
| `window` | window start, UTC |
| `weight` | the weight scheme used |

### Weight modes

| Mode | Edge weight |
| --- | --- |
| `frequency`, `unweighted` | 1 per flight (after aggregation: the flight count) |
| `distance` | great-circle km from the airport coordinates (`distance_source="gcd"`, default) or the filed/actual distance in km (`distance_source="actual"`) |
| `seats` | estimated seats per flight from the ICAO aircraft type |

### Seat lookup

`src/airconnectivity/data/ac_type_seats.csv` maps ICAO type designators to
typical two-class seat counts (representative manufacturer figures). A type not
in the table falls back **per row** to a category default (widebody 300,
narrowbody 180, regional_jet 100, turboprop 70, business_jet 10, unknown 150):
first from the designator's manufacturer/model family, then from the flight's
STATFOR segment (e.g. `Regional` → regional_jet), then `unknown`. Fallbacks are
counted and logged with the affected flights per category.

## `airconn report`

### Markdown report

```bash
airconn report --rankings outputs --out outputs/report.md
```

Writes the top 20 airports per month, the biggest movers between consecutive
months, and the static-vs-temporal Spearman/Kendall/top-k correlation per month.

### Interactive HTML report

```bash
airconn report --data-root "$DATA" --rankings outputs --periods 202403 202404 \
    --html outputs/report.html --inline --top-n 25
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--rankings` | `outputs` | directory of `rankings_*.csv` |
| `--html` | – | write the bokeh HTML report to this path (instead of Markdown) |
| `--periods` | – | restrict the report to these periods; space- or comma-separated; also (re)computes the missing monthly/daily rankings |
| `--top-n` | `25` | airports per chart |
| `--inline` | off | embed the bokeh resources so the page opens offline |
| `--weight` | `seats` | weight mode noted in the report header |

It reuses the ranking CSVs and only (re)computes the monthly/daily rankings that
are missing. Four charts, each with hover tooltips:

1. top-N airports, static vs temporal score, with a period selector;
2. rank change between months (dumbbell);
3. one airport's PageRank across daily/weekly windows, with an airport selector;
4. a map of airports (lon/lat) sized by PageRank; each point's hover tooltip
   shows ICAO, name, score and rank. The screenshot in the README uses a
   tooltip-styled callout for the top airport, captioned as a reproduction of
   the hover tooltip (a headless capture cannot reproduce a live hover).

`bokeh` is required only for this command; it is the optional `[viz]` extra and
the module reports a clear install hint when it is missing.

### Airport-name lookup

`src/airconnectivity/data/airport_names.csv` maps ICAO codes to names, filtered
from the [OurAirports](https://ourairports.com/data/) dataset (public domain;
the file header notes the source): 5,513 airports with an ICAO code, keeping
large/medium airports and any airport with scheduled service. A code that is not
in the table is shown as `"ICAO (name unknown)"` rather than blank.

## PageRank methods

- **Static weighted PageRank** uses networkx on the edge-weighted window graph
  (`alpha=0.85`).
- **Temporal PageRank** follows the streaming algorithm of Rozenshtein & Gionis,
  *Temporal PageRank* (ECML PKDD 2016), over the flight stream ordered by
  departure, with parameters `alpha` (jumping probability) and `beta`
  (transition probability, default 1.0). Walks follow only time-respecting
  connections: flight `b` connects after flight `a` when `a.ades == b.adep` and
  `mct(airport) <= dep_b - arr_a <= max_wait`, with a default **MCT of 45
  minutes** and **max wait of 6 hours** (per-airport MCT override via a dict or
  a CSV). The exact update rule is in the `temporal.py` module docstring.

## Regenerating the screenshots

`scripts/make_screenshots.py` rebuilds `docs/img/` from a fresh `--inline` report
run using headless Chromium (Playwright). See the script's docstring for usage.
