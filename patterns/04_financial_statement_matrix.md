# Pattern 04 — Dynamic Row-Level Formatting for Financial Statement Matrix

**Category:** Data Modeling · Display Formatting · Financial Reporting  
**Applies to:** Power BI Desktop / Service  
**Complexity:** Advanced  

---

## Problem Statement

A financial statement matrix (Income Statement, Lease Operating
Statement, Cash Flow Statement) presents a fundamental formatting
challenge in Power BI: every row has different display requirements.

- Price rows: `$40.04 /BBL` — currency, 2 decimals, per-unit
- Volume rows: `41.09` — integer, no symbol, thousands not applicable
- Revenue rows: `($43)` — currency, zero decimals, negative in parentheses
- Cost rows: `$18,033` — currency, zero decimals, positive sign
- Margin rows: `($11.17) /BOE` — currency, 2 decimals, per-unit, parenthetical negative

Power BI's native conditional formatting applies one format per
column, not per row. A matrix with 40+ line items across 17 columns
requires row-aware format logic that Power BI does not provide natively.

This pattern implements a **mapping-table-driven display measure**
that reads formatting metadata per row and applies the correct
scale, symbol, decimal precision, and sign convention dynamically
within a single DAX measure.

---

## The Core Insight

Separate the **computation logic** from the **display logic** into
two distinct measure layers:

```
Layer 1: [_BaseAggregation]
         Computes the raw numeric value for each row
         using standard CALCULATE and filter context.
         No formatting. Returns a plain number.
                │
                ▼
Layer 2: [DisplayMeasure]
         Reads Dim_LineFormat[DisplayType] for the current row.
         Applies scale, symbol, decimal precision, sign convention.
         Returns a formatted string via FORMAT().
```

The display layer never computes — it only formats. The computation
layer never formats — it only computes. This separation makes both
layers independently maintainable.

---

## Component 1 — Dim_LineFormat (Mapping Table)

This table is the engine of the pattern. Each row maps a financial
statement line item to its display specification:

```dax
Dim_LineFormat =
DATATABLE(
    "AccountKey",    STRING,     -- joins to Dim_Account[AccountKey]
    "LineLabel",     STRING,     -- display name shown in matrix rows
    "DisplayType",   STRING,     -- format category (see legend below)
    "ScaleFactor",   DOUBLE,     -- numeric divisor before formatting
    "SortOrder",     INTEGER,    -- row sequence in the statement
    "SectionHeader", STRING,     -- section grouping (PRICES, PRODUCTION, etc.)
    "NegateSign",    INTEGER,    -- 1 = multiply by -1 before display, 0 = as-is
    {
        -- PRICES section
        { "PRC_OIL",  "Oil Price / BBL",       "CURRENCY_2D_PER_UNIT",  1,      100, "PRICES",     0 },
        { "PRC_GAS",  "Gas Price / MCF",        "CURRENCY_2D_PER_UNIT",  1,      110, "PRICES",     0 },
        -- PRODUCTION section
        { "VOL_OIL",  "Net Oil — MBLS",         "INTEGER_VOLUME",        1000,   200, "PRODUCTION", 0 },
        { "VOL_GAS",  "Net Gas — MMCF",         "INTEGER_VOLUME",        1000,   210, "PRODUCTION", 0 },
        -- REVENUE section
        { "REV_OIL",  "Oil Sales",              "CURRENCY_0D_MM",        1000000,300, "REVENUE",    0 },
        { "REV_TOT",  "Total Revenue",          "CURRENCY_0D_MM",        1000000,360, "REVENUE",    0 },
        -- EXPENSE section
        { "EXP_PO",   "PO Tracked Costs",       "CURRENCY_0D_MM",        1000000,400, "EXPENSE",    0 },
        { "EXP_LIFT", "Lifting Cost $/BOE",     "CURRENCY_2D_PER_UNIT",  1,      460, "EXPENSE",    0 },
        { "EXP_TOT",  "Total Expense",          "CURRENCY_0D_MM",        1000000,494, "EXPENSE",    0 },
        -- CASH FLOW section
        { "CF_INT",   "Internal Cash Flow",     "CURRENCY_0D_MM",        1000000,600, "CASH_FLOW",  0 },
        { "CF_EXT",   "External Cash Flow",     "CURRENCY_0D_MM",        1000000,610, "CASH_FLOW",  1 }
        -- Add rows for all line items in the statement
    }
)
```

**DisplayType legend:**

| DisplayType | Format | Example |
|---|---|---|
| `CURRENCY_0D_MM` | `$#,0;($#,0)` | `$18,033` / `($18,033)` |
| `CURRENCY_2D_PER_UNIT` | `$#,0.00;($#,0.00)` | `$40.04` / `($11.17)` |
| `INTEGER_VOLUME` | `#,0;(#,0)` | `41,090` / `(1)` |
| `PCT_1D` | `#,0.0%;(#,0.0%)` | `12.3%` / `(4.5%)` |
| `BLANK_HEADER` | *(no value displayed)* | section header row |

---

## Component 2 — Layer 1: Base Aggregation Measure

```dax
[_BaseAggregation] =
VAR _AccountKey =
    SELECTEDVALUE( Dim_LineFormat[AccountKey] )

-- Route to the correct source measure based on AccountKey.
-- Each account maps to a pre-built atomic measure.
RETURN
SWITCH(
    _AccountKey,
    "PRC_OIL",  [OilPriceBBL],
    "PRC_GAS",  [GasPriceMCF],
    "VOL_OIL",  [NetOilVolume],
    "VOL_GAS",  [NetGasVolume],
    "REV_OIL",  [OilSalesRevenue],
    "REV_TOT",  [TotalRevenue],
    "EXP_PO",   [POTrackedCosts],
    "EXP_LIFT", [LiftingCostPerBOE],
    "EXP_TOT",  [TotalExpense],
    "CF_INT",   [InternalCashFlow],
    "CF_EXT",   [ExternalCashFlow],
    BLANK()
)
```

Each atomic measure (`[OilPriceBBL]`, `[TotalRevenue]`, etc.) is a
simple `CALCULATE( SUM(...), ... )` or division. They contain no
formatting logic whatsoever.

---

## Component 3 — Layer 2: Display Measure

```dax
[StatementDisplay] =

VAR _RawValue =
    [_BaseAggregation]

VAR _DisplayType =
    SELECTEDVALUE( Dim_LineFormat[DisplayType], "CURRENCY_0D_MM" )

VAR _ScaleFactor =
    SELECTEDVALUE( Dim_LineFormat[ScaleFactor], 1 )

VAR _NegateSign =
    SELECTEDVALUE( Dim_LineFormat[NegateSign], 0 )

-- Apply scale and optional sign inversion
VAR _ScaledValue =
    IF(
        _NegateSign = 1,
        DIVIDE( _RawValue * -1, _ScaleFactor, BLANK() ),
        DIVIDE( _RawValue,      _ScaleFactor, BLANK() )
    )

-- Apply format string based on DisplayType
VAR _FormattedValue =
    SWITCH(
        _DisplayType,

        "CURRENCY_0D_MM",
        IF(
            ISBLANK( _ScaledValue ), BLANK(),
            FORMAT( _ScaledValue, "$#,0;($#,0)" )
        ),

        "CURRENCY_2D_PER_UNIT",
        IF(
            ISBLANK( _ScaledValue ), BLANK(),
            FORMAT( _ScaledValue, "$#,0.00;($#,0.00)" )
        ),

        "INTEGER_VOLUME",
        IF(
            ISBLANK( _ScaledValue ), BLANK(),
            FORMAT( _ScaledValue, "#,0;(#,0)" )
        ),

        "PCT_1D",
        IF(
            ISBLANK( _ScaledValue ), BLANK(),
            FORMAT( _ScaledValue, "#,0.0%;(#,0.0%)" )
        ),

        "BLANK_HEADER",
        BLANK(),

        -- Default fallback
        IF(
            ISBLANK( _ScaledValue ), BLANK(),
            FORMAT( _ScaledValue, "$#,0;($#,0)" )
        )
    )

RETURN _FormattedValue
```

---

## Component 4 — Visual Configuration

Place the matrix visual with this field configuration:

| Field well | Source |
|---|---|
| Rows | `Dim_LineFormat[LineLabel]` (sorted by `SortOrder`) |
| Columns | `Dim_MatrixColumns[ColumnLabel]` (Pattern 03) |
| Values | `[StatementDisplay]` |

Use **conditional formatting** on the Values field to apply background
color by `Dim_LineFormat[SectionHeader]` — this creates the banded
section headers (PRICES in one color, PRODUCTION in another, etc.)
that match a standard financial statement layout.

For bold formatting on section total rows, add a `RowWeight` column
to `Dim_LineFormat` (`"BOLD"` / `"NORMAL"`) and apply conditional
font weight formatting.

---

## Why FORMAT() Returns a String

`FORMAT()` returns a `STRING` in DAX, which means the Values field
in the matrix will be treated as text, not numeric. This has
implications:

- **Sorting:** Text sorting is alphabetical, not numeric. For the
  matrix column values this is acceptable since columns are sorted
  by `SortOrder` in `Dim_MatrixColumns`, not by value.
- **Aggregation:** String values cannot be summed. This is intentional
  — the display measure is not meant to be summed across rows. Each
  row is independently computed by `[_BaseAggregation]`.
- **Grand totals:** Power BI's built-in grand total row will show
  BLANK for string measures. Suppress the grand total in visual
  formatting settings, or create an explicit total row in
  `Dim_LineFormat` with its own `AccountKey` routing.

If numeric behavior is required alongside formatted display (for
tooltips, conditional formatting thresholds, or export), maintain
a parallel numeric measure `[StatementValue]` that returns the
scaled raw number without `FORMAT()`, and use it exclusively for
non-display purposes.

---

## Extending to Variance Columns

For variance columns (`Δ vs Plan`, `Δ vs Prior`, `Δ%`), add a
secondary display type path in the SWITCH:

```dax
-- In [StatementDisplay], after the primary _FormattedValue logic:
VAR _ColumnLabel =
    SELECTEDVALUE( Dim_MatrixColumns[ColumnLabel] )

VAR _IsVarianceColumn =
    _ColumnLabel IN { "Δ vs Plan", "Δ vs Prior" }

VAR _IsPctVarianceColumn =
    _ColumnLabel = "Δ% vs Plan"

VAR _VarianceValue =
    IF(
        _IsVarianceColumn,
        [StatementDisplay_Total] - [StatementDisplay_PlanTotal],
        IF(
            _IsPctVarianceColumn,
            DIVIDE(
                [StatementDisplay_Total] - [StatementDisplay_PlanTotal],
                ABS( [StatementDisplay_PlanTotal] ),
                BLANK()
            ),
            _ScaledValue
        )
    )
```

Apply the same `DisplayType`-driven `FORMAT()` logic to
`_VarianceValue`. Variance columns inherit the same decimal
precision and unit convention as the base metric — a price row
variance shows as `$1.23 /BBL`, a volume variance shows as `1,234`.

---

## The Design Pattern in One Sentence

**Store formatting metadata in the model, not in the measure.**
`Dim_LineFormat` is the single source of truth for how every row
displays. Adding a new line item requires one new row in the mapping
table and one new `SWITCH` branch in `[_BaseAggregation]` — the
display measure itself never changes.

---

## Common Issues

| Symptom | Probable Cause | Resolution |
|---------|---------------|------------|
| All rows show same format | `Dim_LineFormat[DisplayType]` not filtering correctly | Verify `AccountKey` relationship and `SELECTEDVALUE` path |
| Grand total row shows BLANK | `FORMAT()` returns string, cannot aggregate | Suppress grand total in visual settings |
| Negative values not in parentheses | Format string missing negative pattern | Ensure `;($#,0)` clause present after positive pattern |
| Variance column shows base value | Column routing logic missing | Add `_ColumnLabel` branch before final `RETURN` |
| Sorting wrong within sections | `SortOrder` not set as sort column | Set `LineLabel` sort column to `SortOrder` in Data View |

---

## Reuse Checklist

- [ ] Build `Dim_LineFormat` with one row per financial statement line item
- [ ] Define `DisplayType` values matching your statement's formatting requirements
- [ ] Set `ScaleFactor` per row: `1` for per-unit, `1000` for thousands, `1000000` for millions
- [ ] Set `NegateSign = 1` for rows where the source system sign convention inverts display convention
- [ ] Build one atomic measure per `AccountKey` in `[_BaseAggregation]`
- [ ] Set `LineLabel` sort column to `SortOrder` in Data View
- [ ] Suppress grand total row in matrix visual formatting settings
- [ ] Create parallel numeric measure `[StatementValue]` for conditional formatting thresholds
