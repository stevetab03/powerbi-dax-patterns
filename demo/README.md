This is significantly out of date. Issues:

Intro says "two major geopolitical supply disruptions" — there are seven events
"Strait of Hormuz closure" framing — never used
Page 1 describes [DisruptionLabel] via USERELATIONSHIP — actual implementation uses [EventMarker] merged into fact table
Page 2 describes tenor slicer, Field Parameter, Dim_Tenor — none of that was built
Page 3 tau bins say "61-90 days" — actual bins start at 31-45d
Page 4 describes a summary matrix — actual is the disruption event table
Pipeline outputs list term_structure.csv — not used
Repo structure shows screenshots/ — replaced by analysis/
ORBIT section omits the actual ratio of 2.46

Here's the full replacement:

markdown# Demo — WTI Futures-Spot Basis Dashboard

A fully reproducible Power BI dashboard demonstrating advanced DAX
engineering patterns documented in this repository, built on publicly
available WTI crude oil data spanning January 2020 through April 2026
across seven major geopolitical and market disruption events.

---

## What This Demonstrates

The patterns folder documents the *architecture* of enterprise FP&A
reporting in Power BI. This demo applies those patterns to a real
dataset with a concrete analytical question:

> *The gap between WTI futures prices and spot prices must converge
> to zero at contract expiration — that is a contractual obligation.
> How does the structure of that convergence change as expiration
> approaches, and how do geopolitical shocks distort it?*

Each dashboard page directly exercises one or more of the documented
DAX patterns against this question. For full analytical results and
interpretation, see [`analysis/ANALYSIS.md`](analysis/ANALYSIS.md).

---

## Dashboard Pages

### Page 1 — Basis Time Series

WTI spot vs front-month futures over the full sample (Jan 2020 –
Apr 2026), with rolling 21-day basis volatility on a secondary axis
and seven geopolitical disruption events annotated as red markers.

**Patterns demonstrated:**

* `[EventMarker]` annotation — returns 0 on event dates via
  `IF(MAX(Fact_BasisPanel[event_label]) <> BLANK(), 0, BLANK())`,
  producing a dot series on the chart with event labels as tooltips.
  Event labels are merged into the fact table at pipeline time;
  the inactive relationship to `Dim_DisruptionEvents` is preserved
  for future use but not activated here
* `[BasisVol21d]` dual-axis overlay — precomputed rolling volatility
  surfaced as a measure on a secondary axis

**What to look for:** Three distinct regime breaks — the April 2020
COVID storage crisis (basis to +$6, vol to 2.0+), the Ukraine/WTI
$130 supply shock (2022), and the sustained 2026 US-Iran backwardation
regime culminating in a −$1.60 basis on the ceasefire date.

---

### Page 2 — Spot vs Front Month WTI

Spot price and front-month futures plotted over the full sample with
all seven disruption events annotated. An average basis KPI card
summarizes the mean spread of ($0.32) across the full period. A
date slicer allows zooming into specific windows for exploratory
analysis.

**Patterns demonstrated:**

* `[SpotPrice]` and `[FrontPrice]` as independent measure series —
  demonstrates clean measure separation where both series share an
  axis without a legend dimension
* Page-scoped date slicer — intentionally not synced to other pages,
  keeping Pages 3 and 4 anchored to the full sample while this page
  serves as an exploratory zoom tool

**What to look for:** How closely the two series track for most of
the sample — tight convergence discipline across six years — versus
the persistent backwardation visible in the 2026 escalation window.

---

### Page 3 — Variance Collapse

Bar chart of basis variance stratified by time-to-expiry bin
(`31-45d`, `22-30d`, `15-21d`, `8-14d`, `0-7d`), with a
`[VarianceCollapseRatio]` KPI card showing **2.46**.

**Patterns demonstrated:**

* `[BasisVarianceByBin]`: cross-bin `CALCULATE` override using
  `Dim_TauBin` filter manipulation — same filter context principle
  as Pattern 02 applied to a continuous numeric dimension
  discretized into categorical bins
* `[VarianceCollapseRatio]`: divides the highest-variance bin
  (22-30d, 0.80) by the lowest (8-14d, 0.31) using explicit
  bin-level CALCULATE filter extraction

**What to look for:** Variance collapsing ~60% from the 22-30d bin
to the sub-21-day bins. The ratio of 2.46 is the empirical test of
the ORBIT theoretical result.

---

### Page 4 — Disruption Event Analysis

A table isolating the seven most significant market disruption events
in the sample, showing exact trading-day price context (spot,
front-month, basis, 21-day rolling volatility) and analyst commentary.

**Patterns demonstrated:**

* `[My Remark]` as a DAX calculated column using `SWITCH` on
  `Dim_DisruptionEvents[event_label]` — analyst commentary encoded
  directly in the semantic model, keeping the model self-documenting
* Event dates snapped to nearest trading day in the pipeline —
  three of seven events required adjustment for weekends and
  market holidays before the fact table join

**What to look for:** Volatility is not proportional to price level
— the $130 WTI peak shows only 0.14 vol while the −$37 event shows
2.30. The 2026 US-Iran sequence traces a complete price discovery
cycle across three annotated events in six weeks.

---

## Reproducing This Dashboard

### Step 1 — Get an EIA API key

Register at <https://www.eia.gov/opendata/register.php>

### Step 2 — Install dependencies
cd demo/data
pip install -r requirements.txt

### Step 3 — Run the pipeline
python pipeline.py --eia_key YOUR_KEY --start 2020-01-01

Output: CSV files in `demo/data/outputs/powerbi/`
basis_panel_clean.csv        daily panel with event labels merged in — primary fact table
variance_by_tau.csv          tau-stratified variance — Page 3
disruption_events_clean.csv  event annotations with snapped trading dates and remarks

**Note on date snapping:** Event dates falling on weekends or market
holidays are snapped to the nearest trading day in the pipeline.
Hamas Attack (Oct 7 → Oct 6), US-Iran War Begins (Feb 28 → Feb 27),
and US-Iran Ceasefire (Apr 7 → Apr 6) were all adjusted.

### Step 4 — Build in Power BI Desktop

Follow [`powerbi/data_model.md`](powerbi/data_model.md) for the
complete schema, relationships, and calculated table DAX.

Follow [`powerbi/measures.md`](powerbi/measures.md) for all measure
definitions, folder structure, and visual configuration notes.

**Important:** Enable PBIP format before saving:
`Options → Preview Features → Power BI Project (.pbip)`

This ensures the file is committed as diffable source, not a binary
blob.

---

## Repository Structure
demo/
├── README.md
├── data/
│   ├── pipeline.py
│   ├── requirements.txt
│   └── sample/
│       ├── basis_panel_sample.csv
│       └── disruption_events.csv
├── powerbi/
│   ├── data_model.md
│   └── measures.md
├── analysis/
│   ├── ANALYSIS.md
│   └── images/
│       ├── 01_basis_time_series.png
│       ├── 02_term_structure.png
│       ├── 03_variance_collapse.png
│       └── 04_event_table.png
├── WTI_Basis_Dashboard.pbip
├── WTI_Basis_Dashboard.Report/
└── WTI_Basis_Dashboard.SemanticModel/

---

## Data Sources

| Source | Data | License |
| --- | --- | --- |
| [EIA API v2](https://www.eia.gov/opendata/) | WTI spot price, daily | US Government open data — no restrictions |
| [Yahoo Finance](https://finance.yahoo.com) via yfinance | WTI front-month futures, daily | Public market data |

---

## Connection to ORBIT

The `variance_by_tau.csv` output and Page 3 of this dashboard
constitute an empirical validation of **Theorem 1** from the
[ORBIT monograph](https://github.com/stevetab03/ORBIT):

> *σ²\_e(τ) = O(1/a(τ)) → 0 as τ → 0*

The `[VarianceCollapseRatio]` of **2.46** quantifies the result
directly: variance in the 22-30 day bin is 2.46× the variance in
the final week before expiration. The convergence mechanism that
ORBIT formalizes mathematically is visible in the data.

This is the bridge between the mathematical framework in ORBIT
and the BI engineering in this repository.
