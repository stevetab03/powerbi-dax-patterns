"""
ORBIT Data Pipeline
===================
WTI Futures-Spot Basis Panel for Power BI

Fetches:
  - WTI spot prices          : EIA API v1 (free key, register at eia.gov)
  - WTI futures (3 tenors)   : Yahoo Finance via yfinance (no key required)

Computes:
  - Basis per tenor          : e_t = F_t - S_t
  - Time to expiry (tau)     : calendar days to front-month expiry / 252
  - Tau bins                 : for variance collapse analysis (ORBIT Theorem 1)
  - Rolling basis variance   : 21-day rolling, stratified by tenor
  - Term spread              : second-month minus front-month

Exports (Power BI ready CSVs):
  - basis_panel.csv
  - variance_by_tau.csv
  - term_structure.csv
  - disruption_events.csv

Usage:
  python pipeline.py --start 2020-01-01 --end 2026-04-11
  python pipeline.py --start 2020-01-01 --eia_key YOUR_KEY

EIA API key: free at https://www.eia.gov/opendata/register.php
"""

import os
import time
import logging
import argparse
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict

# ── Logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# EIA API v1 endpoint
EIA_V1_URL = "https://api.eia.gov/series/"

# EIA series ID: WTI Crude Oil spot price, Cushing OK, daily, $/BBL
EIA_SERIES_ID = "PET.RWTC.D"

# Yahoo Finance tickers
FUTURES_TICKERS = {
    "front":  "CL=F",
    "second": "CLM25.NYM",
    "third":  "CLQ25.NYM",
}

# Rolling window (trading days)
ROLLING_WINDOW = 21

# Tau bins for ORBIT Theorem 1 validation
TAU_BINS   = [0, 7, 14, 21, 30, 45, 60, 90]
TAU_LABELS = ["0-7d", "8-14d", "15-21d", "22-30d", "31-45d", "46-60d", "61-90d"]

# Geopolitical disruption events
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
        "description": "Russia invades Ukraine; WTI basis widens sharply"
    },
    {
        "event_date":  "2022-03-08",
        "event_label": "WTI $130 Peak",
        "event_type":  "GEOPOLITICAL",
        "description": "WTI reaches 14-year high of $130.50"
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
        "description": "Largest-ever IEA emergency stock release; 11mb/d Gulf production offline"
    },
    {
        "event_date":  "2026-04-07",
        "event_label": "US-Iran Ceasefire",
        "event_type":  "GEOPOLITICAL",
        "description": "Two-week ceasefire. WTI -16% in one session. Brent spot $124 vs futures $94"
    },
]


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, params: Optional[Dict] = None,
         retries: int = 4, base_sleep: float = 1.0) -> requests.Response:
    """Backoff GET with retry on 429 and transient network errors."""
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
            logger.warning("Request error [%s] — retry in %.1fs",
                           exc.__class__.__name__, wait)
            time.sleep(wait)
    raise RuntimeError(f"All {retries} attempts failed for: {url}")


# ── EIA spot price (v1 API) ───────────────────────────────────────────────────

def fetch_eia_spot(start: str, end: str, api_key: str) -> pd.DataFrame:
    """
    Fetch WTI spot price from EIA API v1.
    Series PET.RWTC.D: WTI Crude Oil, Cushing OK, daily, $/BBL.
    """
    logger.info("Fetching EIA WTI spot %s to %s", start, end)

    params = {
        "api_key":   api_key,
        "series_id": EIA_SERIES_ID,
        "start":     start.replace("-", ""),   # v1 uses YYYYMMDD
        "end":       end.replace("-", ""),
    }

    response    = _get(EIA_V1_URL, params=params)
    payload     = response.json()
    series_list = payload.get("series", [])

    if not series_list:
        raise ValueError(
            "EIA returned empty series. "
            "Verify your API key is activated (activation can take up to 1 hour)."
        )

    raw_data = series_list[0].get("data", [])
    if not raw_data:
        raise ValueError("EIA series contained no data for the requested date range.")

    df = pd.DataFrame(raw_data, columns=["date_str", "spot_price"])
    df["date"]       = pd.to_datetime(df["date_str"], format="%Y%m%d")
    df["spot_price"] = pd.to_numeric(df["spot_price"], errors="coerce")
    df = (
        df[["date", "spot_price"]]
        .dropna()
        .sort_values("date")
        .reset_index(drop=True)
    )

    logger.info("EIA spot: %d rows (%s to %s)",
                len(df), df["date"].min().date(), df["date"].max().date())
    return df


# ── Yahoo Finance futures ─────────────────────────────────────────────────────

def fetch_yfinance_futures(ticker: str, start: str, end: str) -> pd.Series:
    """Fetch daily close for a single yfinance ticker. Returns empty Series on failure."""
    try:
        import yfinance as yf
        raw = yf.download(ticker, start=start, end=end,
                          progress=False, auto_adjust=True)
        if raw.empty:
            logger.warning("yfinance: no data for %s", ticker)
            return pd.Series(dtype=float)
        series = raw["Close"].squeeze()
        series.index = pd.to_datetime(series.index)
        series.name  = ticker
        logger.info("yfinance %s: %d rows", ticker, len(series))
        return series
    except Exception as exc:
        logger.warning("yfinance failed for %s: %s", ticker, exc)
        return pd.Series(dtype=float)


def fetch_all_futures(start: str, end: str) -> pd.DataFrame:
    """Fetch front, second, and third month WTI futures. Continues if a tenor fails."""
    logger.info("Fetching WTI futures (3 tenors) %s to %s", start, end)

    series = {}
    for tenor, ticker in FUTURES_TICKERS.items():
        s = fetch_yfinance_futures(ticker, start, end)
        if not s.empty:
            series[tenor] = s

    if not series:
        raise RuntimeError(
            "No futures data retrieved from yfinance. "
            "Check yfinance is installed: pip install yfinance"
        )

    df = pd.DataFrame(series)
    df.index.name = "date"
    df = df.reset_index()
    df.columns = (
        ["date"] + [f"{c}_price" for c in df.columns if c != "date"]
    )
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── Expiry calendar ───────────────────────────────────────────────────────────

def nymex_expiry_calendar(start_year: int, end_year: int) -> pd.DataFrame:
    """
    Approximate NYMEX WTI front-month expiry dates.
    Rule: 3 business days before the 25th of the prior calendar month.
    """
    records = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            prior_month = month - 1 if month > 1 else 12
            prior_year  = year if month > 1 else year - 1
            anchor = pd.Timestamp(year=prior_year, month=prior_month, day=25)
            expiry = anchor - pd.offsets.BDay(3)
            records.append({
                "contract_month": f"{year}-{month:02d}",
                "expiry_date":    expiry
            })
    return pd.DataFrame(records)


def assign_tau(dates: pd.Series, expiry_calendar: pd.DataFrame) -> pd.Series:
    """Compute tau = days to nearest upcoming expiry / 252 for each date."""
    expiries = pd.to_datetime(expiry_calendar["expiry_date"].values)

    def _tau(d):
        future = expiries[expiries >= d]
        if len(future) == 0:
            return np.nan
        return max((future.min() - d).days, 0) / 252.0

    return dates.apply(_tau)


# ── Basis computation ─────────────────────────────────────────────────────────

def compute_basis_panel(spot: pd.DataFrame,
                        futures: pd.DataFrame,
                        expiry_cal: pd.DataFrame) -> pd.DataFrame:
    """Merge spot and futures, compute basis and all derived columns."""
    logger.info("Computing basis panel")

    panel = pd.merge(spot, futures, on="date", how="inner")
    panel = panel.sort_values("date").reset_index(drop=True)

    # Basis per tenor
    for tenor in ["front", "second", "third"]:
        col = f"{tenor}_price"
        if col in panel.columns:
            panel[f"basis_{tenor}"] = panel[col] - panel["spot_price"]

    # Term spread
    if "second_price" in panel.columns and "front_price" in panel.columns:
        panel["term_spread"] = panel["second_price"] - panel["front_price"]

    # Time to expiry
    panel["tau"]      = assign_tau(panel["date"], expiry_cal)
    panel["tau_days"] = (panel["tau"] * 252).round(0).astype("Int64")

    # Tau bins
    panel["tau_bin"] = pd.cut(
        panel["tau_days"].astype(float),
        bins=TAU_BINS,
        labels=TAU_LABELS,
        right=True
    ).astype(str)

    # Rolling variance and volatility of front basis
    if "basis_front" in panel.columns:
        panel["basis_var_21d"] = (
            panel["basis_front"]
            .rolling(window=ROLLING_WINDOW, min_periods=10)
            .var()
        )
        panel["basis_vol_21d"] = np.sqrt(panel["basis_var_21d"])

    # Contango / backwardation
    if "basis_front" in panel.columns:
        panel["contango_flag"] = (panel["basis_front"] > 0).astype(int)
        panel["structure"]     = panel["contango_flag"].map(
            {1: "Contango", 0: "Backwardation"}
        )

    # Time columns for Power BI
    panel["year"]             = panel["date"].dt.year
    panel["month_number"]     = panel["date"].dt.month
    panel["month_name_short"] = panel["date"].dt.strftime("%b")
    panel["period_label"]     = panel["date"].dt.strftime("%Y-%m")

    logger.info("Basis panel: %d rows, %d columns", len(panel), len(panel.columns))
    return panel


# ── Variance by tau ───────────────────────────────────────────────────────────

def compute_variance_by_tau(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate basis variance by tau bin.
    Empirical test of ORBIT Theorem 1: variance should decrease
    monotonically toward the 0-7d bin.
    """
    logger.info("Aggregating variance by tau bin")

    if "basis_front" not in panel.columns or "tau_bin" not in panel.columns:
        logger.warning("Skipping tau variance — required columns missing")
        return pd.DataFrame()

    clean = panel.dropna(subset=["basis_front", "tau_bin"])
    clean = clean[clean["tau_bin"] != "nan"]

    agg = (
        clean
        .groupby("tau_bin", observed=True)
        .agg(
            basis_variance    = ("basis_front", "var"),
            basis_std_dev     = ("basis_front", "std"),
            basis_mean        = ("basis_front", "mean"),
            observation_count = ("basis_front", "count"),
            avg_tau_days      = ("tau_days",     "mean"),
        )
        .reset_index()
    )

    agg = agg.sort_values("avg_tau_days").reset_index(drop=True)
    agg["sort_order"]        = range(len(agg))
    agg["orbit_prediction"]  = np.nan   # populated after calibration run

    logger.info("Variance by tau: %d bins", len(agg))
    return agg


# ── Term structure ────────────────────────────────────────────────────────────

def compute_term_structure(panel: pd.DataFrame) -> pd.DataFrame:
    """Long-format tenor table: one row per (date × tenor)."""
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
                      "year", "month_number",
                      "month_name_short", "period_label"]].copy()
        sub = sub.rename(columns={price_col: "futures_price"})
        sub["tenor"]       = tenor
        sub["tenor_label"] = f"{tenor.capitalize()} Month"
        sub["sort_order"]  = sort_order
        sub["basis"]       = sub["futures_price"] - sub["spot_price"]
        records.append(sub)

    if not records:
        return pd.DataFrame()

    ts = pd.concat(records, ignore_index=True)
    ts = ts.sort_values(["date", "sort_order"]).reset_index(drop=True)

    logger.info("Term structure: %d rows", len(ts))
    return ts


# ── Disruption events ─────────────────────────────────────────────────────────

def build_disruption_events() -> pd.DataFrame:
    """Static annotation reference table."""
    df = pd.DataFrame(DISRUPTION_EVENTS)
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["year"]       = df["event_date"].dt.year
    df["sort_order"] = range(len(df))
    return df


# ── Export ────────────────────────────────────────────────────────────────────

def export_outputs(panel: pd.DataFrame, var_tau: pd.DataFrame,
                   term_struct: pd.DataFrame, events: pd.DataFrame,
                   output_dir: str = "outputs/powerbi") -> None:
    """Export all tables to CSV for Power BI import."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    exports = {
        "basis_panel.csv":       panel,
        "variance_by_tau.csv":   var_tau,
        "term_structure.csv":    term_struct,
        "disruption_events.csv": events,
    }

    for filename, df in exports.items():
        if df is None or df.empty:
            logger.warning("Skipping empty table: %s", filename)
            continue
        path = out / filename
        df.to_csv(path, index=False)
        logger.info("Exported %s → %s (%d rows)", filename, path, len(df))

    print("\n── Export Summary " + "─" * 44)
    for filename, df in exports.items():
        if df is not None and not df.empty:
            print(f"  {filename:<30}  {len(df):>6} rows  {len(df.columns):>3} cols")
    print(f"\n  Output directory: {out.resolve()}")
    print("─" * 62 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline(start: str, end: str, eia_key: str,
                 out_dir: str = "outputs/powerbi") -> Dict[str, pd.DataFrame]:
    """Full pipeline: fetch → compute → export."""
    logger.info("ORBIT pipeline starting: %s → %s", start, end)

    start_year = int(start[:4])
    end_year   = int(end[:4])

    spot        = fetch_eia_spot(start, end, eia_key)
    futures     = fetch_all_futures(start, end)
    expiry_cal  = nymex_expiry_calendar(start_year - 1, end_year + 1)

    panel       = compute_basis_panel(spot, futures, expiry_cal)
    var_tau     = compute_variance_by_tau(panel)
    term_struct = compute_term_structure(panel)
    events      = build_disruption_events()

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
        description="ORBIT WTI Basis Pipeline — exports Power BI CSVs"
    )
    parser.add_argument("--start",   type=str,
                        default="2020-01-01",
                        help="Start date YYYY-MM-DD (default: 2020-01-01)")
    parser.add_argument("--end",     type=str,
                        default=datetime.today().strftime("%Y-%m-%d"),
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--eia_key", type=str,
                        default=os.getenv("EIA_API_KEY", ""),
                        help="EIA API key (or set EIA_API_KEY env variable)")
    parser.add_argument("--out_dir", type=str,
                        default="outputs/powerbi",
                        help="Output directory (default: outputs/powerbi)")
    args = parser.parse_args()

    if not args.eia_key:
        print("\nERROR: EIA API key required.")
        print("  Register free at: https://www.eia.gov/opendata/register.php")
        print("  Run: python pipeline.py --eia_key YOUR_KEY\n")
        print("  Or:  set EIA_API_KEY=YOUR_KEY  then  python pipeline.py\n")
        return

    run_pipeline(
        start   = args.start,
        end     = args.end,
        eia_key = args.eia_key,
        out_dir = args.out_dir,
    )


if __name__ == "__main__":
    main()
