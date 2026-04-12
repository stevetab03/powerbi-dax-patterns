# Pattern 02 — Cross-Scenario Aggregation via SWITCH Dispatch

**Category:** Scenario Management · Filter Context  
**Applies to:** Power BI Desktop / Service  
**Complexity:** Advanced  

---

## Problem Statement

Multi-scenario FP&A visuals require simultaneous rendering of Plan,
Forecast, and Actual values as independent series on the same chart.
A standard scenario slicer collapses all three into the single
selected scenario, making side-by-side comparison impossible without
explicit filter context management.

The core challenge: each series must behave as if the slicer does
not exist for its own scenario predicate, while still respecting all
other active filters (entity, account, date range, region).

---

## Architecture

```
Dim_LegendSeries
  SeriesLabel: Plan / Forecast / Actual
  SortOrder:   1    / 2        / 3
       │
       │  SELECTEDVALUE drives dispatch
       ▼
[ScenarioDispatch]  ←── SWITCH on SeriesLabel
       │
       ├── Plan branch:     REMOVEFILTERS → explicit PLAN predicate
       ├── Forecast branch: REMOVEFILTERS → dynamic scenario predicate
       └── Actual branch:   REMOVEFILTERS → period-indexed predicate
                                            + temporal cutoff gate
```

`Dim_LegendSeries` is a disconnected helper table — no relationship
to the fact table. It drives the measure via `SELECTEDVALUE`, not
filter propagation. This is intentional: the legend must not
participate in cross-filtering.

---

## The Resolution Variable Block

Every scenario-aware measure opens with the same variable block
that resolves the active scenario state from slicer context:

```
_ActiveScenarioKey   ← SELECTEDVALUE from scenario slicer
_ActivePeriodIndex   ← integer extracted from scenario identifier
_CutoffPeriod        ← derived from PeriodIndex or system date + lag
_SeriesLabel         ← SELECTEDVALUE from Dim_LegendSeries
_VisualPeriod        ← SELECTEDVALUE from date axis
```

The lag constant in `_CutoffPeriod` is the only hard-coded value
in the entire pattern. It reflects the organization's financial
close schedule — the number of periods between period-end and
confirmed actuals publication. Everything else is derived.

---

## Dispatch Structure

```
SWITCH( _SeriesLabel,

  "Plan"     → CALCULATE( [Metric], remove scenario filter,
                           apply explicit PLAN predicate )

  "Forecast" → CALCULATE( [Metric], remove scenario filter,
                           apply dynamic period-index predicate )

  "Actual"   → IF( _VisualPeriod <= _CutoffPeriod,
                   CALCULATE( [Metric], remove scenario filter,
                               apply period-indexed predicate ),
                   BLANK() )
)
```

The `REMOVEFILTERS` in each branch operates at the column level,
not the table level. This removes the slicer's influence on the
scenario column while preserving all other active filters. Using
`ALL( FactTable )` would strip user-set slicers entirely — a
common mistake that produces correct results in testing but breaks
in production when regional or entity slicers are active.

---

## Advanced Variant — Retrospective Accuracy Layer

The standard Forecast branch above shows the currently selected
scenario's forward projection for all periods. This is correct
for a planning visual but analytically weak: it tells you what
the current scenario predicts, not how accurate prior forecasts
were.

The advanced variant introduces a **predictive accuracy split**
in the Forecast branch:

```
IF _VisualPeriod is finalized (≤ cutoff):
    → show the front-month scenario prediction for that period
      (i.e., what was forecast when that period was still future)

IF _VisualPeriod is future (> cutoff):
    → show the currently selected scenario's forward projection
```

The result is a Forecast series that carries historical accuracy
information on its left side and forward projection on its right —
a single continuous line encoding two different analytical questions.

### The Non-Obvious Filter Problem

The future-period branch requires removing two columns from the
filter context simultaneously, not one. Removing only the scenario
column leaves a residual period filter propagated from the date
axis context. This residual filter restricts the scenario lookup
to a single period, returning incorrect values that are easy to
miss in testing because they appear plausible at first inspection.

The correct solution removes both the period label column and the
scenario column before re-applying the explicit scenario predicate.
This is the minimal intervention — removing anything beyond these
two columns risks stripping user-set filters the visual depends on.

### COALESCE vs BLANK

The Forecast branch uses `COALESCE( result, 0 )` rather than
allowing `BLANK()`. The Actual branch uses `BLANK()` explicitly
for future periods.

This distinction is not cosmetic. `BLANK()` in a line chart
suppresses the data point and breaks the line. `0` keeps the
line continuous. Forecast must remain a continuous line across
all periods — even where the value approaches zero — because a
broken forecast line is visually indistinguishable from missing
data. Actual must break at the cutoff because there is no actual
value for future periods and implying zero would be misleading.

---

## Visual Field Configuration

| Field well | Source |
|---|---|
| X-axis | `Dim_AxisConfig[PeriodLabel]` (Pattern 03) |
| Y-axis | `[ScenarioDispatch_YourMetric]` |
| Legend | `Dim_LegendSeries[SeriesLabel]` |
| Sort legend by | `Dim_LegendSeries[SortOrder]` |
| Slicer | `Dim_Scenario[ScenarioAlias]` |

---

## Diagnostic Measures

Before using the dispatch measure in a visual, validate the
resolution block with isolated diagnostic measures:

```
TestCutoff    = [_CutoffPeriod]
TestSeries    = SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )
TestPeriod    = SELECTEDVALUE( Dim_Date[MonthNumber] )
TestScenario  = SELECTEDVALUE( Dim_Scenario[ScenarioKey] )
```

Place each in a card visual with the scenario slicer active.
Verify the resolved values match expectations before debugging
the dispatch logic itself. Most production issues trace to the
resolution block, not the SWITCH branches.

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| All series identical | Column-scoped `REMOVEFILTERS` missing | Verify `REMOVEFILTERS( Fact[ScenarioKey] )` in every branch |
| Forecast flat in retrospective variant | Single-column removal leaving period residual | Extend to dual-column `REMOVEFILTERS` in future-period sub-branch |
| Forecast line breaks at cutoff | `BLANK()` used instead of `COALESCE` | Wrap forecast result in `COALESCE( ..., 0 )` |
| Actual visible for future periods | Cutoff condition inverted | Confirm `<=` direction in temporal gate |
| Legend renders out of order | Sort column not configured | Set `SeriesLabel` sort column to `SortOrder` |

---

## Reuse Checklist

- [ ] Create `Dim_LegendSeries` with no relationship to fact table
- [ ] Identify the scenario key column and period index attribute in your model
- [ ] Define your reporting lag constant
- [ ] Decide: standard variant or retrospective accuracy variant
- [ ] Build diagnostic measures before the dispatch measure
- [ ] Validate all three branches in isolation before combining
