# Pattern 04 — Dynamic Row-Level Formatting for Financial Statement Matrix

**Category:** Data Modeling · Display Architecture · Financial Reporting  
**Applies to:** Power BI Desktop / Service  
**Complexity:** Advanced  

---

## Problem Statement

A financial statement matrix in Power BI presents a fundamental
formatting constraint: the platform applies one format per column,
not per row. A Lease Operating Statement, Income Statement, or
Cash Flow Statement has 40+ line items where every row has different
display requirements:

- Price rows: per-unit currency, 2 decimal places, positive
- Volume rows: integer, no currency symbol, thousands separator
- Revenue rows: currency millions, zero decimals, parenthetical negative
- Cost rows: currency millions, zero decimals, positive sign
- Unit cost rows: per-unit currency, 2 decimals, parenthetical negative
- Percentage rows: one decimal percent

Power BI provides no native mechanism for row-level format variation
in a matrix visual. The standard workaround — separate measures per
row type — produces an unmaintainable model that breaks whenever
the statement structure changes.

This pattern implements a **mapping-table-driven display architecture**
that resolves the correct format for each row at query time, driven
entirely by metadata in the model rather than hard-coded measure logic.

---

## The Two-Layer Architecture

The central design principle is strict separation of concerns:

```
Layer 1: Computation
─────────────────────────────────────────────────────
[_BaseAggregation]

Reads AccountKey from Dim_LineFormat.
Routes to the correct atomic source measure.
Returns a raw numeric value.
No formatting. No scaling. No sign logic.


Layer 2: Display
─────────────────────────────────────────────────────
[StatementDisplay]

Reads DisplayType, ScaleFactor, NegateSign from Dim_LineFormat.
Applies scale divisor to raw value.
Applies sign inversion where source convention differs from display.
Applies FORMAT() string based on DisplayType.
Returns a formatted string.
No computation. No aggregation. No CALCULATE.
```

Each layer is independently testable and independently maintainable.
A change to how a line item is calculated touches only Layer 1.
A change to how it is displayed touches only `Dim_LineFormat`.
Neither change requires modifying the other layer.

---

## Component 1 — Dim_LineFormat (The Formatting Engine)

`Dim_LineFormat` is the single source of truth for how every row
in the statement displays. It contains one row per financial
statement line item:

| Column | Purpose |
|--------|---------|
| `AccountKey` | Foreign key joining to `Dim_Account` and routing Layer 1 |
| `LineLabel` | Display name rendered in the matrix row header |
| `SortOrder` | Sequence position within the statement |
| `SectionHeader` | Grouping label (PRICES, PRODUCTION, REVENUE, EXPENSE...) |
| `DisplayType` | Format category driving the FORMAT() string selection |
| `ScaleFactor` | Divisor applied before formatting (1, 1000, 1000000) |
| `NegateSign` | Boolean: multiply by -1 before display |

The `NegateSign` column exists to resolve a specific class of problem:
source systems (ERP, planning platforms) often store values with sign
conventions that differ from financial statement display conventions.
Expenses may be stored as positive values but displayed as negative
in a P&L context, or vice versa. Rather than encoding this inversion
in each atomic measure, `NegateSign` externalizes it to the mapping
table where it is visible, auditable, and changeable without touching
measure logic.

---

## Component 2 — DisplayType Categories

`DisplayType` maps each line item to a format string family:

| DisplayType | Format behavior | Example output |
|---|---|---|
| `CURRENCY_0D_MM` | Currency, zero decimals, millions scale | `$18,033` / `($18,033)` |
| `CURRENCY_2D_PER_UNIT` | Currency, 2 decimals, no scaling | `$40.04` / `($11.17)` |
| `INTEGER_VOLUME` | Integer, no currency symbol | `41,090` / `(1)` |
| `PCT_1D` | Percentage, one decimal | `12.3%` / `(4.5%)` |
| `BLANK_HEADER` | Section header row — no value rendered | *(blank)* |

Parenthetical negatives `($18,033)` are the standard financial
statement convention for negative values. This is enforced at the
`FORMAT()` string level, not through conditional logic — the
negative pattern in the format string handles all negative values
automatically regardless of how they arrive from the computation layer.

---

## Component 3 — Layer 1 Routing Logic

Layer 1 reads `AccountKey` from the row context and dispatches to
the correct atomic source measure:

```
SWITCH( _AccountKey,
  "PRC_OIL"  → [OilPriceBBL],
  "VOL_OIL"  → [NetOilVolume],
  "REV_TOT"  → [TotalRevenue],
  "EXP_LIFT" → [LiftingCostPerBOE],
  "CF_INT"   → [InternalCashFlow],
  ...
  BLANK()
)
```

Each atomic measure is a simple aggregation — `SUM`, `DIVIDE`,
`CALCULATE` with filters. They contain no display logic. Adding a
new line item to the statement requires adding one row to
`Dim_LineFormat` and one branch to this routing SWITCH. The display
layer requires no changes.

---

## Component 4 — Layer 2 Display Logic (Conceptual)

The display layer executes a three-step transformation:

```
Step 1: Read raw value from [_BaseAggregation]

Step 2: Transform
   scaled_value = raw_value / ScaleFactor
   IF NegateSign = 1: scaled_value = scaled_value * -1

Step 3: Format
   SWITCH( DisplayType,
     "CURRENCY_0D_MM"      → FORMAT( scaled_value, currency_0d_pattern ),
     "CURRENCY_2D_PER_UNIT"→ FORMAT( scaled_value, currency_2d_pattern ),
     "INTEGER_VOLUME"      → FORMAT( scaled_value, integer_pattern ),
     "PCT_1D"              → FORMAT( scaled_value, percent_pattern ),
     "BLANK_HEADER"        → BLANK()
   )
```

The format string patterns are not published here — they encode
specific sign and parenthesis conventions that represent production
implementation detail. The architecture is the contribution; the
format strings are implementation.

---

## The String Return Constraint

`FORMAT()` returns a `STRING` in DAX. This has three implications
that must be managed explicitly:

**Grand totals are suppressed.** A string-valued measure cannot be
aggregated by Power BI's built-in totals row. The matrix grand total
must be disabled in visual formatting settings, with an explicit total
row added to `Dim_LineFormat` if a summary row is required.

**Sorting is lexicographic.** String fields sort alphabetically.
Row ordering in the matrix is controlled entirely by
`Dim_LineFormat[SortOrder]` set as the sort column for `LineLabel`.
Never rely on value sorting for a formatted financial statement.

**Parallel numeric measure is required.** Conditional formatting
thresholds, export to Excel with numeric values, and tooltips all
require numeric context. Maintain a parallel `[StatementValue]`
measure that returns the scaled raw number without `FORMAT()` and
use it exclusively for non-display purposes.

---

## Conditional Formatting for Statement Sections

The `SectionHeader` column in `Dim_LineFormat` enables banded
section formatting via Power BI's conditional formatting rules:

```
Background color rule:
  IF Dim_LineFormat[SectionHeader] = "PRICES"      → teal
  IF Dim_LineFormat[SectionHeader] = "PRODUCTION"  → light gray
  IF Dim_LineFormat[SectionHeader] = "REVENUE"     → white
  IF Dim_LineFormat[SectionHeader] = "EXPENSE"     → light gray
  IF Dim_LineFormat[SectionHeader] = "CASH_FLOW"   → teal

Font weight rule:
  IF Dim_LineFormat[RowWeight] = "BOLD"   → bold
  IF Dim_LineFormat[RowWeight] = "NORMAL" → regular
```

This reproduces the visual structure of a standard financial
statement — section headers distinguished from detail rows,
subtotals bolded — without requiring separate visual elements
or DAX logic. The entire formatting specification lives in
`Dim_LineFormat`.

---

## Why This Architecture Matters

The alternative approach — one measure per display format, selected
manually per row — produces a model with 40+ measures, no single
source of truth for format specifications, and no maintainable path
for statement restructuring. When the client adds a new line item,
the analyst creates a new measure. When the format changes, every
affected measure is edited individually.

The mapping-table architecture inverts this: the model has two
measures regardless of statement complexity. Statement structure
is a data problem, not a code problem. Restructuring the statement
means editing rows in `Dim_LineFormat`, not editing DAX.

---

## Reuse Checklist

- [ ] Design `Dim_LineFormat` schema before writing any measures
- [ ] Identify all `DisplayType` categories needed for your statement
- [ ] Audit source system sign conventions against display conventions — document `NegateSign` decisions
- [ ] Build and validate all atomic source measures independently before connecting Layer 1
- [ ] Disable matrix grand total row in visual settings
- [ ] Create parallel numeric `[StatementValue]` measure for conditional formatting
- [ ] Set `LineLabel` sort column to `SortOrder` in Data View
