# powerbi-dax-patterns

[![Power BI](https://img.shields.io/badge/Power%20BI-Desktop%20%7C%20Service-F2C811?logo=powerbi&logoColor=black)](https://powerbi.microsoft.com)
[![DAX](https://img.shields.io/badge/Language-DAX-blueviolet)](https://learn.microsoft.com/en-us/dax/)
[![Modeling](https://img.shields.io/badge/Methodology-Kimball%20Dimensional-0f3460)](https://www.kimballgroup.com)
[![Domain](https://img.shields.io/badge/Domain-FP%26A%20%7C%20Energy%20%7C%20Finance-success)](https://github.com/stevetab03)

**Author:** Liyuan Zhang  
**Status:** Active — patterns extracted from production enterprise deployments

---

## Overview

This repository documents a set of advanced DAX patterns for
**enterprise FP&A reporting** in Power BI. Each pattern addresses a
class of problems that standard documentation does not cover at
production depth: cross-scenario filter context manipulation, dynamic
temporal cutoff logic, hybrid axis construction, and row-level
financial statement formatting.

The patterns are grounded in Kimball dimensional modeling principles
and are designed for environments where Power BI connects directly to
enterprise planning platforms (OneStream, SAP BPC, Hyperion, Anaplan)
via native connectors or structured ETL pipelines.

---

## Reference Data Model

All patterns reference a canonical dimensional schema. Substitute
your own table and column names using the reuse checklist in each
document.

```
Fact_PeriodData
    │   Grain: one row per (Entity × Account × Date × Scenario)
    │   Key measures: [Amount], [Volume], [UnitCost]
    │
    ├── Dim_Scenario          ScenarioKey, ScenarioAlias, ScenarioType,
    │                         PeriodIndex, SortOrder
    │
    ├── Dim_Account           AccountKey, AccountName, LineFormat,
    │                         HierarchyL1..L9, SortOrder, DisplayType
    │
    ├── Dim_Entity            EntityKey, EntityName, Region,
    │                         BusinessUnit, ConsolidationLevel
    │
    ├── Dim_Date              DateKey (marked date table),
    │                         Year, QuarterNumber, MonthNumber,
    │                         MonthNameShort, MonthNameLong, FiscalPeriod
    │
    ├── Dim_LineFormat        AccountKey, LineLabel, DisplayType,
    │   (Pattern 04)          ScaleFactor, SortOrder, SectionHeader, NegateSign
    │
    ├── Dim_AxisConfig        PeriodLabel, MonthNumber (SortOrder)
    │   (Pattern 03)          Hybrid month + FY axis configuration
    │
    └── Dim_LegendSeries      SeriesKey, SeriesLabel, SortOrder
        (Pattern 02)          Plan / Forecast / Actual series definition
```

---

## Patterns

| # | Document | Core Problem | Primary Technique |
|---|----------|-------------|-------------------|
| [01](patterns/01_temporal_cutoff.md) | Temporal Series Cutoff | Display Actuals only through the last finalized period; suppress future months | `REMOVEFILTERS` · lag constant · conditional `BLANK()` |
| [02](patterns/02_cross_scenario_switch.md) | Cross-Scenario Aggregation | Show Plan, Forecast, and Actual as independent series despite an active scenario slicer. Advanced variant adds retrospective forecast accuracy layer. | `SWITCH` · `REMOVEFILTERS` · `Dim_LegendSeries` · dual-column removal |
| [03](patterns/03_hybrid_axis_union.md) | Hybrid Axis Construction | Combine dynamic calendar periods with a static fiscal year total on the same chart axis | `UNION` · `SUMMARIZE` · sort-by-column |
| [04](patterns/04_financial_statement_matrix.md) | Financial Statement Matrix | Row-level formatting in a matrix visual where every row has different scale, precision, sign convention, and unit | `Dim_LineFormat` mapping table · `FORMAT()` · two-layer measure architecture |

---

## Design Principles

**Filter context over visual workarounds.**  
Every pattern manipulates filter context explicitly via `CALCULATE`
and `REMOVEFILTERS` rather than relying on visual-layer configuration.
This makes behavior predictable, testable, and independent of report
layout changes.

**Kimball schema alignment.**  
Helper tables (`Dim_AxisConfig`, `Dim_LegendSeries`, `Dim_LineFormat`)
are first-class model citizens with defined relationships — not
disconnected lookup objects. Relationship cardinality and filter
propagation direction are documented explicitly.

**Separation of computation and display.**  
Pattern 04 formalizes a two-layer measure architecture: `[_BaseAggregation]`
computes raw values with no formatting; `[StatementDisplay]` formats
with no computation. Each layer is independently maintainable and
testable.

**Composability.**  
Pattern 01 (temporal cutoff) is consumed by Pattern 02 (scenario
SWITCH) as an embedded variable block. Pattern 03 (hybrid axis)
drives the visual that renders Pattern 02's measures. Pattern 04
(financial statement) uses Pattern 03's `Dim_MatrixColumns` as its
column definition. The four patterns are designed to be used together.

---

## Repository Structure
```
powerbi-dax-patterns/
│
├── README.md
├── LICENSE
├── .gitignore
│
├── patterns/
│   ├── 01_temporal_cutoff.md
│   ├── 02_cross_scenario_switch.md
│   ├── 03_hybrid_axis_union.md
│   └── 04_financial_statement_matrix.md
│
└── demo/
    │
    ├── README.md
    │
    ├── data/
    │   ├── pipeline.py
    │   ├── requirements.txt
    │   └── sample/
    │       ├── basis_panel_sample.csv
    │       └── disruption_events.csv
    │
    ├── WTI_Basis_Dashboard.pbip
    ├── WTI_Basis_Dashboard.SemanticModel/
    ├── WTI_Basis_Dashboard.Report/
    │
    ├── powerbi/
    │   ├── data_model.md
    │   └── measures.md
    │
    └── screenshots/
        ├── 01_basis_time_series.png
        ├── 02_term_structure.png
        ├── 03_tau_variance.png
        └── 04_summary_matrix.png
```

---

## Related Work

- **[ORBIT](https://github.com/stevetab03/ORBIT)** — the oil futures-spot
  basis convergence model whose Python calibration outputs are exported
  to CSV and visualized in Power BI using these patterns.

- **[SVMA](https://github.com/stevetab03/SVMA)** — the predecessor stochastic
  volatility framework, also using Power BI as the visualization layer.

---

## Contact

**LinkedIn:** https://www.linkedin.com/in/hlzhang/  
**GitHub:** https://github.com/stevetab03
