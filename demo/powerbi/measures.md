# DAX Measures — WTI Basis Dashboard

**Measure organization:** All measures live in `Fact_BasisPanel`  
**Folder structure:** Create display folders in the model view  

```
Fact_BasisPanel/
├── _Core/
│   ├── [SpotPrice]
│   ├── [FrontPrice]
│   ├── [BasisFront]
│   ├── [BasisSecond]
│   ├── [TermSpread]
│   └── [StructureFlag]
├── _Volatility/
│   ├── [BasisVol21d]
│   ├── [BasisVar21d]
│   └── [RealizedVol]
├── _TenorDispatch/
│   ├── [TenorBasis]
│   └── [TenorPrice]
├── _TauAnalysis/
│   ├── [BasisVarianceByBin]
│   └── [VarianceCollapseRatio]
└── _Annotation/
    └── [DisruptionLabel]
```

---

## Folder: _Core

### [SpotPrice]

```
Purpose:  Average WTI spot price for the selected period.
Visual:   KPI card, time series reference line.
```

Architecture: Simple average of the spot price column. Uses `AVERAGE`
rather than `SUM` because spot price is a rate, not an additive quantity.
A sum of daily prices is meaningless; an average of daily prices represents
the period's central tendency.

```
Base:   AVERAGE( Fact_BasisPanel[spot_price] )
Filter: Inherits from Dim_Date via active relationship.
```

---

### [FrontPrice]

```
Purpose:  Average WTI front-month futures price.
Visual:   Time series alongside [SpotPrice].
```

Same pattern as `[SpotPrice]`. The spread between these two lines
is the visual representation of the basis before formal computation.

---

### [BasisFront]

```
Purpose:  Average front-month basis: F_t - S_t.
Visual:   Primary time series, KPI card, distribution chart.
Note:     This is the raw basis (lambda = 1).
          The ORBIT-calibrated lambda-adjusted basis requires
          the calibration module output — documented separately.
```

Architecture: Average of the pre-computed `basis_front` column.
The column-level computation (futures minus spot) is done in Python
during pipeline execution — Power BI measures aggregate the result,
not recompute it. This is intentional: the transformation belongs in
the data preparation layer, not the reporting layer.

```
Base:   AVERAGE( Fact_BasisPanel[basis_front] )
```

---

### [BasisSecond]

```
Purpose:  Average second-month basis.
Visual:   Term structure comparison alongside [BasisFront].
```

---

### [TermSpread]

```
Purpose:  Average spread between second and front month futures.
          Positive = contango steepening. Negative = backwardation.
Visual:   Secondary axis on term structure chart.
          Color-coded by sign: green (contango) / red (backwardation).
```

---

### [StructureFlag]

```
Purpose:  Percentage of days in contango for the selected period.
Visual:   KPI card with target line at 50%.
```

Architecture: Divides the count of contango days by total days.
Uses `COUNTROWS` with a filter rather than `AVERAGE` of the flag column —
the latter works but `COUNTROWS` is more explicit about the intent.

```
Numerator:   COUNTROWS( FILTER( Fact_BasisPanel, [contango_flag] = 1 ) )
Denominator: COUNTROWS( Fact_BasisPanel )
Result:      DIVIDE( numerator, denominator, BLANK() )
Format:      Percentage, 1 decimal place
```

---

## Folder: _Volatility

### [BasisVol21d]

```
Purpose:  Latest 21-day rolling basis volatility (std dev).
Visual:   Secondary axis on basis time series.
          Represents uncertainty in the convergence path.
Note:     This is the empirical sigma_e(tau) from ORBIT theory.
```

Architecture: The rolling volatility is pre-computed by the pipeline
and stored in `basis_vol_21d`. The measure selects the most recent
value in the filter context — not an average, because volatility
at a point in time is what matters for interpretation.

```
Base:    column Fact_BasisPanel[basis_vol_21d]
Measure: returns the value for the latest date in context,
         or average over the selected period depending on visual
```

---

### [RealizedVol]

```
Purpose:  Realized volatility of spot price returns (annualized).
          Standard 21-day window, annualized by sqrt(252).
Visual:   Volatility regime context panel.
          Distinguishes high-vol geopolitical periods from normal.
```

Architecture: Requires computing log returns within DAX using
`EARLIER` or `OFFSET` — a non-trivial measure that demonstrates
time-series computation in DAX. The key is using `CALCULATE` with
`OFFSET` (Power BI 2023+) to access the prior row's value without
a self-join.

This is one of the measures worth documenting carefully in the
TMDL file because it shows modern DAX function usage.

```
Step 1: Log return at date t = LN( spot_t / spot_{t-1} )
Step 2: Rolling variance over 21 days of log returns
Step 3: Annualize: variance * 252
Step 4: Std dev: SQRT( annualized variance )
```

---

## Folder: _TenorDispatch

### [TenorBasis]

```
Purpose:  Basis for the tenor selected via Dim_Tenor slicer.
          Adapts Pattern 02 (cross-scenario dispatch) to tenor selection.
Visual:   Main line chart on Page 2 — Term Structure.
```

Architecture: This is Pattern 02 adapted to tenor context instead
of forecast scenario context. `Dim_Tenor[tenor_label]` plays the
role of `Dim_LegendSeries[SeriesLabel]`. The dispatch logic selects
the correct basis column per tenor using `SWITCH` on the selected
tenor key.

The structural insight carried forward from Pattern 02: each branch
must remove the tenor filter before re-applying an explicit tenor
predicate, otherwise cross-filtering from the slicer collapses all
tenors to the selected one.

```
Variable block:
  _TenorKey = SELECTEDVALUE( Dim_Tenor[tenor_key] )

Dispatch:
  SWITCH( _TenorKey,
    "front"  → [BasisFront],
    "second" → [BasisSecond],
    "third"  → AVERAGE( Fact_BasisPanel[basis_third] ),
    [BasisFront]   -- default to front if no selection
  )
```

Note: unlike Pattern 02, the tenor dispatch does not require
`REMOVEFILTERS` because `Dim_Tenor` connects to `Fact_TermStructure`,
not `Fact_BasisPanel`. The relationship architecture naturally
isolates the filter context. This is an example of where correct
schema design eliminates DAX complexity.

---

### [TenorPrice]

```
Purpose:  Futures price for the selected tenor.
          Paired with [SpotPrice] to show convergence visually.
Visual:   Page 2 dual-line chart: spot vs selected-tenor futures.
```

Same dispatch pattern as `[TenorBasis]` but returning the price
rather than the basis.

---

## Folder: _TauAnalysis

### [BasisVarianceByBin]

```
Purpose:  Basis variance for the tau bin in context.
          Primary measure for the ORBIT Theorem 1 validation chart.
Visual:   Page 3 — bar chart, tau bin on x-axis, variance on y-axis.
          Expected shape: monotonically decreasing left to right
          (variance collapses as tau approaches zero).
```

Architecture: `Fact_VarianceByTau` is already aggregated by the
pipeline — one row per tau bin. This measure simply reads the
pre-aggregated value. The complexity is in the visual configuration:
the tau bins must be sorted by `Dim_TauBin[sort_order]` or they
render alphabetically, destroying the convergence narrative.

```
Base:   SUM( Fact_VarianceByTau[basis_variance] )
```

The SUM here aggregates over a single row in context (one bin
is selected by the axis) — it is effectively a lookup, but
`SUM` is the correct DAX pattern for a fact table measure
regardless of grain.

---

### [VarianceCollapseRatio]

```
Purpose:  Ratio of variance in the 61-90d bin to the 0-7d bin.
          Single-number summary of the convergence effect.
Visual:   KPI card on Page 3.
          Ratio >> 1 confirms variance collapse.
          Ratio near 1 suggests no convergence structure in data.
```

Architecture: Uses `CALCULATE` with explicit tau bin filters to
extract variance from specific bins, then divides. Demonstrates
cross-filter override pattern from Pattern 02 at the bin level.

```
VAR _var_far  = CALCULATE( [BasisVarianceByBin],
                            Dim_TauBin[tau_bin] = "61-90d" )
VAR _var_near = CALCULATE( [BasisVarianceByBin],
                            Dim_TauBin[tau_bin] = "0-7d" )
RETURN DIVIDE( _var_far, _var_near, BLANK() )

Format: Decimal, 2 places. Label: "×" suffix (e.g. "4.2×")
```

---

## Folder: _Annotation

### [DisruptionLabel]

```
Purpose:  Returns the event label for a given date if a disruption
          event is annotated on that date. BLANK() otherwise.
Visual:   Reference line labels on Page 1 time series.
          Tooltip on any visual showing event context.
```

Architecture: Uses `USERELATIONSHIP` to activate the otherwise
inactive relationship between `Dim_Date` and `Dim_DisruptionEvents`.
This is the correct pattern for annotation layers — the relationship
stays inactive so events do not filter the fact table, but measures
can activate it on demand.

```
CALCULATE(
    SELECTEDVALUE( Dim_DisruptionEvents[event_label] ),
    USERELATIONSHIP( Dim_Date[Date], Dim_DisruptionEvents[event_date] )
)
```

To add vertical reference lines: use the Analytics pane in the
time series visual, add a Constant Line per event date, and set
the label to this measure.

---

## Page Layout Reference

| Page | Title | Primary Visual | Key Measure | Key DAX Feature |
|------|-------|---------------|-------------|-----------------|
| 1 | Basis Time Series | Line chart | `[BasisFront]` + `[BasisVol21d]` | `[DisruptionLabel]` annotation via `USERELATIONSHIP` |
| 2 | Term Structure | Multi-line + scatter | `[TenorBasis]` | `[TenorDispatch]` SWITCH pattern |
| 3 | Variance Collapse | Bar chart + KPI | `[BasisVarianceByBin]` | `[VarianceCollapseRatio]` cross-bin CALCULATE |
| 4 | Summary Matrix | Matrix visual | All core measures | Pattern 04 two-layer display architecture |

---

## Field Parameters (JD requirement — modern Power BI feature)

Add a Field Parameter to Page 2 to allow the user to switch the
y-axis between basis metrics without changing the visual:

```
Metric Selector =
{
    ("Basis ($/BBL)",     NAMEOF( [BasisFront] ),    0),
    ("Futures Price",     NAMEOF( [FrontPrice] ),    1),
    ("Rolling Vol",       NAMEOF( [BasisVol21d] ),   2),
    ("Term Spread",       NAMEOF( [TermSpread] ),    3)
}
```

Field Parameters are a modern Power BI feature (2022+) explicitly
listed in the JD. Using one here directly addresses that requirement.

---

## Performance Optimization Notes

With ~1,500 rows, this model has no performance challenges. These
notes document the practices applied — relevant for the enterprise
contexts this repo references:

**Variable declarations in all measures.** Every measure uses `VAR`
blocks for intermediate computations rather than nesting functions.
This ensures each sub-expression is computed once, not repeatedly.

**No bidirectional cross-filtering.** All relationships are single-
direction. Bidirectional filtering creates ambiguous filter paths
and unpredictable measure behavior at scale.

**Inactive relationship for annotations.** The `Dim_DisruptionEvents`
relationship is inactive. Active relationships participate in all
filter propagation — an annotation table should never filter your
facts. `USERELATIONSHIP` activates it only where explicitly needed.

**Pre-computed columns in Python.** Rolling variance, tau, tau bins,
basis — all computed in the pipeline, not in DAX. DAX row-level
iteration (`SUMX`, `FILTER` over large tables) is expensive. Push
transformations upstream to Power Query or Python wherever possible.
