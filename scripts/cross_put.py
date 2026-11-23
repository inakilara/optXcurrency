"""Cross-put portfolio: short XRP puts hedged with long BTC puts, weekly tranches, daily marks.

    python scripts/cross_put.py grid        -> reports/phase5/grid.csv          (tenor x distance x hedge ratio)
    python scripts/cross_put.py variants    -> reports/phase5/variants.csv      (BTC strike, sizing, schedule)
    python scripts/cross_put.py final       -> reports/phase5/final*.csv, equity.png

Rules
- Every Friday at 09:00 UTC (one hour after the weekly settlement) open one tranche:
    short XRP put, strike K = F exp(-m sigma_RV sqrt(tau)) on the expiry closest to `tenor` days;
    long BTC put on the same expiry, strike at distance m_btc (default = m) in BTC's own realised vol,
    quantity = h x beta x XRP dollar delta / BTC dollar delta (beta: trailing 30 d hourly, clipped 0.3-3).
- Tranche size: XRP notional = f x equity x 7 / tenor, so about f x equity of XRP notional is open at once.
- Held to expiry, settled at the hourly index. Fills: mid + 10 bps or bid/ask + 3 bps (fee capped at 12.5 % of
  the price). Daily valuation at the exchange mark price (09:00).
- Margin (simplified Deribit standard margin, no portfolio offsets): short XRP put max(0.15 - OTM, 0.10) x S + mark
  per unit; long BTC puts need only their premium. Reported as the peak of margin / equity. On Deribit the XRP leg
  is USDC-margined and the BTC leg BTC-margined, so the two need separate collateral.
Metrics from the daily equity curve: CAGR, annualised vol, max drawdown, Sharpe (daily, x sqrt 365), worst month.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import REPORTS, fill  # noqa: E402
from xc import trades as T  # noqa: E402

OUT = os.path.join(REPORTS, "phase5")
SPLIT = pd.Timestamp("2025-07-01", tz="UTC")


def tranche(D, t, tenor, m, h, m_btc=None, gate=None):
    """gate: skip the tranche unless the XRP put's IV exceeds XRP's trailing 30 d realised vol by `gate` (decimal)."""
    e = T.common_expiry(D, t, tenor)
    if e is None:
        return None
    xr = T.pick_strike(D, "xrp", t, e, False, -m)
    if xr is None:
        return None
    if gate is not None and not float(xr["iv"]) - float(D.rv30["xrp"].asof(t)) > gate:
        return None
    legs = [("xrp", xr, -1.0 / float(xr["S"]))]
    if h > 0:
        mb = m if m_btc is None else m_btc
        br = T.pick_strike(D, "btc", t, e, False, -mb)
        beta = D.beta30.asof(t)
        if br is None or not np.isfinite(beta):
            return None
        gx, gb = T.greeks(xr), T.greeks(br)
        qb = -h * float(np.clip(beta, 0.3, 3)) * legs[0][2] * gx["delta"] * gx["S"] / (gb["delta"] * gb["S"])
        legs.append(("btc", br, qb))
    return legs


def simulate(D, tenor=30, m=0.5, h=1.0, f=1.0, costs="pess", m_btc=None, weekday=4, start=None, end=None,
             gate=None):
    cash, eq0 = 1.0, 1.0
    pos = []            # dicts: asset, expiry, strike, is_call, qty, last_mark
    rec = []
    for t in D.times:
        if (start is not None and t < start) or (end is not None and t >= end):
            continue
        # settle expired legs at the index at expiry
        keep = []
        for p in pos:
            if p["expiry"] <= t:
                S = D.settle(p["asset"], p["expiry"])
                cash += p["qty"] * max(p["strike"] - S, 0.0)
            else:
                keep.append(p)
        pos = keep
        value = 0.0
        for p in pos:
            mk = D.mark[p["asset"]].get((t, p["expiry"], p["strike"], False))
            if mk is not None and np.isfinite(mk):
                p["last"] = mk
            value += p["qty"] * p["last"]
        equity = cash + value
        if t.weekday() == weekday and equity > 0:
            legs = tranche(D, t, tenor, m, h, m_btc, gate)
            if legs:
                N = f * equity * 7.0 / tenor
                for asset, row, q in legs:
                    qty = q * N
                    cash -= fill(row, qty, float(row["S"]), costs)
                    pos.append({"asset": asset, "expiry": row["expiry"], "strike": float(row["strike"]),
                                "qty": qty, "last": float(row["mark"])})
                value = sum(p["qty"] * p["last"] for p in pos)
                equity = cash + value
        margin = 0.0
        for p in pos:
            if p["asset"] == "xrp" and p["qty"] < 0:
                S = float(D.idx["xrp"].asof(t))
                otm = max(S - p["strike"], 0.0) / S
                margin += -p["qty"] * (max(0.15 - otm, 0.10) * S + p["last"])
        rec.append((t, equity, margin / equity if equity > 0 else np.nan, len(pos)))
    h_ = pd.DataFrame(rec, columns=["t", "equity", "margin_ratio", "legs"]).set_index("t")
    return h_


def metrics(h):
    e = h["equity"]
    r = e.pct_change().dropna()
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    m = e.resample("ME").last()
    mr = m / m.shift(1).fillna(e.iloc[0]) - 1
    out = {"CAGR": (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1 if e.iloc[-1] > 0 else -1.0,
           "vol": r.std() * np.sqrt(365.25), "MDD": (e / e.cummax() - 1).min(),
           "Sharpe": r.mean() / r.std() * np.sqrt(365.25) if r.std() > 0 else np.nan,
           "worst_month": mr.min(), "pos_months": (mr > 0).mean(), "peak_margin": h["margin_ratio"].max()}
    yl = e.groupby(e.index.year).last()
    for y, v in (yl / yl.shift(1).fillna(e.iloc[0]) - 1).items():
        out["y%d" % y] = v
    return out


def split_metrics(D, **kw):
    """Full period, in-sample (to 2025-06-30), out-of-sample (from 2025-07-01, restarted at 1)."""
    out = {}
    for name, a, b in (("", None, None), ("is_", None, SPLIT), ("oos_", SPLIT, None)):
        h = simulate(D, start=a, end=b, **kw)
        out.update({name + k: v for k, v in metrics(h).items() if not (name and k.startswith("y"))})
        if not name:
            full = h
    return out, full


def show(df, cols):
    x = df.copy()
    for c in cols:
        if c in x and c not in ("Sharpe", "is_Sharpe", "oos_Sharpe", "peak_margin", "pos_months"):
            x[c] = 100 * x[c]
    pd.set_option("display.width", 250)
    print(x[[c for c in x.columns if c in cols or not c[0].islower() or c in ("tenor", "m", "h", "f", "m_btc",
                                                                                 "costs", "tag")]].round(2)
          .to_string(index=False))


def grid():
    os.makedirs(OUT, exist_ok=True)
    D = T.Data()
    rows = []
    for tenor in (14, 30):
        for m in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
            for h in (0.0, 0.5, 1.0, 1.5):
                for c in ("pess", "mid"):
                    out, _ = split_metrics(D, tenor=tenor, m=m, h=h, f=1.0, costs=c)
                    rows.append(dict(tenor=tenor, m=m, h=h, costs=c, **out))
                r = rows[-2]
                print("T%d m%.2f h%.1f pess: CAGR %5.1f%% vol %5.1f%% MDD %6.1f%% Sharpe %5.2f | IS Sharpe %5.2f "
                      "OOS Sharpe %5.2f" % (tenor, m, h, 100 * r["CAGR"], 100 * r["vol"], 100 * r["MDD"],
                                            r["Sharpe"], r["is_Sharpe"], r["oos_Sharpe"]), flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "grid.csv"), index=False)


def candidates(n=3):
    """Top configurations by in-sample Sharpe at pessimistic costs (hedged only), plus the phase-3 baseline."""
    g = pd.read_csv(os.path.join(OUT, "grid.csv"))
    g = g[(g["costs"] == "pess") & (g["h"] > 0)].sort_values("is_Sharpe", ascending=False)
    picks = [dict(tenor=int(r.tenor), m=float(r.m), h=float(r.h)) for r in g.head(n).itertuples()]
    base = dict(tenor=30, m=0.5, h=1.0)
    return picks + ([base] if base not in picks else [])


def variants():
    D = T.Data()
    rows = []
    for base in candidates():
        tag0 = "T%d_m%g_h%g" % (base["tenor"], base["m"], base["h"])
        runs = [("base", {})]
        runs += [("btc_atm", dict(m_btc=0.0)), ("btc_m+0.5", dict(m_btc=base["m"] + 0.5)),
                 ("btc_m+1", dict(m_btc=base["m"] + 1.0))]
        runs += [("gate_0", dict(gate=0.0)), ("gate_+10", dict(gate=0.10)), ("gate_-10", dict(gate=-0.10))]
        runs += [("f%g" % f, dict(f=f)) for f in (0.5, 1.5, 2.0, 3.0)]
        for name, kw in runs:
            for c in ("pess", "mid"):
                args = dict(base, f=1.0, costs=c)
                args.update(kw)
                out, _ = split_metrics(D, **args)
                rows.append(dict(base=tag0, variant=name, costs=c, **{k: v for k, v in args.items() if k != "costs"},
                                 **out))
            r = rows[-2]
            print("%-14s %-10s pess: CAGR %5.1f%% vol %5.1f%% MDD %6.1f%% Sharpe %5.2f margin %.2f | IS %5.2f OOS "
                  "%5.2f" % (tag0, name, 100 * r["CAGR"], 100 * r["vol"], 100 * r["MDD"], r["Sharpe"],
                             r["peak_margin"], r["is_Sharpe"], r["oos_Sharpe"]), flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "variants.csv"), index=False)


FINAL = [  # (label, kwargs)
    ("naked short XRP put (h = 0)", dict(tenor=30, m=0.5, h=0.0)),
    ("cross-put, BTC put at the same distance, h = 0.5 (in-sample pick)", dict(tenor=30, m=0.5, h=0.5)),
    ("cross-put, BTC put at the same distance, h = 1", dict(tenor=30, m=0.5, h=1.0)),
    ("cross-put, ATM BTC put, h = 1 (recommended)", dict(tenor=30, m=0.5, h=1.0, m_btc=0.0)),
]


def final():
    D = T.Data()
    rows, curves = [], {}
    for label, kw in FINAL:
        for f in (1.0, 2.0):
            for c in ("pess", "mid"):
                out, h = split_metrics(D, f=f, costs=c, **kw)
                wk = h["equity"].resample("W-FRI").last().pct_change().dropna()
                out["vol_weekly"] = wk.std() * np.sqrt(52.18)
                out["Sharpe_weekly"] = wk.mean() / wk.std() * np.sqrt(52.18)
                rows.append(dict(label=label, f=f, costs=c, **kw, **out))
                if c == "pess" and f == 1.0:
                    curves[label] = h["equity"]
                if c == "pess" and "recommended" in label:
                    m = h["equity"].resample("ME").last()
                    (m / m.shift(1).fillna(h["equity"].iloc[0]) - 1).rename("return").to_csv(
                        os.path.join(OUT, "final_monthly_f%g.csv" % f))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "final.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    x = df.copy()
    pct = ["CAGR", "vol", "vol_weekly", "MDD", "worst_month", "pos_months", "is_CAGR", "oos_CAGR", "oos_MDD",
           "y2024", "y2025", "y2026"]
    x[pct] = 100 * x[pct]
    print(x[["label", "f", "costs", "CAGR", "vol", "vol_weekly", "MDD", "Sharpe", "Sharpe_weekly", "worst_month",
             "pos_months", "peak_margin", "is_Sharpe", "oos_Sharpe", "is_CAGR", "oos_CAGR", "y2024", "y2025",
             "y2026"]].round(2).to_string(index=False))
    plot(curves)


def plot(curves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
    cols = ["#9b9a96", "#7fb0e8", "#2a78d6", "#0f3f7a"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})
    fig, (ax, dd) = plt.subplots(2, 1, figsize=(12, 8), facecolor=SURF, sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.3]})
    for a in (ax, dd):
        a.set_facecolor(SURF)
        a.grid(color=GRID, linewidth=0.8)
        a.spines[["top", "right"]].set_visible(False)
        a.tick_params(length=0)
    for (label, e), col in zip(curves.items(), cols):
        lw = 2.0 if "recommended" in label else 1.3
        ax.plot(e.index, e.to_numpy(), color=col, linewidth=lw, label=label)
        dd.plot(e.index, 100 * (e / e.cummax() - 1).to_numpy(), color=col, linewidth=lw)
    ax.axvline(SPLIT, color=INK2, linewidth=1, linestyle="--")
    ax.text(SPLIT, ax.get_ylim()[1], "  in-sample | out-of-sample", va="top", fontsize=8, color=INK2)
    ax.set_ylabel("equity (start = 1)")
    dd.set_ylabel("drawdown, %")
    ax.set_title("Short XRP put (30 d, 0.5 sigma OTM) hedged with long BTC puts: weekly tranches, about 1 x equity "
                 "of XRP notional, bid/ask costs", loc="left", color=INK, fontsize=10.5)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "equity.png"), dpi=130, facecolor=SURF)


if __name__ == "__main__":
    globals()[sys.argv[1]]()
