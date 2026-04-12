# Data Model — WTI Basis Dashboard

**Schema:** Kimball star schema  
**Source:** Four CSVs exported by `demo/data/pipeline.py`  
**Power BI import:** Get Data → Text/CSV → each file separately  

---

## Schema Overview

```
                    Dim_Date
                    DateKey (PK)
                    Date
                    Year
                    MonthNumber
                    MonthNameShort
                    PeriodLabel
                         │
              ┌──────────┼──────────────────────┐
              │          │                       │
              ▼          ▼                       ▼
   Fact_BasisPanel   Fact_TermStructure    Dim_DisruptionEvents
   date (FK) ────►   date (FK) ────────►  event_date
   tenor_key (FK)─►       │               (inactive relationship
   tau_bin (FK) ──►        │                used for annotation)
                     Dim_Tenor
                     tenor_key (PK)
                     tenor_label
                     sort_order
              │
              ▼
         Dim_TauBin
         tau_bin (PK)
         sort_order
         tau_days_avg
              │
              ▼
   Fact_VarianceByTau
   tau_bin (FK)
```

---

## Table 1 — Fact_BasisPanel

**Source:** `basis_panel.csv`  
**Grain:** One row per trading day  
**Loaded as:** Import mode

| Column | Type | Description |
|--------|------|-------------|
| `date` | Date | Trading date — primary join key |
| `spot_price` | Decimal | WTI spot price $/BBL (Cushing, OK) |
| `front_price` | Decimal | Front-month futures settlement $/BBL |
| `second_price` | Decimal | Second-month futures settlement $/BBL |
| `third_price` | Decimal | Third-month futures settlement $/BBL |
| `basis_front` | Decimal | `front_price - spot_price` |
| `basis_second` | Decimal | `second_price - spot_price` |
| `basis_third` | Decimal | `third_price - spot_price` |
| `term_spread` | Decimal | `second_price - front_price` |
| `tau` | Decimal | Days to front-month expiry / 252 (years) |
| `tau_days` | Integer | Calendar days to front-month expiry |
| `tau_bin` | Text | Categorical: "0-7d", "8-14d", ..., "61-90d" |
| `basis_var_21d` | Decimal | 21-day rolling variance of `basis_front` |
| `basis_vol_21d` | Decimal | 21-day rolling std dev of `basis_front` |
| `contango_flag` | Integer | 1 = contango, 0 = backwardation |
| `structure` | Text | "Contango" or "Backwardation" |
| `year` | Integer | Calendar year |
| `month_number` | Integer | 1–12 |
| `month_name_short` | Text | "Jan", "Feb", etc. |
| `period_label` | Text | "2024-03" format |

**Power Query transformations required:**

```powerquery
let
    Source = Csv.Document(...),
    #"Promoted Headers" = Table.PromoteHeaders(Source),

    // Type each column explicitly — CSV imports as text by default
    #"Changed Types" = Table.TransformColumnTypes(
        #"Promoted Headers",
        {
            {"date",          type date},
            {"spot_price",    type number},
            {"front_price",   type number},
            {"second_price",  type number},
            {"third_price",   type number},
            {"basis_front",   type number},
            {"basis_second",  type number},
            {"basis_third",   type number},
            {"term_spread",   type number},
            {"tau",           type number},
            {"tau_days",      Int64.Type},
            {"tau_bin",       type text},
            {"basis_var_21d", type number},
            {"basis_vol_21d", type number},
            {"contango_flag", Int64.Type},
            {"structure",     type text},
            {"year",          Int64.Type},
            {"month_number",  Int64.Type}
        }
    ),

    // Remove weekends and any rows with null spot price
    #"Removed Nulls" = Table.SelectRows(
        #"Changed Types",
        each [spot_price] <> null and [spot_price] > 0
    )
in
    #"Removed Nulls"
```

---

## Table 2 — Fact_TermStructure

**Source:** `term_structure.csv`  
**Grain:** One row per trading day × tenor (3 rows per day)  
**Loaded as:** Import mode

| Column | Type | Description |
|--------|------|-------------|
| `date` | Date | Trading date |
| `tenor` | Text | "front", "second", "third" |
| `tenor_label` | Text | "Front Month", "Second Month", "Third Month" |
| `sort_order` | Integer | 1, 2, 3 — for legend ordering |
| `spot_price` | Decimal | WTI spot on this date |
| `futures_price` | Decimal | Futures settlement for this tenor |
| `basis` | Decimal | `futures_price - spot_price` |
| `period_label` | Text | "2024-03" format |

**Power Query transformation:** Same type-casting pattern as Fact_BasisPanel.
Add a `tenor_key` column matching `Dim_Tenor[tenor_key]` if not already present:

```powerquery
#"Added TenorKey" = Table.AddColumn(
    #"Changed Types",
    "tenor_key",
    each [tenor],
    type text
)
```

---

## Table 3 — Fact_VarianceByTau

**Source:** `variance_by_tau.csv`  
**Grain:** One row per tau bin  
**Loaded as:** Import mode  
**Purpose:** Drives the ORBIT Theorem 1 validation chart — basis variance
stratified by time-to-expiry bin

| Column | Type | Description |
|--------|------|-------------|
| `tau_bin` | Text | "0-7d", "8-14d", etc. — join key to Dim_TauBin |
| `basis_variance` | Decimal | Empirical variance of basis_front within bin |
| `basis_std_dev` | Decimal | Standard deviation |
| `basis_mean` | Decimal | Mean basis within bin |
| `observation_count` | Integer | Number of daily observations in bin |
| `avg_tau_days` | Decimal | Average days-to-expiry within bin |
| `sort_order` | Integer | Ascending by avg_tau_days |

---

## Table 4 — Dim_DisruptionEvents

**Source:** `disruption_events.csv`  
**Grain:** One row per annotated event  
**Loaded as:** Import mode  
**Purpose:** Annotation reference layer for time series visuals

| Column | Type | Description |
|--------|------|-------------|
| `event_date` | Date | Date of the event |
| `event_label` | Text | Short label for chart annotation |
| `event_type` | Text | "GEOPOLITICAL", "MARKET_STRUCTURE", "POLICY" |
| `description` | Text | Full description for tooltip |
| `year` | Integer | Calendar year |
| `sort_order` | Integer | Chronological sequence |

---

## Table 5 — Dim_Date

**Source:** Calculated table in Power BI (DAX) — do not import from CSV  
**Purpose:** Time intelligence, standard date hierarchy

```dax
Dim_Date =
VAR _MinDate = MIN( Fact_BasisPanel[date] )
VAR _MaxDate = MAX( Fact_BasisPanel[date] )
RETURN
ADDCOLUMNS(
    CALENDAR( _MinDate, _MaxDate ),
    "DateKey",         INT( FORMAT( [Date], "YYYYMMDD" ) ),
    "Year",            YEAR( [Date] ),
    "QuarterNumber",   ROUNDUP( MONTH( [Date] ) / 3, 0 ),
    "QuarterLabel",    "Q" & ROUNDUP( MONTH( [Date] ) / 3, 0 ),
    "MonthNumber",     MONTH( [Date] ),
    "MonthNameShort",  FORMAT( [Date], "MMM", "en-US" ),
    "MonthNameLong",   FORMAT( [Date], "MMMM", "en-US" ),
    "PeriodLabel",     FORMAT( [Date], "YYYY-MM" ),
    "DayOfWeek",       WEEKDAY( [Date], 2 ),
    "IsWeekend",       IF( WEEKDAY( [Date], 2 ) >= 6, 1, 0 )
)
```

Mark as date table: Table tools → Mark as date table → Date column = `[Date]`

---

## Table 6 — Dim_Tenor

**Source:** Calculated table (DAX) — static, no CSV needed

```dax
Dim_Tenor =
DATATABLE(
    "tenor_key",    STRING,
    "tenor_label",  STRING,
    "sort_order",   INTEGER,
    {
        { "front",  "Front Month",  1 },
        { "second", "Second Month", 2 },
        { "third",  "Third Month",  3 }
    }
)
```

---

## Table 7 — Dim_TauBin

**Source:** Calculated table (DAX) — static, defines tau bin ordering

```dax
Dim_TauBin =
DATATABLE(
    "tau_bin",      STRING,
    "sort_order",   INTEGER,
    "tau_days_min", INTEGER,
    "tau_days_max", INTEGER,
    {
        { "0-7d",   1,  0,  7  },
        { "8-14d",  2,  8,  14 },
        { "15-21d", 3,  15, 21 },
        { "22-30d", 4,  22, 30 },
        { "31-45d", 5,  31, 45 },
        { "46-60d", 6,  46, 60 },
        { "61-90d", 7,  61, 90 }
    }
)
```

Set `tau_bin` sort column to `sort_order` in Data View.

---

## Relationships

Configure in Model View. All are many-to-one, single cross-filter direction
unless noted.

| From (Many) | To (One) | Column | Active | Notes |
|---|---|---|---|---|
| `Fact_BasisPanel[date]` | `Dim_Date[Date]` | date | ✓ | Primary time filter |
| `Fact_BasisPanel[tau_bin]` | `Dim_TauBin[tau_bin]` | tau_bin | ✓ | Tau stratification |
| `Fact_TermStructure[date]` | `Dim_Date[Date]` | date | ✓ | Shares date dimension |
| `Fact_TermStructure[tenor_key]` | `Dim_Tenor[tenor_key]` | tenor_key | ✓ | Tenor slicer |
| `Fact_VarianceByTau[tau_bin]` | `Dim_TauBin[tau_bin]` | tau_bin | ✓ | Variance chart axis |
| `Dim_Date[Date]` | `Dim_DisruptionEvents[event_date]` | date | ✗ | Inactive — annotation only |

The `Dim_DisruptionEvents` relationship is inactive because events are not
filtered facts — they are reference annotations. Activate in measures using
`USERELATIONSHIP` when building the annotation layer.

---

## Sort Columns — Set These or Charts Will Misbehave

| Table | Column to Sort | Sort By Column |
|---|---|---|
| `Dim_Date` | `MonthNameShort` | `MonthNumber` |
| `Dim_Date` | `QuarterLabel` | `QuarterNumber` |
| `Dim_TauBin` | `tau_bin` | `sort_order` |
| `Dim_Tenor` | `tenor_label` | `sort_order` |

---

## Performance Notes

**This model will be fast.** The full daily panel from 2020 to present
is approximately 1,500 rows. Even with the long-format term structure
table (3× rows = ~4,500), total row count is well under 10,000. Import
mode is appropriate — no DirectQuery or composite model needed.

For the portfolio context, this is worth noting: the patterns documented
in this repo were developed against enterprise datasets with millions of
rows. The optimization techniques (aggregations, composite models, DAX
variable caching) documented in the pattern files apply at that scale.
This demo uses a deliberately small public dataset to keep the focus on
the DAX architecture and visual design rather than data volume.
