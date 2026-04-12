# Pattern 03 — Hybrid Axis Construction via UNION

**Category:** Data Modeling · Visual Configuration  
**Applies to:** Power BI Desktop / Service  
**Complexity:** Intermediate–Advanced  

---

## Problem Statement

Enterprise FP&A charts require a **hybrid period axis**: individual
calendar periods (P01 through P12) alongside an aggregate total
period (FY) displayed as a terminal column on the same axis.

Power BI's native date hierarchy is rigid — it cannot include a
synthetic aggregate node. A static lookup table cannot filter the
fact table dynamically. The `UNION`-based axis pattern resolves both
constraints by combining a dynamically derived period set with a
static aggregate row, connected to the model through a shared
sort key.

---

## The Target Axis

```
Visual x-axis:
│ P01 │ P02 │ P03 │ P04 │ P05 │ P06 │ P07 │ P08 │ P09 │ P10 │ P11 │ P12 │ FY │
  ↑                                                                           ↑
  Derived from Dim_Date (dynamic, filtered by data)             Static row
                                                                (SortOrder = 13)
```

All period columns filter the fact table through the `Dim_Date`
relationship. The FY column carries no date filter — the measure
detects the aggregate context and removes period constraints.

---

## Component 1 — Dim_Date (Marked Date Table)

```dax
Dim_Date =
VAR _MinDate = MIN( Fact_PeriodData[DateKey] )
VAR _MaxDate = MAX( Fact_PeriodData[DateKey] )
RETURN
ADDCOLUMNS(
    CALENDAR( _MinDate, _MaxDate ),
    "DateKey",         INT( FORMAT( [Date], "YYYYMMDD" ) ),
    "Year",            YEAR( [Date] ),
    "FiscalYear",      IF( MONTH([Date]) >= 10,
                           YEAR([Date]) + 1,
                           YEAR([Date]) ),   -- adjust for your fiscal year start
    "QuarterNumber",   ROUNDUP( MONTH([Date]) / 3, 0 ),
    "MonthNumber",     MONTH( [Date] ),
    "PeriodLabel",     "P" & FORMAT( MONTH([Date]), "00" ),
    "MonthNameShort",  FORMAT( [Date], "MMM" ),
    "MonthNameLong",   FORMAT( [Date], "MMMM", "en-US" )
)
```

Mark this table as a Date Table in Power BI (Table tools →
Mark as date table, using the `Date` column). This activates
time intelligence functions across all measures.

---

## Component 2 — Dim_AxisConfig (Hybrid Axis Table)

```dax
Dim_AxisConfig =
UNION(
    -- Dynamic portion: calendar periods derived from Dim_Date
    SUMMARIZE(
        Dim_Date,
        Dim_Date[PeriodLabel],     -- "P01", "P02", ... "P12"
        Dim_Date[MonthNumber]      -- 1, 2, ... 12  (sort key)
    ),

    -- Static portion: fiscal year aggregate column
    ROW(
        "PeriodLabel",  "FY",
        "MonthNumber",   13         -- sort position: after P12
    )
)
```

**Why UNION over DATATABLE?**  
`DATATABLE` requires statically defined values at model creation time.
`SUMMARIZE` derives period labels from the actual data range —
if the fact table contains P01 through P09, only those nine periods
appear. No manual updates are needed as new periods are loaded.

---

## Component 3 — Relationship Configuration

Establish an inactive relationship between `Dim_AxisConfig` and
`Dim_Date` on the shared sort key:

```
Dim_AxisConfig[MonthNumber]  ─────(inactive)─────  Dim_Date[MonthNumber]
                                                            │
                                                    (active relationship)
                                                            │
                                                   Fact_PeriodData[DateKey]
```

The relationship is marked inactive because `Dim_AxisConfig`
is consumed by `SELECTEDVALUE` inside measures, not by automatic
filter propagation. Activate it explicitly within measures using
`USERELATIONSHIP` where period-level filtering is required.

---

## Component 4 — Sort Configuration

In the Data View, select `Dim_AxisConfig[PeriodLabel]` and set
**Sort by column** to `Dim_AxisConfig[MonthNumber]`.

Without this, Power BI sorts period labels alphabetically:
P01, P02, P03, P04, P05, P06, P07, P08, P09, P10, P11, P12
becomes P01, P02, P03, P04, P05, P06, P07, P08, P09, P10, P11, P12
which accidentally sorts correctly — but FY would sort between P01
and P02 alphabetically. The numeric sort key ensures FY appears last.

---

## Component 5 — The FY-Aware Display Measure

```dax
[Amount_PeriodDisplay] =

VAR _AxisLabel =
    SELECTEDVALUE( Dim_AxisConfig[PeriodLabel] )

VAR _PeriodNumber =
    SELECTEDVALUE( Dim_AxisConfig[MonthNumber] )

RETURN
IF(
    _AxisLabel = "FY",

    -- FY branch: remove all period filters, aggregate full year
    CALCULATE(
        [Amount],
        REMOVEFILTERS( Dim_Date[MonthNumber] ),
        REMOVEFILTERS( Dim_Date[PeriodLabel] )
    ),

    -- Period branch: filter to the specific calendar period
    CALCULATE(
        [Amount],
        USERELATIONSHIP( Dim_AxisConfig[MonthNumber], Dim_Date[MonthNumber] ),
        Dim_Date[MonthNumber] = _PeriodNumber
    )
)
```

The FY column produces a full-year aggregate regardless of any period
slicer selections. Individual period columns filter to their respective
month through the activated relationship.

---

## Extending to a Matrix Column Header

For matrix visuals requiring variance columns alongside period and FY
columns, extend the axis table with additional static rows:

```dax
Dim_MatrixColumns =
DATATABLE(
    "ColumnLabel",  STRING,
    "SortOrder",    INTEGER,
    "ColumnType",   STRING,
    "Annotation",   STRING,
    {
        { "P01",            1,  "PERIOD",   BLANK()                              },
        { "P02",            2,  "PERIOD",   BLANK()                              },
        { "P03",            3,  "PERIOD",   BLANK()                              },
        { "P04",            4,  "PERIOD",   BLANK()                              },
        { "P05",            5,  "PERIOD",   BLANK()                              },
        { "P06",            6,  "PERIOD",   BLANK()                              },
        { "P07",            7,  "PERIOD",   BLANK()                              },
        { "P08",            8,  "PERIOD",   BLANK()                              },
        { "P09",            9,  "PERIOD",   BLANK()                              },
        { "P10",            10, "PERIOD",   BLANK()                              },
        { "P11",            11, "PERIOD",   BLANK()                              },
        { "P12",            12, "PERIOD",   BLANK()                              },
        { "FY Total",       13, "TOTAL",    "Full-year aggregate, current scenario" },
        { "Prior Total",    14, "TOTAL",    "Full-year aggregate, prior scenario"   },
        { "Δ vs Prior",     15, "VARIANCE", "Absolute variance: Current vs Prior"   },
        { "Plan Total",     16, "TOTAL",    "Full-year aggregate, annual plan"       },
        { "Δ vs Plan",      17, "VARIANCE", "Absolute variance: Current vs Plan"     },
        { "Δ% vs Plan",     18, "VARIANCE", "Percentage variance: Current vs Plan"   }
    }
)
```

Each `ColumnType` value drives branching in the matrix display measure:

```dax
[MatrixDisplay] =
VAR _Col     = SELECTEDVALUE( Dim_MatrixColumns[ColumnLabel] )
VAR _ColType = SELECTEDVALUE( Dim_MatrixColumns[ColumnType]  )
VAR _Sort    = SELECTEDVALUE( Dim_MatrixColumns[SortOrder]   )

RETURN
SWITCH(
    _ColType,

    "PERIOD",
    CALCULATE( [Amount], Dim_Date[MonthNumber] = _Sort ),

    "TOTAL",
    SWITCH(
        _Col,
        "FY Total",
            CALCULATE( [Amount],
                REMOVEFILTERS( Dim_Date[MonthNumber] ) ),
        "Prior Total",
            CALCULATE( [Amount],
                REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
                Dim_Scenario[PeriodIndex] = [_ActivePeriodIndex] - 1 ),
        "Plan Total",
            CALCULATE( [Amount],
                REMOVEFILTERS( Fact_PeriodData[ScenarioKey] ),
                Dim_Scenario[ScenarioType] = "PLAN" )
    ),

    "VARIANCE",
    SWITCH(
        _Col,
        "Δ vs Prior",
            [MatrixDisplay_FYTotal] - [MatrixDisplay_PriorTotal],
        "Δ vs Plan",
            [MatrixDisplay_FYTotal] - [MatrixDisplay_PlanTotal],
        "Δ% vs Plan",
            DIVIDE(
                [MatrixDisplay_FYTotal] - [MatrixDisplay_PlanTotal],
                ABS( [MatrixDisplay_PlanTotal] ),
                BLANK()
            )
    )
)
```

---

## Design Principles

**SortOrder = 13 for FY.**  
Any integer greater than 12 positions FY after P12. Using 13 is
conventional and self-documenting. The value has no semantic
connection to any date — it is purely a display ordering key.

**UNION is the correct operator, not DATATABLE.**  
`DATATABLE` embeds values at model creation time. `UNION` with
`SUMMARIZE` derives the period set from the loaded data dynamically.
As new fiscal years are loaded, new period labels appear without
schema changes.

**Inactive relationship, activated in measure.**  
`Dim_AxisConfig` does not need to propagate filters automatically —
it provides labels and sort keys consumed by `SELECTEDVALUE` inside
measures. The inactive relationship prevents unintended cross-filter
effects while allowing explicit activation via `USERELATIONSHIP`
in specific measures.

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| Periods render in alphabetical order | Sort by column not configured | Set `PeriodLabel` sort column to `MonthNumber` in Data View |
| FY column always blank | Measure missing FY branch | Confirm `IF( _AxisLabel = "FY", ... )` evaluates correctly |
| FY shows single-period value instead of full year | `REMOVEFILTERS` on wrong column | Verify both `MonthNumber` and `PeriodLabel` are removed in FY branch |
| Duplicate period rows in axis | `SUMMARIZE` returning multiple years | Add year filter to `SUMMARIZE` or filter in the measure |
| `MonthNameShort` renders in local language | `FORMAT` locale-dependent | Use `FORMAT( [Date], "MMM", "en-US" )` with explicit locale |

---

## Reuse Checklist

- [ ] Replace `Fact_PeriodData` with your fact table name
- [ ] Replace `Dim_Date[MonthNumber]` and `[PeriodLabel]` with your date dimension columns
- [ ] Confirm `Dim_Date` is marked as the official date table in model settings
- [ ] Set sort column: `Dim_AxisConfig[PeriodLabel]` sorted by `Dim_AxisConfig[MonthNumber]`
- [ ] Adjust `FiscalYear` logic in `Dim_Date` to match your organization's fiscal calendar
- [ ] Replace `[Amount]` with your base measure throughout
- [ ] Add `Dim_MatrixColumns` rows for any additional variance or comparison columns
