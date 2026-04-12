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

Add additional series rows (e.g., `"Budget"`, `"Prior Year"`) as
reporting requirements expand. Each new row requires a corresponding
branch in the dispatch measure.

---

## Component 2 — The Resolution Variable Block

Embed this block in every scenario-aware measure. It derives the
active scenario state from slicer context before any dispatch logic:

```dax
-- ── Scenario resolution ──────────────────────────────────────────────
VAR _ActiveScenarioKey =
    SELECTEDVALUE( Dim_Scenario[ScenarioKey], "CURRENT" )

VAR _ActivePeriodIndex =
    COALESCE(
        SELECTEDVALUE( Dim_Scenario[PeriodIndex] ),
        MONTH( TODAY() ) - 2    -- fallback: derive from system date
    )

VAR _CutoffPeriod =
    IF(
        _ActiveScenarioKey = "CURRENT",
        MONTH( TODAY() ) - 2,
        _ActivePeriodIndex
    )

-- ── Series resolution ────────────────────────────────────────────────
VAR _SeriesLabel =
    SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )

VAR _VisualPeriod =
    SELECTEDVALUE( Dim_Date[MonthNumber] )
```

---

## Component 3 — The SWITCH Dispatch Measure

```dax
[ScenarioDispatch_Amount] =

-- [paste resolution variable block here]
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

    -- ── Plan ─────────────────────────────────────────────────────────
    -- Full-year plan. Slicer filter removed; explicit PLAN predicate applied.
    -- Renders across all periods as a reference baseline.
    "Plan",
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
        Dim_Scenario[ScenarioType] = "PLAN"
    ),

    -- ── Forecast ─────────────────────────────────────────────────────
    -- Front-month forecast scenario relative to the active cutoff.
    -- References the scenario whose PeriodIndex = CutoffPeriod - 1,
    -- which is the scenario that starts forecasting at the next period.
    "Forecast",
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
        Dim_Scenario[PeriodIndex] = _CutoffPeriod - 1
    ),

    -- ── Actual ───────────────────────────────────────────────────────
    -- Confirmed values for finalized periods only.
    -- Returns BLANK() for periods beyond the cutoff — suppresses
    -- the bar segment and data label without rendering zero.
    "Actual",
    IF(
        _VisualPeriod <= _CutoffPeriod,
        CALCULATE(
            [Amount],
            REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
            Dim_Scenario[PeriodIndex] = _VisualPeriod
        )
    ),

    -- Default: BLANK() for any unmapped series label
    BLANK()
)
```

---

## Filter Context Flow Diagram

```
User sets slicer: ScenarioKey = "FCST_P09"
                         │
                         ▼
          Filter propagates to Fact_PeriodData[ScenarioKey]
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
        Plan          Forecast       Actual
        branch         branch        branch
           │             │             │
    REMOVEFILTERS   REMOVEFILTERS  REMOVEFILTERS
    on [ScenarioKey] on [ScenarioKey] on [ScenarioKey]
           │             │             │
    Re-apply:       Re-apply:      Re-apply:
    ScenarioType    PeriodIndex    PeriodIndex
    = "PLAN"        = 8 (9-1)      = VisualPeriod
                                   IF VisualPeriod <= 9
```

The slicer filter is intercepted and replaced by an explicit predicate
in each branch. No branch inherits the raw slicer value.

---

## Extending to Multiple KPIs

Once the resolution block and SWITCH structure are established, adding
a KPI is a single substitution of the base measure:

```dax
[ScenarioDispatch_Volume] =
-- [same resolution block]
SWITCH( _SeriesLabel,
    "Plan",     CALCULATE( [Volume],    REMOVEFILTERS(...), Dim_Scenario[ScenarioType] = "PLAN" ),
    "Forecast", CALCULATE( [Volume],    REMOVEFILTERS(...), Dim_Scenario[PeriodIndex] = _CutoffPeriod - 1 ),
    "Actual",   IF( _VisualPeriod <= _CutoffPeriod,
                    CALCULATE( [Volume], REMOVEFILTERS(...), Dim_Scenario[PeriodIndex] = _VisualPeriod ) )
)

[ScenarioDispatch_UnitCost] =
-- [same resolution block]
SWITCH( _SeriesLabel,
    "Plan",     CALCULATE( [UnitCost],  REMOVEFILTERS(...), Dim_Scenario[ScenarioType] = "PLAN" ),
    "Forecast", CALCULATE( [UnitCost],  REMOVEFILTERS(...), Dim_Scenario[PeriodIndex] = _CutoffPeriod - 1 ),
    "Actual",   IF( _VisualPeriod <= _CutoffPeriod,
                    CALCULATE( [UnitCost], REMOVEFILTERS(...), Dim_Scenario[PeriodIndex] = _VisualPeriod ) )
)
```

All measures are structurally identical. Only the base measure changes.
Extract the resolution block into a shared calculation group if your
model supports it.

---

## Visual Field Configuration

| Field well        | Source                              |
|-------------------|-------------------------------------|
| X-axis            | `Dim_AxisConfig[PeriodLabel]`       |
| Y-axis (series 1) | `[ScenarioDispatch_Amount]`         |
| Y-axis (series 2) | `[ScenarioDispatch_Volume]`         |
| Legend            | `Dim_LegendSeries[SeriesLabel]`     |
| Sort legend by    | `Dim_LegendSeries[SortOrder]`       |
| Slicer            | `Dim_Scenario[ScenarioAlias]`       |

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| All series identical despite REMOVEFILTERS | Relationship cross-filter direction overrides column removal | Set `Dim_Scenario` → `Fact_PeriodData` as single-direction only |
| Plan series always blank | `ScenarioType` value mismatch | Inspect `DISTINCT( Dim_Scenario[ScenarioType] )` in DAX query |
| Forecast and Actual overlap at boundary | `PeriodIndex - 1` off-by-one | Confirm inclusive/exclusive boundary convention in scenario design |
| Legend renders in wrong order | Sort by column not configured | Set `SeriesLabel` sort column to `SortOrder` in Data View |
| Slicer set to ALL returns BLANK on all branches | `SELECTEDVALUE` returns BLANK when multiple values active | Wrap with `COALESCE( SELECTEDVALUE(...), "CURRENT" )` |

---

## Reuse Checklist

- [ ] Replace `Fact_PeriodData[ScenarioKey]` with your fact table's scenario foreign key
- [ ] Replace `Dim_Scenario[PeriodIndex]` and `[ScenarioType]` with your scenario attributes
- [ ] Replace `Dim_LegendSeries[SeriesLabel]` with your legend dimension
- [ ] Replace `Dim_Date[MonthNumber]` with your period number column
- [ ] Replace `[Amount]` with your base measure
- [ ] Verify `"PLAN"` string matches the exact value in `Dim_Scenario[ScenarioType]`
- [ ] Add additional `SWITCH` branches for Budget, Prior Year, or other series as required
