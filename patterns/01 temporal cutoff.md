# Pattern 01 — Temporal Series Cutoff

**Category:** Time Intelligence · Scenario Management  
**Applies to:** Power BI Desktop / Service  
**Complexity:** Advanced  

---

## Problem Statement

In rolling forecast architectures, each reporting period produces a
new scenario that supersedes the prior one. A visual displaying
historical actuals alongside forward-looking forecasts must enforce
a **temporal cutoff**: display realized values only through the most
recently closed period, and suppress those columns for periods not
yet finalized.

The cutoff boundary is not static — it advances one period each month
as new actuals are locked. Hard-coding the boundary month is a
maintenance liability. The pattern below derives the cutoff
dynamically from the active scenario and a configurable reporting lag.

---

## Conceptual Model

A rolling forecast scenario encodes its maturity in its identifier.
The `PeriodIndex` attribute of `Dim_Scenario` captures how many
periods of actuals the scenario contains:

| ScenarioKey   | ScenarioAlias | PeriodIndex | Interpretation              |
|---------------|---------------|-------------|-----------------------------|
| `FCST_P01`    | `1+11`        | 1           | 1 actual period, 11 forecast|
| `FCST_P06`    | `6+6`         | 6           | 6 actual periods, 6 forecast|
| `FCST_P09`    | `9+3`         | 9           | 9 actual periods, 3 forecast|

`PeriodIndex` is the authoritative cutoff boundary for each scenario.

---

## Implementation

### Variable Block — Scenario Resolution

Embed this variable block at the top of any measure requiring
temporal cutoff logic:

```dax
-- ── Scenario resolution ──────────────────────────────────────────────
VAR _ActiveScenarioKey =
    SELECTEDVALUE( Dim_Scenario[ScenarioKey] )

VAR _ActivePeriodIndex =
    SELECTEDVALUE( Dim_Scenario[PeriodIndex], 0 )

VAR _ReportingLag = 2
-- Reporting lag: number of periods after close before actuals are
-- confirmed and published. Adjust to your organization's close cycle.

VAR _CutoffPeriod =
    IF(
        _ActiveScenarioKey = "CURRENT",
        MONTH( TODAY() ) - _ReportingLag,
        _ActivePeriodIndex
    )
-- When the slicer is set to "Current" (auto-resolve to today),
-- derive the cutoff from the system date minus the reporting lag.
-- Otherwise, use the PeriodIndex from the selected scenario directly.
```

---

### The Cutoff Display Measure

```dax
[Amount_WithCutoff] =

-- ── Scenario resolution (paste variable block here) ──────────────────
VAR _ActiveScenarioKey  = SELECTEDVALUE( Dim_Scenario[ScenarioKey] )
VAR _ActivePeriodIndex  = SELECTEDVALUE( Dim_Scenario[PeriodIndex], 0 )
VAR _ReportingLag       = 2
VAR _CutoffPeriod       = IF( _ActiveScenarioKey = "CURRENT",
                              MONTH( TODAY() ) - _ReportingLag,
                              _ActivePeriodIndex )

-- ── Series resolution ────────────────────────────────────────────────
VAR _SeriesLabel =
    SELECTEDVALUE( Dim_LegendSeries[SeriesLabel] )

VAR _VisualPeriod =
    SELECTEDVALUE( Dim_Date[MonthNumber] )

-- ── Dispatch ─────────────────────────────────────────────────────────
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
        -- Returns BLANK() for periods beyond the cutoff.
        -- BLANK() suppresses bar segments and data labels automatically.
    )
)
```

---

## Cutoff Behavior Illustrated

```
Configuration:  ReportingLag = 2,  ActiveScenario = FCST_P09 (PeriodIndex = 9)
CutoffPeriod  = 9

Period:    P01  P02  P03  P04  P05  P06  P07  P08  P09  P10  P11  P12
           ──── ──── ──── ──── ──── ──── ──── ──── ──── ──── ──── ────
Actual:     ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ─    ─    ─
Forecast:   ─    ─    ─    ─    ─    ─    ─    ─    ─    ✓    ✓    ✓
Plan:       ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓    ✓
```

Actuals are rendered through period P09. Forecast begins at P10.
Plan spans all periods as a full-year reference baseline.

---

## Design Decisions

**Why `BLANK()` rather than `0` for suppressed periods?**

Returning `BLANK()` instructs Power BI to omit the data point
entirely — no bar segment, no axis tick contribution, no data label.
Returning `0` renders a zero-height bar that still occupies axis
space and triggers conditional formatting. `BLANK()` produces a
cleaner visual and is semantically correct: the value does not exist,
it has not yet been measured.

**Why `REMOVEFILTERS` scoped to the foreign key column?**

`REMOVEFILTERS( Fact_PeriodData[ScenarioKey] )` removes the scenario
slicer's influence on that specific column while preserving all other
active filters — entity, account, date range, region. Using
`REMOVEFILTERS( Fact_PeriodData )` or `ALL( Fact_PeriodData )` would
strip the entire filter context including user-set slicers. The
column-scoped form is strictly safer and more predictable.

**Why `PeriodIndex - 1` for the Forecast branch?**

The forecast scenario with `PeriodIndex = N` contains N periods of
actuals and begins forecasting at period N+1. To show the forecast
that starts where actuals end, reference the scenario whose
`PeriodIndex = CutoffPeriod - 1` — that scenario's forward periods
align to the post-cutoff months.

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| Actuals render for all periods | `_CutoffPeriod` resolves to 0 | Verify `Dim_Scenario[PeriodIndex]` is populated and the relationship to `Fact_PeriodData` is active |
| Forecast and Actual overlap at boundary | Off-by-one in `PeriodIndex - 1` | Confirm whether your scenario convention is inclusive or exclusive at the boundary |
| Plan branch returns BLANK | `ScenarioType` value mismatch | Inspect distinct values of `Dim_Scenario[ScenarioType]` in Data View |
| Cutoff does not advance with calendar | `_ReportingLag` constant too high | Lower lag or verify TODAY() is returning the expected system date |
| CURRENT scenario branch never triggers | Slicer not populated with "CURRENT" row | Add a `CURRENT` sentinel row to `Dim_Scenario` with `PeriodIndex = 0` |

---

## Reuse Checklist

- [ ] Replace `Fact_PeriodData` with your fact table name
- [ ] Replace `Dim_Scenario[ScenarioKey]` and `[PeriodIndex]` with your scenario dimension columns
- [ ] Replace `Dim_LegendSeries[SeriesLabel]` with your legend dimension column
- [ ] Replace `Dim_Date[MonthNumber]` with your date dimension period column
- [ ] Replace `[Amount]` with your base measure
- [ ] Set `_ReportingLag` to match your organization's financial close schedule
- [ ] Confirm `Dim_Scenario[ScenarioType]` values match the `"PLAN"` string in the Plan branch
