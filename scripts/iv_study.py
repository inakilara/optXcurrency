"""Phase 1: XRP vs BTC implied vol, volatility premium and skew on Deribit, daily at 09:00 UTC.

    python scripts/iv_study.py build    -> reports/phase1/surface_daily.csv
    python scripts/iv_study.py report   -> reports/phase1/*.csv, *.png

Per asset, day and constant maturity (7, 14, 30, 60 days; ATM interpolated in total variance between the two
expiries around the target):
    atm        ATM implied vol (mark IV, interpolated at log-moneyness 0 from OTM options)
    rr25       25-delta risk reversal: IV(25d call) - IV(25d put)   > 0 = call skew
    bf25       25-delta butterfly: (IV(25d call) + IV(25d put)) / 2 - ATM   (wing richness)
    rv_fwd     realised vol over the next `tenor` days (hourly index returns)   -> vrp = atm - rv_fwd
    rv_past    realised vol over the past `tenor` days                          -> iv_minus_past = atm - rv_past
Cross-asset, per tenor:
    corr_fwd, beta_fwd   correlation and beta of XRP on BTC hourly returns over the next `tenor` days
    corr_past, beta_past the same over the past 30 days
Deltas are Black-76 from mark IV for both chains (the exchange's inverse-BTC and linear-XRP deltas differ in
convention).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import ASSETS, REPORTS, constant_maturity, load_chain, load_index, realised_vol, smile_points  # noqa

OUT = os.path.join(REPORTS, "phase1")
TENORS = (7, 14, 30, 60)
KEYS = ("atm", "c25", "p25", "c10", "p10")


def build():
    os.makedirs(OUT, exist_ok=True)
    idx = load_index()
    r = np.log(idx).diff()
    rows = []
    for asset in ASSETS:
        ch = load_chain(asset)
        for t, g in ch.groupby("t"):
            pts = [smile_points(e) for _, e in g.groupby("expiry") if e["days"].iloc[0] >= 1]
            for T in TENORS:
                row = {"t": t, "asset": asset, "tenor": T}
                for k in KEYS:
                    row[k] = constant_maturity(pts, T, k)
                t1 = t + pd.Timedelta(days=T)
                row["rv_fwd"] = realised_vol(idx[asset], t, t1) if t1 <= idx.index[-1] else np.nan
                row["rv_past"] = realised_vol(idx[asset], t - pd.Timedelta(days=T), t)
                rows.append(row)
        print(asset, "done", flush=True)
    d = pd.DataFrame(rows)
    d["rr25"] = d["c25"] - d["p25"]
    d["bf25"] = 0.5 * (d["c25"] + d["p25"]) - d["atm"]
    d["vrp"] = d["atm"] - d["rv_fwd"]
    d["iv_minus_past"] = d["atm"] - d["rv_past"]
    # cross-asset co-movement
    cross = []
    for t in d["t"].unique():
        for T in TENORS:
            w = r[(r.index > t) & (r.index <= t + pd.Timedelta(days=T))].dropna()
            p = r[(r.index > t - pd.Timedelta(days=30)) & (r.index <= t)].dropna()
            row = {"t": t, "tenor": T}
            for name, x in (("fwd", w), ("past", p)):
                ok = len(x) > 24 and (t + pd.Timedelta(days=T) <= r.index[-1] or name == "past")
                row["corr_" + name] = x["xrp"].corr(x["btc"]) if ok else np.nan
                row["beta_" + name] = x["xrp"].cov(x["btc"]) / x["btc"].var() if ok else np.nan
            cross.append(row)
    d = d.merge(pd.DataFrame(cross), on=["t", "tenor"], how="left")
    d.to_csv(os.path.join(OUT, "surface_daily.csv"), index=False)
    print(len(d), "rows")


# ---------------------------------------------------------------------------------------------------- report
def moments(x):
    x = pd.Series(x).dropna()
    return {"n": len(x), "mean": x.mean(), "median": x.median(), "std": x.std(), "skew": x.skew(),
            "exkurt": x.kurt(), "p5": x.quantile(0.05), "p95": x.quantile(0.95), "pos_share": (x > 0).mean()}


def report():
    d = pd.read_csv(os.path.join(OUT, "surface_daily.csv"), parse_dates=["t"])
    pts = ["atm", "rv_fwd", "vrp", "iv_minus_past", "rr25", "bf25"]
    d[pts + ["c25", "p25", "c10", "p10", "rv_past"]] *= 100  # vol points
    w = d.pivot_table(index=["t", "tenor"], columns="asset",
                      values=pts + ["corr_fwd", "beta_fwd", "corr_past", "beta_past"])
    w.columns = ["%s_%s" % c for c in w.columns]
    w = w.reset_index()
    w["iv_ratio"] = w["atm_xrp"] / w["atm_btc"]
    w["rv_ratio"] = w["rv_fwd_xrp"] / w["rv_fwd_btc"]
    w["vrp_diff"] = w["vrp_xrp"] - w["vrp_btc"]
    w["rr_diff"] = w["rr25_xrp"] - w["rr25_btc"]
    w["corr"], w["beta"] = w["corr_fwd_xrp"], w["beta_fwd_xrp"]
    w.to_csv(os.path.join(OUT, "cross_daily.csv"), index=False)

    rows = []
    for T in TENORS:
        x = w[w["tenor"] == T]
        for col in ("atm_xrp", "atm_btc", "rv_fwd_xrp", "rv_fwd_btc", "vrp_xrp", "vrp_btc", "vrp_diff",
                    "rr25_xrp", "rr25_btc", "rr_diff", "bf25_xrp", "bf25_btc", "iv_ratio", "rv_ratio", "corr",
                    "beta"):
            rows.append(dict(tenor=T, series=col, **moments(x[col])))
    m = pd.DataFrame(rows)
    m.to_csv(os.path.join(OUT, "moments.csv"), index=False)
    # by year, 7 and 30 days
    w["year"] = w["t"].dt.year
    yr = w[w["tenor"].isin([7, 30])].groupby(["tenor", "year"])[
        ["atm_xrp", "atm_btc", "vrp_xrp", "vrp_btc", "vrp_diff", "rr25_xrp", "rr25_btc", "iv_ratio", "rv_ratio",
         "corr", "beta"]].median()
    yr.to_csv(os.path.join(OUT, "by_year_median.csv"))
    pd.set_option("display.width", 220)
    print(m.pivot(index="series", columns="tenor", values="median").round(2).to_string())
    print(m[m["tenor"].isin([7, 30])].set_index(["tenor", "series"])[
        ["mean", "std", "skew", "exkurt", "p5", "p95", "pos_share"]].round(2).to_string())
    print(yr.round(2).to_string())
    plots(w)


def plots(w):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    XC, BC, INK, INK2, GRID, SURF = "#2a78d6", "#d9822b", "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})

    def style(ax, title):
        ax.set_facecolor(SURF)
        ax.grid(color=GRID, linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(length=0)
        ax.set_title(title, loc="left", color=INK, fontsize=10)

    def box(ax, x, label, color, y):
        x = pd.Series(x).dropna()
        ax.text(0.98, y, "%s  median %.1f  mean %.1f\nstd %.1f  skew %.2f  exkurt %.1f" % (
            label, x.median(), x.mean(), x.std(), x.skew(), x.kurt()), transform=ax.transAxes, ha="right",
            va="top", fontsize=8, color=color, family="DejaVu Sans Mono")

    # 1. distributions: ATM IV, VRP, RR (7 d and 30 d)
    fig, axes = plt.subplots(3, 2, figsize=(13, 11), facecolor=SURF)
    for j, T in enumerate((7, 30)):
        x = w[w["tenor"] == T]
        for i, (base, title) in enumerate((("atm", "ATM implied vol"), ("vrp", "volatility premium: IV - next RV"),
                                           ("rr25", "25d risk reversal: call IV - put IV"))):
            ax = axes[i, j]
            style(ax, "%s, %d-day (vol points)" % (title, T))
            a, b = x[base + "_xrp"].dropna(), x[base + "_btc"].dropna()
            lo, hi = np.nanpercentile(np.r_[a, b], [0.5, 99.5])
            bins = np.linspace(lo, hi, 60)
            ax.hist(b.clip(lo, hi), bins=bins, density=True, color=BC, alpha=0.6, label="BTC")
            ax.hist(a.clip(lo, hi), bins=bins, density=True, color=XC, alpha=0.6, label="XRP")
            if base != "atm":
                ax.axvline(0, color=INK2, linewidth=1)
            box(ax, a, "XRP", XC, 0.97)
            box(ax, b, "BTC", BC, 0.80)
            ax.legend(loc="upper left", frameon=False)
    fig.suptitle("XRP vs BTC options on Deribit, daily at 09:00 UTC, 2024-03 to 2026-10 (tails clipped at the "
                 "0.5 / 99.5 percentiles for display)", x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(os.path.join(OUT, "distributions.png"), dpi=130, facecolor=SURF)

    # 2. time series, 30 d: IV both, premium both (30-day rolling median), IV ratio vs RV ratio
    x = w[w["tenor"] == 30].set_index("t").sort_index()
    x7 = w[w["tenor"] == 7].set_index("t").sort_index()
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), facecolor=SURF, sharex=True)
    ax = axes[0]
    style(ax, "30-day ATM implied vol (vol points)")
    ax.plot(x.index, x["atm_xrp"], color=XC, linewidth=1.2, label="XRP")
    ax.plot(x.index, x["atm_btc"], color=BC, linewidth=1.2, label="BTC")
    ax.legend(loc="upper left", frameon=False)
    ax = axes[1]
    style(ax, "7-day volatility premium, IV - next 7 d RV, 30-day rolling median (vol points)")
    ax.plot(x7.index, x7["vrp_xrp"].rolling(30, min_periods=10).median(), color=XC, linewidth=1.2, label="XRP")
    ax.plot(x7.index, x7["vrp_btc"].rolling(30, min_periods=10).median(), color=BC, linewidth=1.2, label="BTC")
    ax.axhline(0, color=INK2, linewidth=1)
    ax.legend(loc="upper left", frameon=False)
    ax = axes[2]
    style(ax, "30-day XRP / BTC ratios: implied vol ratio vs the realised vol ratio that followed")
    ax.plot(x.index, x["iv_ratio"], color=XC, linewidth=1.2, label="IV ratio (XRP / BTC)")
    ax.plot(x.index, x["rv_ratio"], color=INK2, linewidth=1.0, label="next 30 d RV ratio")
    ax.axhline(1, color=GRID, linewidth=1)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "time_series.png"), dpi=130, facecolor=SURF)
    print("plots ->", OUT)


if __name__ == "__main__":
    build() if sys.argv[1] == "build" else report()
