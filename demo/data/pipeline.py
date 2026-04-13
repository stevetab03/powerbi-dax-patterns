"""
ORBIT Data Pipeline
Created by Liyuan Zhang
===================
WTI Futures-Spot Basis Panel for Power BI

Sources (both free, no API key required):
  - WTI spot price     : FRED public CSV  (series DCOILWTICO)
  - WTI front-month    : Yahoo Finance    (ticker CL=F)

Outputs (Power BI CSVs):
  - basis_panel.csv          daily: spot, futures, basis, tau, rolling variance
  - variance_by_tau.csv      basis variance by time-to-expiry bin
  - term_structure.csv       spot vs front-month futures
  - disruption_events.csv    geopolitical event annotations

Usage:
  python pipeline.py --start 2020-01-01
  python pipeline.py --start 2020-01-01 --end 2024-12-31
"""

import os
import time
import logging
import argparse
import requests
import numpy as np
import pandas as pd
from io import StringIO
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Constants

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO"
FUTURES_TICKER = "CL=F"
ROLLING_WINDOW = 21

TAU_BINS = [0, 7, 14, 21, 30, 45, 60, 90]
TAU_LABELS = ["0-7d", "8-14d", "15-21d", "22-30d", "31-45d", "46-60d", "61-90d"]

DISRUPTION_EVENTS = [
    (
        "2020-04-20",
        "WTI Negative Price",
        "MARKET_STRUCTURE",
        "Front-month WTI settles at -$37.63 due to storage constraints",
    ),
    (
        "2022-02-24",
        "Ukraine Invasion",
        "GEOPOLITICAL",
        "Russia invades Ukraine; WTI basis widens sharply",
    ),
    (
        "2022-03-08",
        "WTI $130 Peak",
        "GEOPOLITICAL",
        "WTI reaches 14-year high of $130.50",
    ),
    (
        "2023-10-07",
        "Hamas Attack",
        "GEOPOLITICAL",
        "Israel-Hamas conflict begins; Middle East risk premium enters",
    ),
    (
        "2026-02-28",
        "US-Iran War Begins",
        "GEOPOLITICAL",
        "US and Israel strike Iran; Strait of Hormuz effectively closes",
    ),
    (
        "2026-03-11",
        "IEA Emergency Release",
        "POLICY",
        "Largest-ever IEA emergency stock release; 11mb/d Gulf production offline",
    ),
    (
        "2026-04-07",
        "US-Iran Ceasefire",
        "GEOPOLITICAL",
        "Two-week ceasefire. WTI -16% in one session. Brent spot $124 vs futures $94",
    ),
]


# ── Fetch


def fetch_spot(start: str, end: str) -> pd.DataFrame:
    """WTI spot price from FRED — no API key required."""
    logger.info("Fetching WTI spot from FRED (%s to %s)", start, end)
    r = requests.get(FRED_URL, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))
    df.columns = ["date", "spot_price"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["spot_price"] = pd.to_numeric(df["spot_price"], errors="coerce")
    df = df.dropna()
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.sort_values("date").reset_index(drop=True)
    logger.info(
        "Spot: %d rows (%s to %s)",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )
    return df


def fetch_futures(start: str, end: str) -> pd.DataFrame:
    """WTI front-month futures from Yahoo Finance — no API key required."""
    logger.info("Fetching WTI front-month futures from yfinance (%s to %s)", start, end)
    import yfinance as yf

    raw = yf.download(
        FUTURES_TICKER, start=start, end=end, progress=False, auto_adjust=True
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data for CL=F")
    df = raw[["Close"]].reset_index()
    df.columns = ["date", "front_price"]
    df["date"] = pd.to_datetime(df["date"])
    df["front_price"] = pd.to_numeric(df["front_price"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)
    logger.info(
        "Futures: %d rows (%s to %s)",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )
    return df


# ── Expiry calendar


def build_expiry_calendar(start_year: int, end_year: int) -> pd.DataFrame:
    """
    Approximate NYMEX WTI front-month expiry dates.
    Rule: 3 business days before the 25th of the prior calendar month.
    """
    rows = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            py = year if month > 1 else year - 1
            pm = month - 1 if month > 1 else 12
            expiry = pd.Timestamp(year=py, month=pm, day=25) - pd.offsets.BDay(3)
            rows.append(
                {"contract_month": f"{year}-{month:02d}", "expiry_date": expiry}
            )
    return pd.DataFrame(rows)


def assign_tau(dates: pd.Series, expiry_cal: pd.DataFrame) -> pd.Series:
    """Days to nearest upcoming front-month expiry, divided by 252."""
    expiries = pd.to_datetime(expiry_cal["expiry_date"].values)

    def _tau(d):
        future = expiries[expiries >= d]
        return max((future.min() - d).days, 0) / 252.0 if len(future) else np.nan

    return dates.apply(_tau)


# ── Compute


def build_basis_panel(
    spot: pd.DataFrame, futures: pd.DataFrame, expiry_cal: pd.DataFrame
) -> pd.DataFrame:
    logger.info("Building basis panel")
    panel = pd.merge(spot, futures, on="date", how="inner")
    panel = panel.sort_values("date").reset_index(drop=True)

    panel["basis"] = panel["front_price"] - panel["spot_price"]
    panel["tau"] = assign_tau(panel["date"], expiry_cal)
    panel["tau_days"] = (panel["tau"] * 252).round(0).astype("Int64")
    panel["tau_bin"] = pd.cut(
        panel["tau_days"].astype(float), bins=TAU_BINS, labels=TAU_LABELS, right=True
    ).astype(str)
    panel["basis_var_21d"] = (
        panel["basis"].rolling(ROLLING_WINDOW, min_periods=10).var()
    )
    panel["basis_vol_21d"] = np.sqrt(panel["basis_var_21d"])
    panel["structure"] = panel["basis"].apply(
        lambda x: "Contango" if x > 0 else "Backwardation"
    )
    panel["year"] = panel["date"].dt.year
    panel["month_number"] = panel["date"].dt.month
    panel["month_short"] = panel["date"].dt.strftime("%b")
    panel["period_label"] = panel["date"].dt.strftime("%Y-%m")

    logger.info("Basis panel: %d rows, %d cols", len(panel), len(panel.columns))
    return panel


def build_variance_by_tau(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Basis variance aggregated by tau bin.
    Empirical test of ORBIT Theorem 1: variance should decrease
    monotonically as tau approaches zero.
    """
    logger.info("Aggregating variance by tau bin")
    clean = panel.dropna(subset=["basis", "tau_bin"])
    clean = clean[clean["tau_bin"] != "nan"]
    agg = (
        clean.groupby("tau_bin", observed=True)
        .agg(
            basis_variance=("basis", "var"),
            basis_std_dev=("basis", "std"),
            basis_mean=("basis", "mean"),
            observation_count=("basis", "count"),
            avg_tau_days=("tau_days", "mean"),
        )
        .reset_index()
        .sort_values("avg_tau_days")
        .reset_index(drop=True)
    )
    agg["sort_order"] = range(len(agg))
    logger.info("Variance by tau: %d bins", len(agg))
    return agg


def build_term_structure(panel: pd.DataFrame) -> pd.DataFrame:
    """Spot vs front-month futures — long format for chart legend."""
    logger.info("Building term structure table")
    spot = panel[
        ["date", "spot_price", "year", "month_number", "month_short", "period_label"]
    ].copy()
    spot = spot.rename(columns={"spot_price": "price"})
    spot["series"] = "Spot"
    spot["sort_order"] = 1

    fwd = panel[
        ["date", "front_price", "year", "month_number", "month_short", "period_label"]
    ].copy()
    fwd = fwd.rename(columns={"front_price": "price"})
    fwd["series"] = "Front-Month Futures"
    fwd["sort_order"] = 2

    ts = pd.concat([spot, fwd], ignore_index=True)
    return ts.sort_values(["date", "sort_order"]).reset_index(drop=True)


def build_disruption_events() -> pd.DataFrame:
    df = pd.DataFrame(
        DISRUPTION_EVENTS,
        columns=["event_date", "event_label", "event_type", "description"],
    )
    df["event_date"] = pd.to_datetime(df["event_date"])
    df["year"] = df["event_date"].dt.year
    df["sort_order"] = range(len(df))
    return df


# ── Export


def export(panel, var_tau, term_struct, events, out_dir="outputs/powerbi"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "basis_panel.csv": panel,
        "variance_by_tau.csv": var_tau,
        "term_structure.csv": term_struct,
        "disruption_events.csv": events,
    }
    for name, df in files.items():
        df.to_csv(out / name, index=False)
        logger.info("Saved %s (%d rows)", name, len(df))

    print("\n── Export Summary " + "─" * 42)
    for name, df in files.items():
        print(f"  {name:<30}  {len(df):>6} rows  {len(df.columns):>3} cols")
    print(f"\n  Output: {out.resolve()}")
    print("─" * 60 + "\n")


# ── Pipeline


def run(start: str, end: str, out_dir: str = "outputs/powerbi"):
    logger.info("ORBIT pipeline: %s → %s", start, end)

    spot = fetch_spot(start, end)
    futures = fetch_futures(start, end)
    expiry_cal = build_expiry_calendar(int(start[:4]) - 1, int(end[:4]) + 1)

    panel = build_basis_panel(spot, futures, expiry_cal)
    var_tau = build_variance_by_tau(panel)
    term_struct = build_term_structure(panel)
    events = build_disruption_events()

    export(panel, var_tau, term_struct, events, out_dir)
    logger.info("Done.")


# ── CLI


def main():
    p = argparse.ArgumentParser(description="ORBIT WTI Basis Pipeline")
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default=datetime.today().strftime("%Y-%m-%d"))
    p.add_argument("--out_dir", default="outputs/powerbi")
    args = p.parse_args()
    run(args.start, args.end, args.out_dir)


if __name__ == "__main__":
    main()
