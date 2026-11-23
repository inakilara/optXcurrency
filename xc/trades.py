"""Trade-level backtest of cross-currency option structures (XRP and BTC on Deribit), daily entries at 09:00 UTC.

A structure is a function ctx -> list of legs, each leg = dict(asset, expiry, strike, is_call, qty) with qty in
units of the underlying (+ long), sized per 1 USD of XRP notional. A trade is held until its first leg's expiry:
    legs expiring then settle at the hourly index at expiry (08:00 UTC; inverse BTC options pay max(S-K,0)/S BTC,
    i.e. max(S-K,0) USD when converted at settlement);
    later legs are closed at the 09:00 quotes of that day (mid or touch + fee, as at entry).
P&L is in USD per 1 USD of XRP notional, so it reads as a fraction of the XRP leg's notional.
"""
import numpy as np
import pandas as pd

from xc.common import ASSETS, COSTS, FEE_CAP, b76_delta, b76_vega, load_chain, load_index  # noqa: F401

TWO_SIDED = lambda d: d[(d["bid"] > 0) & (d["ask"] > 0)]  # noqa: E731


class Data:
    """Per-day two-sided chains for both assets, trailing realised vol and beta, the hourly index."""

    def __init__(self):
        self.idx = load_index()
        self.day = {}
        self.quote = {}
        self.mark = {}
        for a in ASSETS:
            full = load_chain(a)
            self.mark[a] = {(r.t, r.expiry, r.strike, r.is_call): r.mark
                            for r in full[["t", "expiry", "strike", "is_call", "mark"]].itertuples()}
            ch = TWO_SIDED(full)
            del full
            self.day[a] = {t: g.reset_index(drop=True) for t, g in ch.groupby("t")}
            self.quote[a] = {(r.t, r.expiry, r.strike, r.is_call): (r.bid, r.ask, r.S)
                             for r in ch[["t", "expiry", "strike", "is_call", "bid", "ask", "S"]].itertuples()}
        self.times = sorted(set(self.day["xrp"]) & set(self.day["btc"]))
        r = np.log(self.idx).diff()
        rv = np.sqrt((r ** 2).rolling(24 * 30, min_periods=24 * 20).mean() * 8766)
        cov = r["xrp"].rolling(24 * 30, min_periods=24 * 20).cov(r["btc"])
        var = r["btc"].rolling(24 * 30, min_periods=24 * 20).var()
        self.rv30 = rv
        self.beta30 = cov / var

    def settle(self, asset, expiry):
        s = self.idx[asset]
        return float(s.asof(expiry))


# --------------------------------------------------------------------------------------------- selection
def common_expiry(D, t, days, window=(0.6, 1.5), assets=ASSETS):
    """Expiry listed (two-sided) on every asset in `assets`, closest to `days` in log terms, within window."""
    sets = []
    for a in assets:
        g = D.day[a][t]
        e = g.drop_duplicates("expiry").set_index("expiry")["days"]
        sets.append(e[(e >= window[0] * days) & (e <= window[1] * days)])
    common = set(sets[0].index)
    for s in sets[1:]:
        common &= set(s.index)
    if not common:
        return None
    return min(common, key=lambda e: abs(np.log(sets[0][e] / days)))


def pick_strike(D, asset, t, expiry, is_call, m, sigma=None):
    """Listed two-sided strike nearest to F x exp(m x sigma x sqrt(tau)); sigma = trailing 30 d realised vol."""
    g = D.day[asset][t]
    g = g[(g["expiry"] == expiry) & (g["is_call"] == is_call)]
    if g.empty:
        return None
    F, tau = float(g["F"].iloc[0]), float(g["tau"].iloc[0])
    s = sigma if sigma is not None else float(D.rv30[asset].asof(t))
    if not np.isfinite(s):
        return None
    k = F * np.exp(m * s * np.sqrt(tau))
    row = g.iloc[(g["strike"] - k).abs().to_numpy().argmin()]
    # the nearest listed strike must be within half a sigma-step of the target
    if abs(np.log(row["strike"] / k)) > 0.25 * s * np.sqrt(tau) + 1e-9 and m != 0:
        return None
    return row


def pick_delta(D, asset, t, expiry, is_call, delta):
    g = D.day[asset][t]
    g = g[(g["expiry"] == expiry) & (g["is_call"] == is_call)]
    if g.empty:
        return None
    i = (g["delta_bs"] - delta).abs().to_numpy().argmin()
    return g.iloc[i] if abs(g["delta_bs"].iloc[i] - delta) < 0.07 else None


def greeks(row):
    F, K, s, tau = row["F"], row["strike"], row["iv"], row["tau"]
    v = s * np.sqrt(tau)
    d1 = (np.log(F / K) + 0.5 * v * v) / v
    gamma = np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi) / (F * v)
    return {"delta": float(b76_delta(F, K, s, tau, row["is_call"])), "vega": float(b76_vega(F, K, s, tau)) / 100,
            "cash_gamma": float(gamma * F * F), "S": float(row["S"]), "F": float(F)}


def leg(asset, row, qty):
    return {"asset": asset, "expiry": row["expiry"], "strike": float(row["strike"]), "is_call": bool(row["is_call"]),
            "qty": float(qty), "row": row}


# -------------------------------------------------------------------------------------------- evaluation
def evaluate(D, t, legs, costs):
    """-> dict with total P&L and per-asset P&L (USD per 1 USD of XRP notional), entry/exit times; None if a
    quote is missing at entry or exit."""
    c = COSTS[costs]
    exit_t = min(lg["expiry"] for lg in legs)
    close_t = exit_t.floor("D") + pd.Timedelta(hours=9)
    pnl = {a: 0.0 for a in ASSETS}
    fees = 0.0
    for lg in legs:
        q, qty = lg["row"], lg["qty"]
        px = 0.5 * (q["bid"] + q["ask"]) if c["fill"] == "mid" else (q["ask"] if qty > 0 else q["bid"])
        fee = min(c["fee"] * q["S"], FEE_CAP * px) * abs(qty)
        pnl[lg["asset"]] -= qty * px + fee
        fees += fee
        if lg["expiry"] <= exit_t:
            S = D.settle(lg["asset"], lg["expiry"])
            pnl[lg["asset"]] += qty * (max(S - lg["strike"], 0.0) if lg["is_call"] else max(lg["strike"] - S, 0.0))
        else:
            qq = D.quote[lg["asset"]].get((close_t, lg["expiry"], lg["strike"], lg["is_call"]))
            if qq is None:
                return None
            bid, ask, S = qq
            px = 0.5 * (bid + ask) if c["fill"] == "mid" else (bid if qty > 0 else ask)
            fee = min(c["fee"] * S, FEE_CAP * px) * abs(qty)
            pnl[lg["asset"]] += qty * px - fee
            fees += fee
    ret = {a: D.settle(a, exit_t) / float(D.idx[a].asof(t)) - 1 for a in ASSETS}
    return {"t": t, "exit": exit_t, "pnl": pnl["xrp"] + pnl["btc"], "pnl_xrp": pnl["xrp"], "pnl_btc": pnl["btc"],
            "fees": fees, "ret_xrp": ret["xrp"], "ret_btc": ret["btc"]}


def run(D, structure, costs=("mid", "pess"), times=None, **kw):
    """Daily entries; returns a DataFrame of trades with P&L per cost model (columns pnl_<costs> etc.)."""
    out = []
    for t in times or D.times:
        legs = structure(D, t, **kw)
        if not legs:
            continue
        row = {"t": t}
        ok = True
        for cm in costs:
            r = evaluate(D, t, legs, cm)
            if r is None:
                ok = False
                break
            row["exit"], row["ret_xrp"], row["ret_btc"] = r["exit"], r["ret_xrp"], r["ret_btc"]
            for k in ("pnl", "pnl_xrp", "pnl_btc", "fees"):
                row["%s_%s" % (k, cm)] = r[k]
        if not ok:
            continue
        row["legs"] = ";".join("%s %+.4g %s%g%s" % (lg["asset"], lg["qty"], lg["expiry"].strftime("%d%b%y"),
                                                     lg["strike"], "C" if lg["is_call"] else "P") for lg in legs)
        out.append(row)
    return pd.DataFrame(out)


def summarise(tr, costs, label=None):
    """Per-trade stats (overlapping daily entries) + a non-overlapping roll (enter again at each exit day)."""
    x = tr["pnl_" + costs].to_numpy()
    if len(x) == 0:
        return {}
    srt = np.sort(x)
    days = (tr["exit"] - tr["t"]).dt.total_seconds().median() / 86400
    roll = non_overlapping(tr)
    r = roll["pnl_" + costs].to_numpy()
    years = (roll["exit"].iloc[-1] - roll["t"].iloc[0]).days / 365.25 if len(roll) > 1 else np.nan
    eq = np.cumprod(1 + r)
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min()) if len(r) else np.nan
    sd = x.std(ddof=1)
    out = {"label": label, "trades": len(x), "days": days, "mean": x.mean(), "median": np.median(x), "std": sd,
           "ann_mean": x.mean() * 365.25 / max(days, 1),
           "hit": (x > 0).mean(), "worst": x.min(), "p5": np.percentile(x, 5), "best": x.max(),
           "mean_ex_best5pct": srt[: int(0.95 * len(srt))].mean(),
           "skew": pd.Series(x).skew(), "t_stat_eff": x.mean() / sd * np.sqrt(len(x) / max(days, 1)),
           "mean_xrp": tr["pnl_xrp_" + costs].mean(), "mean_btc": tr["pnl_btc_" + costs].mean(),
           "fees": tr["fees_" + costs].mean(),
           "roll_trades": len(r), "roll_cagr": eq[-1] ** (1 / years) - 1 if len(r) > 1 and eq[-1] > 0 else np.nan,
           "roll_sharpe": r.mean() / r.std(ddof=1) * np.sqrt(365.25 / max(days, 1)) if len(r) > 2 else np.nan,
           "roll_mdd": mdd}
    return out


_BETA = {}


def entry_beta(times):
    """Trailing 30 d hourly beta of XRP on BTC at each time (same estimator as Data.beta30, from the index only)."""
    if "b" not in _BETA:
        r = np.log(load_index()).diff()
        _BETA["b"] = r["xrp"].rolling(24 * 30, min_periods=24 * 20).cov(r["btc"]) /             r["btc"].rolling(24 * 30, min_periods=24 * 20).var()
    return np.clip(_BETA["b"].reindex(pd.DatetimeIndex(times), method="ffill").to_numpy(), 0.3, 3)


def drift_split(tr, costs):
    """Split the mean P&L into a part explained by XRP's relative move and the rest.
    rel = ret_xrp - beta x ret_btc (beta at entry). OLS: pnl = a + b rel + c rel^2. The drift part is b x mean(rel)
    (what the structure earned from XRP out- or under-performing BTC on average); `mean_ex_drift` = mean - b mean(rel)
    keeps the premium and the convexity (c x mean(rel^2)) terms."""
    y = tr["pnl_" + costs].to_numpy()
    rel = tr["ret_xrp"].to_numpy() - entry_beta(tr["t"]) * tr["ret_btc"].to_numpy()
    ok = np.isfinite(y) & np.isfinite(rel)
    y, rel = y[ok], rel[ok]
    if len(y) < 20:
        return {}
    X = np.c_[np.ones_like(rel), rel, rel ** 2]
    a, b, c = np.linalg.lstsq(X, y, rcond=None)[0]
    return {"rel_mean": rel.mean(), "slope_rel": b, "curv_rel": c, "drift_part": b * rel.mean(),
            "mean_ex_drift": y.mean() - b * rel.mean(), "intercept": a}


def non_overlapping(tr):
    """Chain of trades: first entry, then the first entry on or after each exit day."""
    tr = tr.sort_values("t").reset_index(drop=True)
    keep, nxt = [], None
    for i, r in tr.iterrows():
        if nxt is None or r["t"] >= nxt:
            keep.append(i)
            nxt = r["exit"].floor("D") + pd.Timedelta(hours=9)
    return tr.loc[keep]
