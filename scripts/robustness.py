"""Robustness of the structures that made money in phases 2-4.

    python scripts/robustness.py   -> reports/phase3/robustness.csv, reports/phase3/cumulative_pnl.png

For each structure (daily entries, P&L in % of XRP notional per trade):
    all          every trade
    ex_q4_2024   without entries from 2024-10-15 to 2024-12-31 (the XRP rally of Nov-Dec 2024)
    h1 / h2      entries before / from 2025-07-01
    xrp_leg      the XRP leg alone (what the BTC leg adds = all - xrp_leg)
    worst5       the five worst trades with entry dates
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import REPORTS  # noqa: E402
from xc import trades as T  # noqa: E402

P2, P3 = os.path.join(REPORTS, "phase2"), os.path.join(REPORTS, "phase3")
PICKS = [("phase2", "T7_m0_dollar"), ("phase2", "T30_m0_dollar"),
         ("phase3", "put_T7_m0.5"), ("phase3", "put_T14_m0.5"), ("phase3", "put_T14_m1"), ("phase3", "put_T30_m0.5"),
         ("phase3", "put_T30_m1"), ("phase3", "callspr_T14_m1"), ("phase3", "callspr_T30_m1"),
         ("phase3", "cal_xrp_T7_B30"), ("phase3", "cal_xrp_T14_B60"), ("phase3", "xcal_T7_B30")]
CUT = pd.Timestamp("2025-07-01", tz="UTC")
Q4 = (pd.Timestamp("2024-10-15", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))


def stats(x, days):
    x = np.asarray(x)
    if len(x) < 10:
        return np.nan, np.nan, len(x)
    return 100 * x.mean(), x.mean() / x.std(ddof=1) * np.sqrt(len(x) / max(days, 1)), len(x)


def main():
    rows, curves = [], {}
    for phase, tag in PICKS:
        tr = pd.read_parquet(os.path.join(REPORTS, phase, "trades_%s.parquet" % tag)).sort_values("t")
        days = (tr["exit"] - tr["t"]).dt.total_seconds().median() / 86400
        for c in ("mid", "pess"):
            y = tr["pnl_" + c]
            q4 = (tr["t"] >= Q4[0]) & (tr["t"] < Q4[1])
            row = {"tag": tag, "costs": c, "days": days}
            for name, sel in (("all", slice(None)), ("ex_q4_2024", ~q4), ("h1", tr["t"] < CUT),
                              ("h2", tr["t"] >= CUT)):
                m, ts, n = stats(y[sel], days)
                row.update({name + "_mean": m, name + "_t": ts, name + "_n": n})
            row["xrp_leg_mean"] = 100 * tr["pnl_xrp_" + c].mean()
            w = tr.nsmallest(5, "pnl_" + c)
            row["worst5"] = "; ".join("%s %+.1f" % (t.strftime("%Y-%m-%d"), 100 * v)
                                      for t, v in zip(w["t"], w["pnl_" + c]))
            rows.append(row)
        roll = T.non_overlapping(tr)
        curves[tag] = roll.set_index("exit")["pnl_mid"].cumsum() * 100
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(P3, "robustness.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 90)
    cols = ["tag", "costs", "all_mean", "all_t", "ex_q4_2024_mean", "ex_q4_2024_t", "h1_mean", "h1_t", "h2_mean",
            "h2_t", "xrp_leg_mean"]
    print(df[cols].round(2).to_string(index=False))
    print(df[df["costs"] == "pess"][["tag", "worst5"]].to_string(index=False))
    plot(curves)


def plot(curves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
    COLS = {"put_T14_m0.5": "#2a78d6", "put_T30_m0.5": "#1a4f91", "cal_xrp_T7_B30": "#d9822b",
            "T7_m0_dollar": "#9b9a96", "callspr_T14_m1": "#3f9b5c"}
    LABELS = {"put_T14_m0.5": "short XRP put / long BTC put, 14 d, 0.5 sigma",
              "put_T30_m0.5": "short XRP put / long BTC put, 30 d, 0.5 sigma",
              "cal_xrp_T7_B30": "XRP calendar: short 7 d / long 30 d ATM straddle",
              "callspr_T14_m1": "short XRP / long BTC call spread, 14 d",
              "T7_m0_dollar": "short XRP call / long BTC call, 7 d ATM (phase 2)"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})
    fig, ax = plt.subplots(figsize=(12, 6), facecolor=SURF)
    ax.set_facecolor(SURF)
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=0)
    for tag, col in COLS.items():
        s = curves[tag]
        ax.plot(s.index, s.to_numpy(), color=col, linewidth=1.6, label=LABELS[tag])
    ax.axhline(0, color=INK2, linewidth=1)
    ax.set_ylabel("cumulative P&L, % of XRP notional (one trade at a time, mid costs)")
    ax.set_title("Cross-currency and XRP option structures, rolled at each expiry, 2024-03 to 2026-10", loc="left",
                 color=INK, fontsize=11)
    ax.legend(loc="lower left", frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(P3, "cumulative_pnl.png"), dpi=130, facecolor=SURF)


if __name__ == "__main__":
    main()
