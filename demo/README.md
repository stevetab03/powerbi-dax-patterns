# Demo — WTI Futures-Spot Basis Dashboard

A fully reproducible Power BI dashboard demonstrating advanced DAX
engineering patterns documented in this repository, built on publicly
available WTI crude oil data spanning six years and seven major
geopolitical and market disruption events.

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
DAX patterns against this question, using a data model and measure
architecture that mirrors what would be deployed in a production
enterprise FP&A environment.

---

## Dashboard Pages

### Page 1 — Basis Time Series

WTI spot vs front-month futures over the full sample (Jan 2020 –
Apr 2026), with rolling 21-day basis volatility on a secondary axis
and annotated vertical reference lines marking seven geopolitical
disruption events.

**Patterns demonstrated:**

* `[DisruptionLabel]` annotation via `USERELATIONSHIP` on an
  inactive relationship — `Dim_DisruptionEvents` never filters the
  fact data during normal operation but is activated on demand for
  event labeling, keeping the model clean while supporting
  contextual annotation
* `[BasisVol21d]` dual-axis overlay — a precomputed rolling
  volatility series surfaced as a measure, demonstrating how
  pipeline-computed values integrate cleanly with DAX measures in
  the same visual

**What to look for:** The persistent contango structure that held
through most of 2020–2025, the Ukraine-driven inversion in early
2022, and the sharp backwardation regime that developed in Q1 2026
as the US-Iran escalation drove spot above front-month by over
$1.60/bbl.

---

### Page 2 — Term Structure

Spot price vs front-month futures over a user-controlled date range,
with an average basis KPI card showing the mean spread for the
selected window.

**Patterns demonstrated:**

* Date slicer scoped to this page only — intentional design choice
  to allow exploratory zooming without contaminating the full-sample
  summary on Page 4. Page-level vs report-level filter scope managed
  deliberately via Sync Slicers configuration
* `[SpotPrice]` and `[FrontPrice]` as independent measure series on
  the same axis — demonstrates clean separation of concerns between
  measures that could otherwise be collapsed into a single series
  with a legend dimension

**What to look for:** The two series track within cents for most of
the sample — the market maintained tight convergence discipline. The
divergence visible in the Feb–Apr 2026 window, where spot ran $1–2
above front-month, is the backwardation episode that Page 3
quantifies and Page 4 contextualizes.

---

### Page 3 — Variance Collapse

Bar chart of basis variance stratified by time-to-expiry bin
(`31-45d`, `22-30d`, `15-21d`, `8-14d`, `0-7d`), with a
`[VarianceCollapseRatio]` KPI card quantifying the effect.

**Patterns demonstrated:**

* `[BasisVarianceByBin]`: cross-bin `CALCULATE` override using
  `Dim_TauBin` filter manipulation — the same filter context
  principle as Pattern 02 applied to a continuous numeric dimension
  discretized into categorical bins. Each bar requires an explicit
  filter predicate that overrides the visual's row context
* `[VarianceCollapseRatio]`: divides the 31-45d bin variance by the
  0-7d bin variance using explicit bin-level filter extraction —
  a single interpretable KPI that summarizes the entire convergence
  dynamic

**What to look for:** Variance decreasing from 0.80 at `22-30d` to
0.31–0.33 at `8-14d` and `0-7d`. The ratio of 2.46 confirms the
ORBIT theoretical prediction — basis variance is proportional to
`1/a(τ)` and collapses as expiration forces convergence. A ratio
substantially greater than 1.0 is the empirical test.

---

### Page 4 — Disruption Event Analysis

An event-driven table isolating the seven most significant market
disruption events in the sample period, with spot price, front-month
price, basis, rolling volatility, and analyst commentary for each
event date.

**Patterns demonstrated:**

* `Dim_DisruptionEvents[My Remark]` as a calculated column using
  `SWITCH` — demonstrates how qualitative analyst commentary can be
  encoded directly in the semantic model rather than maintained in
  an external document, keeping the model self-documenting
* Event dates snapped to nearest trading day in the pipeline — the
  `disruption_events_clean.csv` accounts for weekends and market
  holidays before the data reaches Power BI, a critical data
  engineering step given FRED's publication schedule. Three of seven
  events required snapping: Hamas Attack (Oct 7 → Oct 6), US-Iran
  War Begins (Feb 28 → Feb 27), US-Iran Ceasefire (Apr 7 → Apr 6)
* `event_label` column merged directly into `basis_panel_clean`
  at pipeline time, eliminating the need for an active relationship
  to `Dim_DisruptionEvents` for the table visual — the inactive
  relationship is preserved for Page 1 annotation only

**What to look for:** The WTI Negative Price event (Apr 20, 2020)
dominates with a basis volatility of 2.30 — an order of magnitude
above the typical regime. Ukraine Invasion (0.40) is the only other
event approaching that level. The WTI $130 Peak (Mar 8, 2022) shows
only 0.14 volatility because the shock had already been absorbed —
price level and volatility are not the same thing. The 2026 events
cluster in a moderate 0.19–0.85 range reflecting an elevated but
structured geopolitical risk premium rather than the disorderly
conditions of 2020.

---

## Reproducing This Dashboard

### Step 1 — Get an EIA API key

Register at <https://www.eia.gov/opendata/register.php>

### Step 2 — Install dependencies

```
cd demo/data
pip install -r requirements.txt
```

### Step 3 — Run the pipeline

```
python pipeline.py --eia_key YOUR_KEY --start 2020-01-01
```

Output: CSV files in `demo/data/outputs/powerbi/`

```
basis_panel_clean.csv      daily panel with event labels merged in — primary fact table
variance_by_tau.csv        tau-stratified variance — Page 3
disruption_events_clean.csv  event annotations with snapped trading dates and remarks
```

**Note on date snapping:** FRED publishes WTI spot data on trading
days only. Event dates that fall on weekends or market holidays are
snapped to the nearest trading day in the pipeline before any join
is attempted. This is handled in `pipeline.py` and documented in
the commit history. Do not manually edit event dates in the CSV —
re-run the pipeline if events need updating.

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

```
demo/
├── README.md                    ← this file
│
├── data/
│   ├── pipeline.py              ← data ingestion, basis computation, event snapping
│   ├── requirements.txt
│   └── outputs/
│       └── powerbi/
│           ├── basis_panel_clean.csv
│           ├── variance_by_tau.csv
│           └── disruption_events_clean.csv
│
├── powerbi/
│   ├── data_model.md            ← schema, relationships, calculated tables
│   └── measures.md              ← all DAX measures with architecture notes
│
├── WTI_Basis_Dashboard.pbip
├── WTI_Basis_Dashboard.SemanticModel/
└── WTI_Basis_Dashboard.Report/
```

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

The dashboard visualizes whether basis variance decreases
monotonically as time-to-expiry approaches zero — the empirical
test of the theoretical prediction. The `[VarianceCollapseRatio]`
KPI of **2.46** quantifies the effect: variance in the 22-30 day
bin is 2.46× higher than in the 0-7 day bin, consistent with the
theoretical convergence forcing mechanism.

This is the bridge between the mathematical framework in ORBIT
and the BI engineering in this repository — the same result, read
from two different directions.
