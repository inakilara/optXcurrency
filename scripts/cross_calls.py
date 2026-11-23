"""Phase 2: short XRP call, long BTC call (same expiry), held to expiry. Daily entries at 09:00 UTC.

    python scripts/cross_calls.py run      -> reports/phase2/trades_<tag>.parquet, summary.csv
    python scripts/cross_calls.py report   -> tables printed, by_year.csv

Grid:
    tenor   7, 14, 30 days (common expiry closest in log terms, within 0.6-1.5 x)
    m       strike distance in each asset's own trailing 30 d realised vol: K = F exp(m sigma_RV sqrt(tau)),
            m = 0 (ATM), 0.5, 1, 1.5; so the BTC strike is closer in % terms by the RV ratio
    delta   alternative strike rule: 25-delta calls on both (Black-76 delta from mark IV)
    hedge   none   short XRP call alone (reference)
            beta   BTC dollar delta = beta x XRP dollar delta (beta: trailing 30 d hourly regression, clipped 0.3-3)
            dollar BTC dollar delta = XRP dollar delta
            vega   BTC vega = XRP vega (USD per vol point)
Sizing: 1 USD of XRP notional short (qty = -1 / S_xrp); P&L per 1 USD of XRP notional.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import REPORTS  # noqa: E402
from xc import trades as T  # noqa: E402

OUT = os.path.join(REPORTS, "phase2")
HEDGES = ("none", "beta", "dollar", "vega")


def hedge_qty(D, t, hedge, xrow, brow, qx):
    gx, gb = T.greeks(xrow), T.greeks(brow)
    if hedge == "vega":
        return -qx * gx["vega"] / gb["vega"]
    beta = 1.0 if hedge == "dollar" else float(np.clip(D.beta30.asof(t), 0.3, 3))
    if not np.isfinite(beta):
        return None
    return -beta * qx * gx["delta"] * gx["S"] / (gb["delta"] * gb["S"])


def xcall(D, t, tenor, m=None, delta=None, hedge="beta", is_call=True, sign=-1):
    """sign = -1: short XRP option, long BTC option (the thesis); +1 = the reverse."""
    e = T.common_expiry(D, t, tenor)
    if e is None:
        return None
    if delta is not None:
        d = delta if is_call else -delta
        xr, br = T.pick_delta(D, "xrp", t, e, is_call, d), T.pick_delta(D, "btc", t, e, is_call, d)
    else:
        mm = m if is_call else -m
        xr, br = T.pick_strike(D, "xrp", t, e, is_call, mm), T.pick_strike(D, "btc", t, e, is_call, mm)
    if xr is None or br is None:
        return None
    qx = sign / float(xr["S"])
    legs = [T.leg("xrp", xr, qx)]
    if hedge != "none":
        qb = hedge_qty(D, t, hedge, xr, br, qx)
        if qb is None:
            return None
        legs.append(T.leg("btc", br, qb))
    return legs


def grid():
    for tenor in (7, 14, 30):
        for m in (0.0, 0.5, 1.0, 1.5):
            for h in HEDGES:
                yield "T%d_m%g_%s" % (tenor, m, h), dict(tenor=tenor, m=m, hedge=h)
        for h in HEDGES:
            yield "T%d_d25_%s" % (tenor, h), dict(tenor=tenor, delta=0.25, hedge=h)


def run():
    os.makedirs(OUT, exist_ok=True)
    D = T.Data()
    rows = []
    for tag, kw in grid():
        tr = T.run(D, xcall, **kw)
        tr.to_parquet(os.path.join(OUT, "trades_%s.parquet" % tag))
        for c in ("mid", "pess"):
            rows.append(dict(tag=tag, costs=c, **kw, **T.summarise(tr, c)))
        s = rows[-2]
        print("%-16s n %4d  mean(mid) %+.4f  median %+.4f  std %.4f  worst %+.3f" % (
            tag, s["trades"], s["mean"], s["median"], s["std"], s["worst"]), flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "summary.csv"), index=False)


def report():
    s = pd.read_csv(os.path.join(OUT, "summary.csv"))
    pd.set_option("display.width", 250)
    # variance reduction and residual market exposure vs the unhedged short XRP call, same entry days
    extra = []
    for tag in s["tag"].unique():
        tr = pd.read_parquet(os.path.join(OUT, "trades_%s.parquet" % tag))
        base = pd.read_parquet(os.path.join(OUT, "trades_%s_none.parquet" % tag.rsplit("_", 1)[0]))
        j = tr.merge(base[["t", "pnl_mid"]], on="t", suffixes=("", "_naked"))
        b = np.polyfit(j["ret_btc"], j["pnl_mid"], 1)[0] if len(j) > 10 else np.nan
        ds = {k + "_" + c: v for c in ("mid", "pess") for k, v in T.drift_split(tr, c).items()}
        extra.append({"tag": tag, **ds, "var_reduction": 1 - j["pnl_mid"].var() / j["pnl_mid_naked"].var(),
                      "corr_ret_xrp": j["pnl_mid"].corr(j["ret_xrp"]), "corr_ret_btc": j["pnl_mid"].corr(j["ret_btc"]),
                      "slope_ret_btc": b})
    s = s.merge(pd.DataFrame(extra), on="tag")
    s.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    for c in ("mid", "pess"):
        cols = ["tag", "trades", "mean", "ann_mean", "median", "std", "hit", "worst", "p5", "mean_ex_best5pct",
                "t_stat_eff", "drift_part_" + c, "mean_ex_drift_" + c, "var_reduction", "corr_ret_xrp",
                "roll_sharpe"]
        x = s[s["costs"] == c][cols].copy()
        for k in ("mean", "ann_mean", "median", "std", "worst", "p5", "mean_ex_best5pct", "drift_part_" + c,
                  "mean_ex_drift_" + c):
            x[k] = 100 * x[k]
        print("\n=== costs:", c, "(P&L in % of XRP notional per trade)")
        print(x.round(2).to_string(index=False))
    # by year for the main hedge
    yrs = []
    for tag in s[s["hedge"] == "beta"]["tag"].unique():
        tr = pd.read_parquet(os.path.join(OUT, "trades_%s.parquet" % tag))
        g = tr.groupby(tr["t"].dt.year)
        yrs.append(pd.DataFrame({"tag": tag, "mean_mid": 100 * g["pnl_mid"].mean(),
                                 "mean_pess": 100 * g["pnl_pess"].mean(), "n": g.size()}))
    y = pd.concat(yrs).reset_index().rename(columns={"t": "year"})
    y.to_csv(os.path.join(OUT, "by_year.csv"), index=False)
    print(y.pivot(index="tag", columns="year", values="mean_mid").round(2).to_string())


if __name__ == "__main__":
    run() if sys.argv[1] == "run" else report()
