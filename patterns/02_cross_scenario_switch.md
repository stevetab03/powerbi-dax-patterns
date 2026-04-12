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
explicit filter context override.

This pattern constructs a **SWITCH dispatch measure** that intercepts
the active filter context per series, removes the slicer's scenario
constraint, and re-applies an explicit scenario predicate for each
branch independently.

---

## Architecture

Three model components work together:

```
Dim_LegendSeries                    Dim_Scenario
  SeriesKey   SeriesLabel SortOrder   ScenarioKey  PeriodIndex  ScenarioType
  ─────────   ─────────── ─────────   ───────────  ───────────  ────────────
  SRS_001     Plan        1           PLAN_FY26    0            PLAN
  SRS_002     Forecast    2           FCST_P01     1            FORECAST
  SRS_003     Actual      3           FCST_P06     6            FORECAST
                                      FCST_P09     9            FORECAST
         │                                    │
         └──────── drives ──────────────────────────── [ScenarioDispatch] ──────► visual
```

`Dim_LegendSeries` is a static helper table that defines the legend
categories. It has no relationship to the fact table — it drives
the measure via `SELECTEDVALUE`, not via filter propagation.

---

## Component 1 — Dim_LegendSeries Helper Table

```dax
Dim_LegendSeries =
DATATABLE(
    "SeriesKey",   STRING,
    "SeriesLabel", STRING,
    "SortOrder",   INTEGER,
    {
        { "SRS_001", "Plan",     1 },
        { "SRS_002", "Forecast", 2 },
        { "SRS_003", "Actual",   3 }
    }
)
```

---

## Component 2 — The Resolution Variable Block

```dax
-- ── Scenario resolution ──────────────────────────────────────────────
VAR _ActiveScenarioKey =
    SELECTEDVALUE( Dim_Scenario[ScenarioKey], "CURRENT" )

VAR _ActivePeriodIndex =
    COALESCE(
        SELECTEDVALUE( Dim_Scenario[PeriodIndex] ),
        MONTH( TODAY() ) - 2
    )

VAR _CutoffPeriod =
    IF(
        _ActiveScenarioKey = "CURRENT",
        MONTH( TODAY() ) - 2,
        _ActivePeriodIndex
    )

VAR _SeriesLabel  = SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )
VAR _VisualPeriod = SELECTEDVALUE( Dim_Date[MonthNumber] )
```

---

## Component 3 — Standard SWITCH Dispatch

```dax
[ScenarioDispatch_Amount] =

VAR _ActiveScenarioKey  = SELECTEDVALUE( Dim_Scenario[ScenarioKey], "CURRENT" )
VAR _ActivePeriodIndex  = COALESCE( SELECTEDVALUE( Dim_Scenario[PeriodIndex] ),
                                     MONTH(TODAY()) - 2 )
VAR _CutoffPeriod       = IF( _ActiveScenarioKey = "CURRENT",
                               MONTH(TODAY()) - 2, _ActivePeriodIndex )
VAR _SeriesLabel        = SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )
VAR _VisualPeriod       = SELECTEDVALUE( Dim_Date[MonthNumber] )

RETURN
SWITCH(
    _SeriesLabel,

    "Plan",
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
        Dim_Scenario[ScenarioType] = "PLAN"
    ),

    "Forecast",
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
        Dim_Scenario[PeriodIndex] = _CutoffPeriod - 1
    ),

    "Actual",
    IF(
        _VisualPeriod <= _CutoffPeriod,
        CALCULATE(
            [Amount],
            REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
            Dim_Scenario[PeriodIndex] = _VisualPeriod
        )
    ),

    BLANK()
)
```

---

## Advanced Variant — Retrospective Forecast Accuracy Layer

The standard Forecast branch shows a single forward-looking series.
This variant **splits the Forecast branch by whether the period has
been finalized**, enabling visual comparison of what was predicted
versus what was subsequently realized — on the same series line,
without a second measure.

### The Problem This Solves

With the standard variant, the Forecast series for all finalized
periods shows the *currently selected* scenario projected backward —
not what was actually forecast at the time. This makes it impossible
to answer: *"What did our forecast predict for period 3, and how
accurate was it compared to actuals?"*

The advanced variant shows the **front-month prediction** for each
finalized period: `Scenario[PeriodIndex] = VisualPeriod - 1` is the
scenario that was current when that period was still in the future.
Future periods continue to show the selected scenario's projection.
The Forecast line becomes a continuous record of predictive accuracy
on the left and forward projection on the right.

### Implementation

```dax
[ScenarioDispatch_WithRetro] =

VAR _ActiveScenarioKey  = SELECTEDVALUE( Dim_Scenario[ScenarioKey], "CURRENT" )
VAR _ActivePeriodIndex  = COALESCE( SELECTEDVALUE( Dim_Scenario[PeriodIndex] ),
                                     MONTH(TODAY()) - 2 )
VAR _CutoffPeriod       = IF( _ActiveScenarioKey = "CURRENT",
                               MONTH(TODAY()) - 2, _ActivePeriodIndex )
VAR _SeriesLabel        = SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )
VAR _VisualPeriod       = SELECTEDVALUE( Dim_Date[MonthNumber] )

RETURN
SWITCH(
    _SeriesLabel,

    "Plan",
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
        Dim_Scenario[ScenarioType] = "PLAN"
    ),

    -- ── Forecast: split finalized vs future ──────────────────────────
    "Forecast",
    COALESCE(
        IF(
            _VisualPeriod <= _CutoffPeriod,

            -- Finalized periods: show front-month scenario prediction.
            -- PeriodIndex = _VisualPeriod - 1 is the scenario that was
            -- "current" when this period was still in the future.
            CALCULATE(
                [Amount],
                REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
                Dim_Scenario[PeriodIndex] = _VisualPeriod - 1,
                Dim_Date[MonthNumber]     = _VisualPeriod
            ),

            -- Future periods: show currently selected scenario.
            -- Both PeriodLabel AND ScenarioKey must be removed to prevent
            -- cross-filter contamination from the date axis context.
            CALCULATE(
                [Amount],
                REMOVEFILTERS( Fact_PeriodData[PeriodLabel] ),
                REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
                Fact_PeriodData[ScenarioKey] = _ActiveScenarioKey
            )
        ),
        0
        -- Forecast uses COALESCE( ..., 0 ), not BLANK().
        -- The forecast line must remain continuous even at zero.
        -- Actual uses BLANK() to suppress future periods entirely.
    ),

    -- ── Actual: confirmed values, future suppressed ───────────────────
    "Actual",
    IF(
        _VisualPeriod <= _CutoffPeriod,
        CALCULATE(
            [Amount],
            REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
            Dim_Scenario[PeriodIndex] = _VisualPeriod
        )
    ),

    BLANK()
)
```

### Why the Dual REMOVEFILTERS in the Future Branch

```dax
REMOVEFILTERS( Fact_PeriodData[PeriodLabel] ),
REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
```

Removing only `[ScenarioKey]` leaves a residual period filter
propagated from the date axis. This restricts the scenario lookup
to a single period context, returning incorrect values or BLANK.
Removing `[PeriodLabel]` first clears the cross-filter; the explicit
`ScenarioKey` predicate then operates across the full period range
before the visual re-applies the period constraint at render time.

This two-column removal is the minimal correct solution to a
non-obvious filter context interaction that surfaces specifically
when the axis configuration creates cross-column period pressure
against the scenario dimension.

### Visual Interpretation

```
Period:    P01  P02  P03  P04  P05  P06  P07  P08  P09  P10  P11  P12
           ──── ──── ──── ──── ──── ──── ──── ──── ──── ──── ──── ────
Actual:     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ─    ─    ─
Forecast: retro retro retro retro retro retro retro retro retro fwd  fwd  fwd
Plan:       ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓

retro = front-month prediction for that period (historical accuracy)
fwd   = selected scenario forward projection
```

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| All series identical | Missing `REMOVEFILTERS` | Add column-scoped removal to each branch |
| Forecast flat across finalized periods | Single-column `REMOVEFILTERS` in future branch | Add `REMOVEFILTERS( Fact_PeriodData[PeriodLabel] )` |
| Retro branch shows wrong values | Off-by-one on `PeriodIndex - 1` | Confirm inclusive boundary convention in scenario design |
| Forecast line breaks at cutoff | Missing `COALESCE` | Wrap future branch: `COALESCE( IF(...), 0 )` |
| Plan always blank | `ScenarioType` string mismatch | Inspect `DISTINCT( Dim_Scenario[ScenarioType] )` |
| Legend wrong order | Sort column not set | Set `SeriesLabel` sort column to `SortOrder` |

---

## Reuse Checklist

- [ ] Replace `Fact_PeriodData[ScenarioKey]` and `[PeriodLabel]` with your fact table columns
- [ ] Replace `Dim_Scenario[PeriodIndex]` and `[ScenarioType]` with your scenario attributes
- [ ] Replace `Dim_LegendSeries[SeriesLabel]` with your legend dimension
- [ ] Replace `Dim_Date[MonthNumber]` with your period column
- [ ] Replace `[Amount]` with your base measure
- [ ] Choose: standard variant (simpler) or advanced variant (retrospective accuracy layer)
