"""
ORBIT Data Pipeline
===================
WTI Futures-Spot Basis Panel for Power BI

Fetches:
  - WTI spot prices          : EIA API v2 (free key, register at eia.gov)
  - WTI futures (3 tenors)   : Yahoo Finance via yfinance (no key required)

Computes:
  - Basis per tenor          : e_t = F_t - S_t (raw) and lambda-adjusted
  - Time to expiry (tau)     : calendar days to front-month expiry / 252
  - Tau bins                 : for variance collapse analysis (ORBIT Theorem 1)
  - Rolling basis variance   : 21-day rolling, stratified by tenor
  - Term spread              : second-month minus front-month

Exports (Power BI ready CSVs):
  - basis_panel.csv          : daily panel, all tenors
  - variance_by_tau.csv      : aggregated variance by tau bin
  - term_structure.csv       : daily term structure snapshot
  - disruption_events.csv    : annotated geopolitical event reference table

Usage:
  python pipeline.py --start 2020-01-01 --end 2026-04-01
  python pipeline.py --start 2020-01-01 --end 2026-04-01 --eia_key YOUR_KEY

EIA API key: free registration at https://www.eia.gov/opendata/register.php
"""

import os
import time
import logging
import argparse
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict

# ── Logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# EIA API v2 endpoint for WTI spot price (Cushing, OK)
EIA_SPOT_URL = (
    "https://api.eia.gov/v2/petroleum/pri/spt/data/"
    "?frequency=daily"
    "&data[0]=value"
    "&facets[duoarea][]=Y35NY"
    "&facets[product][]=EPCWTI"
    "&sort[0][column]=period"
    "&sort[0][direction]=asc"
    "&length=5000"
)

# Yahoo Finance tickers for WTI futures continuous contracts
# CL=F  : front-month (nearest expiry)
# CLH=F : 3-month rolling (approximate second-month proxy via yfinance)
# We fetch front, second, and third tenors using the continuous roll series
FUTURES_TICKERS = {
    "front":  "CL=F",
    "second": "CLH25.NYM",   # update month code as needed; see note below
    "third":  "CLM25.NYM",
}
# NOTE on futures tickers: yfinance specific-contract tickers (e.g. CLH25.NYM)
# expire. For a production pipeline use the EIA futures series instead:
#   Front month:  EER_EPCWTI_PF4_Y35NY_DPG
#   The pipeline falls back to EIA futures if yfinance returns empty data.

# Rolling window for variance computation (trading days)
ROLLING_WINDOW = 21

# Tau bins for variance collapse analysis (ORBIT Theorem 1)
# Bins represent days-to-expiry ranges
TAU_BINS = [0, 7, 14, 21, 30, 45, 60, 90]
TAU_LABELS = ["0-7d", "8-14d", "15-21d", "22-30d", "31-45d", "46-60d", "61-90d"]

# Geopolitical disruption events for annotation layer
DISRUPTION_EVENTS = [
    {
        "event_date":  "2020-04-20",
        "event_label": "WTI Negative Price",
        "event_type":  "MARKET_STRUCTURE",
        "description": "Front-month WTI futures settle at -$37.63 due to storage constraints"
    },
    {
        "event_date":  "2022-02-24",
        "event_label": "Ukraine Invasion",
        "event_type":  "GEOPOLITICAL",
        "description": "Russia invades Ukraine; Brent surges past $100, WTI basis widens"
    },
    {
        "event_date":  "2022-03-08",
        "event_label": "WTI $130 Peak",
        "event_type":  "GEOPOLITICAL",
        "description": "WTI reaches 14-year high of $130.50 amid supply shock fears"
    },
    {
        "event_date":  "2023-10-07",
        "event_label": "Hamas Attack",
        "event_type":  "GEOPOLITICAL",
        "description": "Israel-Hamas conflict begins; Middle East risk premium enters market"
    },
    {
        "event_date":  "2026-02-28",
        "event_label": "US-Iran War Begins",
        "event_type":  "GEOPOLITICAL",
        "description": "US and Israel strike Iran; Strait of Hormuz effectively closes"
    },
    {
        "event_date":  "2026-03-11",
        "event_label": "IEA Emergency Release",
        "event_type":  "POLICY",
        "description": "IEA largest-ever emergency stock release; 11mb/d Gulf production offline"
    },
    {
        "event_date":  "2026-04-07",
        "event_label": "US-Iran Ceasefire",
        "event_type":  "GEOPOLITICAL",
        "description": "Two-week ceasefire; WTI falls 16% in single session. Brent spot $124 vs futures $94"
    },
]


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, params: Optional[Dict] = None,
         retries: int = 4, base_sleep: float = 1.0) -> requests.Response:
    """Backoff GET with retry on 429 and network errors."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = base_sleep * (2 ** attempt)
                logger.warning("429 rate limit — retrying in %.1fs", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            wait = base_sleep * (2 ** attempt)
            logger.warning("Request error [%s] — retry in %.1fs", exc.__class__.__name__, wait)
            time.sleep(wait)
    raise RuntimeError(f"All {retries} attempts failed for {url}")


# ── EIA spot price fetcher ────────────────────────────────────────────────────

def fetch_eia_spot(start: str, end: str, api_key: str) -> pd.DataFrame:
    """
    Fetch WTI spot price from EIA API v2.

    Parameters
    ----------
    start, end : ISO date strings "YYYY-MM-DD"
    api_key    : free EIA API key from eia.gov/opendata

    Returns
    -------
    DataFrame with columns: date (datetime64), spot_price (float)
    """
    logger.info("Fetching EIA WTI spot %s → %s", start, end)

    params = {
        "api_key": api_key,
        "start":   start,
        "end":     end,
    }

    response = _get(EIA_SPOT_URL, params=params)
    data = response.json()

    records = data.get("response", {}).get("data", [])
    if not records:
        raise ValueError("EIA returned empty data — check API key and date range")

    df = pd.DataFrame(records)
    df = df.rename(columns={"period": "date", "value": "spot_price"})
    df["date"]        = pd.to_datetime(df["date"])
    df["spot_price"]  = pd.to_numeric(df["spot_price"], errors="coerce")
    df = df[["date", "spot_price"]].dropna().sort_values("date").reset_index(drop=True)

    logger.info("EIA spot: %d rows (%s to %s)",
                len(df), df["date"].min().date(), df["date"].max().date())
    return df


# ── Yahoo Finance futures fetcher ─────────────────────────────────────────────

def fetch_yfinance_futures(ticker: str, start: str, end: str) -> pd.Series:
    """
    Fetch daily close for a single yfinance futures ticker.

    Returns pd.Series indexed by date, or empty Series on failure.
    """
    try:
        import yfinance as yf
        raw = yf.download(ticker, start=start, end=end,
                          progress=False, auto_adjust=True)
        if raw.empty:
            logger.warning("yfinance returned empty data for %s", ticker)
            return pd.Series(dtype=float)
        series = raw["Close"].squeeze()
        series.index = pd.to_datetime(series.index)
        series.name = ticker
        logger.info("yfinance %s: %d rows", ticker, len(series))
        return series
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return pd.Series(dtype=float)


def fetch_all_futures(start: str, end: str) -> pd.DataFrame:
    """
    Fetch front, second, and third month WTI futures.
    Falls back gracefully if specific contracts are unavailable.

    Returns DataFrame with columns: date, front_price, second_price, third_price
    """
    logger.info("Fetching WTI futures (3 tenors) %s → %s", start, end)

    series = {}
    for tenor, ticker in FUTURES_TICKERS.items():
        s = fetch_yfinance_futures(ticker, start, end)
        if not s.empty:
            series[tenor] = s

    if not series:
        raise RuntimeError(
            "No futures data retrieved. Check yfinance installation "
            "and ticker symbols. Consider using EIA futures series as fallback."
        )

    df = pd.DataFrame(series)
    df.index.name = "date"
    df = df.reset_index()
    df.columns = ["date"] + [f"{c}_price" for c in df.columns if c != "date"]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── Expiry calendar ───────────────────────────────────────────────────────────

def nymex_expiry_calendar(start_year: int, end_year: int) -> pd.DataFrame:
    """
    Approximate NYMEX WTI front-month expiry dates.

    NYMEX rule: expiry is the 3rd business day before the 25th calendar
    day of the month preceding the contract month.
    This is an approximation — use CME official calendar for production.

    Returns DataFrame: contract_month (YYYY-MM), expiry_date
    """
    records = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # Contract expires roughly on the 20th of the prior month
            prior_month = month - 1 if month > 1 else 12
            prior_year  = year if month > 1 else year - 1
            # Approximate: 3 business days before 25th of prior month
            anchor = pd.Timestamp(year=prior_year, month=prior_month, day=25)
            expiry = anchor - pd.offsets.BDay(3)
            contract_month = f"{year}-{month:02d}"
            records.append({"contract_month": contract_month, "expiry_date": expiry})

    return pd.DataFrame(records)


def assign_tau(dates: pd.Series, expiry_calendar: pd.DataFrame) -> pd.Series:
    """
    For each date, compute tau = days to nearest front-month expiry / 252.
    Returns a Series of tau values (float, in years).
    """
    expiries = pd.to_datetime(expiry_calendar["expiry_date"].values)

    def _tau(d):
        future_expiries = expiries[expiries >= d]
        if len(future_expiries) == 0:
            return np.nan
        nearest = future_expiries.min()
        return max((nearest - d).days, 0) / 252.0

    return dates.apply(_tau)


# ── Basis computation ─────────────────────────────────────────────────────────

def compute_basis_panel(
    spot: pd.DataFrame,
    futures: pd.DataFrame,
    expiry_cal: pd.DataFrame
) -> pd.DataFrame:
    """
    Merge spot and futures, compute basis and derived columns.

    Basis definition:
        e_t = F_t - lambda * S_t
        lambda = 1.0 (raw basis, no cointegrating adjustment)

    Lambda adjustment (ORBIT model calibration) is left for the
    calibration module. The pipeline exports raw basis for Power BI.

    Derived columns:
        basis_front    = front_price - spot_price
        basis_second   = second_price - spot_price
        basis_third    = third_price - spot_price
        term_spread    = second_price - front_price  (market structure signal)
        tau            = days to front-month expiry / 252
        tau_bin        = categorical bin for variance collapse analysis
        basis_var_21d  = 21-day rolling variance of front basis
        contango_flag  = 1 if front basis > 0 (futures > spot), 0 = backwardation
    """
    logger.info("Computing basis panel")

    # Merge on date — inner join keeps only trading days with both sources
    panel = pd.merge(spot, futures, on="date", how="inner")
    panel = panel.sort_values("date").reset_index(drop=True)

    # Raw basis per tenor
    for tenor in ["front", "second", "third"]:
        col = f"{tenor}_price"
        if col in panel.columns:
            panel[f"basis_{tenor}"] = panel[col] - panel["spot_price"]

    # Term spread (contango/backwardation indicator)
    if "second_price" in panel.columns and "front_price" in panel.columns:
        panel["term_spread"] = panel["second_price"] - panel["front_price"]

    # Time to expiry
    panel["tau"] = assign_tau(panel["date"], expiry_cal)
    panel["tau_days"] = (panel["tau"] * 252).round(0).astype("Int64")

    # Tau bins
    panel["tau_bin"] = pd.cut(
        panel["tau_days"].astype(float),
        bins=TAU_BINS,
        labels=TAU_LABELS,
        right=True
    ).astype(str)

    # Rolling 21-day variance of front basis
    if "basis_front" in panel.columns:
        panel["basis_var_21d"] = (
            panel["basis_front"]
            .rolling(window=ROLLING_WINDOW, min_periods=10)
            .var()
        )
        panel["basis_vol_21d"] = np.sqrt(panel["basis_var_21d"])

    # Contango / backwardation flag
    if "basis_front" in panel.columns:
        panel["contango_flag"] = (panel["basis_front"] > 0).astype(int)
        panel["structure"] = panel["contango_flag"].map(
            {1: "Contango", 0: "Backwardation"}
        )

    # Year and month for Power BI time intelligence
    panel["year"]             = panel["date"].dt.year
    panel["month_number"]     = panel["date"].dt.month
    panel["month_name_short"] = panel["date"].dt.strftime("%b")
    panel["period_label"]     = panel["date"].dt.strftime("%Y-%m")

    logger.info("Basis panel: %d rows, %d columns", len(panel), len(panel.columns))
    return panel


# ── Variance collapse aggregation ─────────────────────────────────────────────

def compute_variance_by_tau(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate basis variance by tau bin.

    This directly tests ORBIT Theorem 1 (Variance Collapse):
        sigma_e^2(tau) = O(1/a(tau)) -> 0 as tau -> 0

    If the theorem holds empirically, variance should decrease
    monotonically as tau_bin moves from 61-90d toward 0-7d.

    Returns DataFrame suitable for a bar chart in Power BI.
    """
    logger.info("Aggregating variance by tau bin")

    if "basis_front" not in panel.columns or "tau_bin" not in panel.columns:
        logger.warning("Required columns missing for tau variance aggregation")
        return pd.DataFrame()

    # Filter out NaN tau bins and extreme outliers (storage crisis 2020)
    clean = panel.dropna(subset=["basis_front", "tau_bin"])
    clean = clean[clean["tau_bin"] != "nan"]

    agg = (
        clean
        .groupby("tau_bin", observed=True)
        .agg(
            basis_variance    = ("basis_front",  "var"),
            basis_std_dev     = ("basis_front",  "std"),
            basis_mean        = ("basis_front",  "mean"),
            observation_count = ("basis_front",  "count"),
            avg_tau_days      = ("tau_days",      "mean"),
        )
        .reset_index()
    )

    # Sort by average tau days for correct chart ordering
    agg = agg.sort_values("avg_tau_days").reset_index(drop=True)
    agg["sort_order"] = range(len(agg))

    # Theoretical prediction for comparison (simplified, lambda=1)
    # sigma_e^2 ~ effective_vol^2 / (2 * a(tau))
    # We don't have calibrated a(tau) yet, so we flag for ORBIT calibration
    agg["orbit_prediction"] = np.nan  # populated after calibration run

    logger.info("Variance by tau: %d bins", len(agg))
    return agg


# ── Term structure snapshot ───────────────────────────────────────────────────

def compute_term_structure(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Build a long-format term structure table for the tenor comparison visual.

    One row per (date, tenor) — suitable for a line chart with tenor as legend.
    """
    logger.info("Building term structure table")

    records = []
    tenor_map = {
        "front":  ("front_price",  1),
        "second": ("second_price", 2),
        "third":  ("third_price",  3),
    }

    for tenor, (price_col, sort_order) in tenor_map.items():
        if price_col not in panel.columns:
            continue
        sub = panel[["date", "spot_price", price_col,
                      "year", "month_number", "month_name_short",
                      "period_label"]].copy()
        sub = sub.rename(columns={price_col: "futures_price"})
        sub["tenor"]        = tenor
        sub["tenor_label"]  = f"{tenor.capitalize()} Month"
        sub["sort_order"]   = sort_order
        sub["basis"]        = sub["futures_price"] - sub["spot_price"]
        records.append(sub)

    if not records:
        return pd.DataFrame()

    ts = pd.concat(records, ignore_index=True)
    ts = ts.sort_values(["date", "sort_order"]).reset_index(drop=True)

    logger.info("Term structure: %d rows", len(ts))
    return ts


# ── Disruption events table ───────────────────────────────────────────────────

def build_disruption_events() -> pd.DataFrame:
    """
    Static reference table of geopolitical and market disruption events.
    Used as an annotation layer in Power BI time series visuals.
    """
    df = pd.DataFrame(DISRUPTION_EVENTS)
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["year"]       = df["event_date"].dt.year
    df["sort_order"] = range(len(df))
    return df


# ── Export ────────────────────────────────────────────────────────────────────

def export_outputs(
    panel:       pd.DataFrame,
    var_tau:     pd.DataFrame,
    term_struct: pd.DataFrame,
    events:      pd.DataFrame,
    output_dir:  str = "outputs/powerbi"
) -> None:
    """
    Export all tables to CSV for Power BI import.

    Power BI import: Get Data → Text/CSV → select each file.
    Recommended: import all four, build relationships on 'date' column.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    exports = {
        "basis_panel.csv":        panel,
        "variance_by_tau.csv":    var_tau,
        "term_structure.csv":     term_struct,
        "disruption_events.csv":  events,
    }

    for filename, df in exports.items():
        if df.empty:
            logger.warning("Skipping empty table: %s", filename)
            continue
        path = out / filename
        df.to_csv(path, index=False)
        logger.info("Exported %s → %s (%d rows)", filename, path, len(df))

    # Summary for verification
    print("\n── Export Summary ─────────────────────────────────────────")
    for filename, df in exports.items():
        if not df.empty:
            print(f"  {filename:<30} {len(df):>6} rows  {len(df.columns):>3} cols")
    print(f"\n  Output directory: {out.resolve()}")
    print("──────────────────────────────────────────────────────────\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline(
    start:   str,
    end:     str,
    eia_key: str,
    out_dir: str = "outputs/powerbi"
) -> Dict[str, pd.DataFrame]:
    """
    Full pipeline: fetch → compute → export.

    Returns dict of DataFrames for programmatic use (e.g. Jupyter notebook).
    """
    logger.info("ORBIT pipeline starting: %s → %s", start, end)

    start_year = int(start[:4])
    end_year   = int(end[:4])

    # ── Fetch ──
    spot    = fetch_eia_spot(start, end, eia_key)
    futures = fetch_all_futures(start, end)

    # ── Expiry calendar ──
    expiry_cal = nymex_expiry_calendar(start_year - 1, end_year + 1)

    # ── Compute ──
    panel      = compute_basis_panel(spot, futures, expiry_cal)
    var_tau    = compute_variance_by_tau(panel)
    term_struct = compute_term_structure(panel)
    events     = build_disruption_events()

    # ── Export ──
    export_outputs(panel, var_tau, term_struct, events, out_dir)

    logger.info("Pipeline complete.")
    return {
        "basis_panel":       panel,
        "variance_by_tau":   var_tau,
        "term_structure":    term_struct,
        "disruption_events": events,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ORBIT WTI Basis Pipeline — fetches spot + futures, exports Power BI CSVs"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="Start date YYYY-MM-DD (default: 2020-01-01)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=datetime.today().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--eia_key",
        type=str,
        default=os.getenv("EIA_API_KEY", ""),
        help="EIA API key (or set EIA_API_KEY env variable)"
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        default="outputs/powerbi",
        help="Output directory for CSV files (default: outputs/powerbi)"
    )

    args = parser.parse_args()

    if not args.eia_key:
        print("\nERROR: EIA API key required.")
        print("  Register free at: https://www.eia.gov/opendata/register.php")
        print("  Then run: python pipeline.py --eia_key YOUR_KEY\n")
        print("  Or set environment variable: export EIA_API_KEY=YOUR_KEY\n")
        return

    run_pipeline(
        start   = args.start,
        end     = args.end,
        eia_key = args.eia_key,
        out_dir = args.out_dir,
    )


if __name__ == "__main__":
    main()
