# Demo — WTI Futures-Spot Basis Dashboard

A fully reproducible Power BI dashboard demonstrating the four DAX
patterns documented in this repository, built on publicly available
WTI crude oil data spanning two major geopolitical supply disruptions.

---

## What This Demonstrates

The patterns folder documents the *architecture* of enterprise FP&A
reporting in Power BI. This demo applies those patterns to a real
dataset with a concrete analytical question:

> *The gap between WTI futures prices and spot prices must converge
> to zero at contract expiration — that is a contractual obligation.
> How does the structure of that convergence change as expiration
> approaches, and how did the 2022 Ukraine invasion and 2026 Strait
> of Hormuz closure distort it?*

Each dashboard page directly exercises one or more of the documented
patterns against this question.

---

## Dashboard Pages

### Page 1 — Basis Time Series

WTI spot vs front-month futures over the full date range, with
rolling 21-day basis volatility on a secondary axis and annotated
vertical reference lines for geopolitical disruption events.

**Patterns demonstrated:**
- `[DisruptionLabel]` annotation via `USERELATIONSHIP` on an
  inactive relationship — the event reference table never filters
  the fact data, but activates on demand for labeling
- `[BasisVol21d]` dual-axis overlay

**What to look for:** The basis spike in March 2026 when Brent
spot reached $124.68 against $94.75 June futures — a $30 gap
driven by the Strait of Hormuz closure. The rolling volatility
series shows the regime shift clearly.

---

### Page 2 — Term Structure

Front, second, and third month futures alongside spot, with a
tenor slicer and a Field Parameter allowing the y-axis to switch
between basis, futures price, rolling volatility, and term spread.

**Patterns demonstrated:**
- Pattern 02 adapted to tenor dispatch: `Dim_Tenor` plays the
  role of `Dim_LegendSeries`. The tenor slicer overrides are
  handled via the same `REMOVEFILTERS` + explicit predicate
  pattern as the forecast scenario dispatch
- Field Parameter for dynamic metric selection — a modern Power BI
  feature (2022+) that eliminates the need for duplicate visuals

**What to look for:** The term spread (second minus front) inverts
during backwardation episodes. During the 2026 crisis the front
month surges while second and third month remain suppressed —
the market pricing a recovery that the physical market had not yet
confirmed.

---

### Page 3 — Variance Collapse

Bar chart of basis variance stratified by time-to-expiry bin
(61-90 days through 0-7 days), with a `[VarianceCollapseRatio]`
KPI card.

**Patterns demonstrated:**
- `[BasisVarianceByBin]`: cross-bin `CALCULATE` override using
  `Dim_TauBin` filter manipulation — same filter context principle
  as Pattern 02 applied to a different dimension
- `[VarianceCollapseRatio]`: explicit bin-level filter extraction

**What to look for:** Variance should decrease monotonically from
the 61-90d bin toward the 0-7d bin. This is the empirical test of
the ORBIT theoretical result — basis variance is proportional to
`1/a(τ)` and collapses as expiration forces convergence. If the
ratio is substantially greater than 1, the data supports the theory.

---

### Page 4 — Summary Matrix

A matrix visual showing spot price, basis, term spread, and rolling
volatility across calendar periods, with variance columns (Δ vs
prior period, Δ% annualized).

**Patterns demonstrated:**
- Pattern 04 two-layer display architecture: `Dim_LineFormat`
  mapping table drives row-level scaling and format selection
- Pattern 03 hybrid axis: `Dim_AxisConfig` UNION combines monthly
  periods with an FY aggregate column on the same axis

---

## Reproducing This Dashboard

### Step 1 — Get an EIA API key

Register at https://www.eia.gov/opendata/register.php

### Step 2 — Install dependencies

```bash
cd demo/data
pip install -r requirements.txt
```

### Step 3 — Run the pipeline

```bash
python pipeline.py --eia_key YOUR_KEY --start 2020-01-01
```

Output: four CSV files in `demo/data/outputs/powerbi/`

```
basis_panel.csv          daily panel — primary fact table
variance_by_tau.csv      tau-stratified variance — Page 3
term_structure.csv       long-format tenor data — Page 2
disruption_events.csv    event annotations — Page 1
```

### Step 4 — Build in Power BI Desktop

Follow [`powerbi/data_model.md`](powerbi/data_model.md) for the
complete schema, relationships, and calculated table DAX.

Follow [`powerbi/measures.md`](powerbi/measures.md) for all measure
definitions, folder structure, and visual configuration notes.

**Important:** Enable PBIP format before saving:
`Options → Preview Features → Power BI Project (.pbip)`

This ensures the file is committed as diffable source, not a
binary blob.

---

## Repository Structure

```
demo/
├── README.md                    ← this file
│
├── data/
│   ├── pipeline.py              ← data ingestion and basis computation
│   ├── requirements.txt
│   └── sample/
│       ├── basis_panel_sample.csv        ← 90-day sample (no Python needed)
│       └── disruption_events.csv         ← static reference table
│
├── powerbi/
│   ├── data_model.md            ← schema, relationships, calculated tables
│   └── measures.md              ← all DAX measures with architecture notes
│
├── WTI_Basis_Dashboard.pbip            ← PBIP entry point
├── WTI_Basis_Dashboard.SemanticModel/  ← data model (fully diffable TMDL)
└── WTI_Basis_Dashboard.Report/         ← report layout (fully diffable JSON)
```

---

## Data Sources

| Source | Data | License |
|--------|------|---------|
| [EIA API v2](https://www.eia.gov/opendata/) | WTI spot price, daily | US Government open data — no restrictions |
| [Yahoo Finance](https://finance.yahoo.com) via yfinance | WTI futures (3 tenors), daily | Public market data |

---

## Connection to ORBIT

The `variance_by_tau.csv` output and Page 3 of this dashboard
constitute an empirical validation of **Theorem 1** from the
[ORBIT monograph](https://github.com/stevetab03/ORBIT):

> *σ²_e(τ) = O(1/a(τ)) → 0 as τ → 0*

The dashboard visualizes whether basis variance decreases
monotonically as time-to-expiry approaches zero — the empirical
test of the theoretical prediction. The `[VarianceCollapseRatio]`
KPI quantifies the effect in a single interpretable number.

This is the bridge between the mathematical framework in ORBIT
and the BI engineering in this repository.
