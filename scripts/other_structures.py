"""Phases 3-4: other cross-currency verticals, diagonals and calendars. Daily entries at 09:00 UTC.

    python scripts/other_structures.py run [i/n]   -> reports/phase3/trades_<tag>.parquet
    python scripts/other_structures.py report      -> reports/phase3/summary.csv

The XRP side is always the short-premium side (1 USD of XRP notional per leg-unit), the BTC side the long side,
except where noted. Strike distances are in each asset's trailing 30 d realised vol (m), as in phase 2.
Sizing rules (beta = trailing 30 d hourly beta of XRP on BTC, clipped 0.3-3):
    beta-delta   BTC dollar delta = -beta x XRP dollar delta            (directional structures)
    beta2-gamma  BTC cash gamma   = beta^2 x XRP cash gamma (sign flipped) (delta-neutral structures: a short
                 XRP straddle loses beta^2 x (BTC move)^2 through the common factor; the BTC straddle offsets it)
    vega         BTC vega = XRP vega (sign flipped)
Verticals (one common expiry):
    put        short XRP put (m below)              long BTC put                          beta-delta
    straddle   short XRP ATM straddle              long BTC ATM straddle                 beta2-gamma | vega
    strangle   short XRP +/-1 sigma strangle       long BTC +/-1 sigma strangle          beta2-gamma
    callspr    short XRP call spread (ATM / +1 s)   long BTC call spread (ATM / +1 s)     beta-delta
    rr         short XRP 25d risk reversal (sell 25d call, buy 25d put), long BTC 25d RR      beta-delta
               (the skew trade: XRP calls rich vs BTC calls, phase 1)
Diagonals (XRP front expiry, BTC back expiry; held to the XRP expiry, BTC closed at the 09:00 quotes):
    dcall      short XRP front call (m)             long BTC back call (m)               beta-delta
    dstraddle  short XRP front ATM straddle         long BTC back ATM straddle           beta2-gamma | vega
Calendars (phase 4; front expiry ~ tenor, back ~ back days; back leg closed at the front expiry):
    cal_<a>    short front ATM straddle, long back ATM straddle, same asset (a = xrp | btc), equal units
    xcal       XRP calendar (short XRP front, long XRP back straddle) + BTC reverse calendar (long BTC front,
               short BTC back), BTC scaled beta2-gamma on the front legs: relative term structure
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import REPORTS  # noqa: E402
from xc import trades as T  # noqa: E402

OUT = os.path.join(REPORTS, "phase3")


def beta(D, t):
    return float(np.clip(D.beta30.asof(t), 0.3, 3))


def tot(rows_qty, key):
    return sum(q * T.greeks(r)[key] * (T.greeks(r)["S"] if key == "delta" else 1.0) for r, q in rows_qty)


def scale_btc(D, t, x, b, rule):
    """x, b: lists of (row, qty); b is a unit shape. Returns b scaled by the sizing rule (None if degenerate)."""
    if rule == "beta-delta":
        num, den = -beta(D, t) * tot(x, "delta"), tot(b, "delta")
    elif rule == "beta2-gamma":
        num, den = -beta(D, t) ** 2 * tot(x, "cash_gamma"), tot(b, "cash_gamma")
    else:
        num, den = -tot(x, "vega"), tot(b, "vega")
    if not np.isfinite(den) or not np.isfinite(num) or abs(den) < 1e-12:
        return None
    k = num / den
    return [(r, q * k) for r, q in b]


def legs_out(x, b):
    return [T.leg("xrp", r, q) for r, q in x] + [T.leg("btc", r, q) for r, q in b]


def strikes(D, a, t, e, spec):
    """spec: list of (is_call, m) -> rows (None if any missing)."""
    rows = [T.pick_strike(D, a, t, e, c, m) for c, m in spec]
    return None if any(r is None for r in rows) else rows


# ------------------------------------------------------------------------------------------------ verticals
def vertical(D, t, tenor, kind, m=1.0, rule=None):
    e = T.common_expiry(D, t, tenor)
    if e is None:
        return None
    if kind == "put":
        spec, signs, rule = [(False, -m)], [1], rule or "beta-delta"
    elif kind == "straddle":
        spec, signs, rule = [(True, 0.0), (False, 0.0)], [1, 1], rule or "beta2-gamma"
    elif kind == "strangle":
        spec, signs, rule = [(True, m), (False, -m)], [1, 1], rule or "beta2-gamma"
    elif kind == "callspr":
        spec, signs, rule = [(True, 0.0), (True, m)], [1, -1], rule or "beta-delta"
    elif kind == "rr":
        xr = [T.pick_delta(D, "xrp", t, e, True, 0.25), T.pick_delta(D, "xrp", t, e, False, -0.25)]
        br = [T.pick_delta(D, "btc", t, e, True, 0.25), T.pick_delta(D, "btc", t, e, False, -0.25)]
        if any(r is None for r in xr + br):
            return None
        qx = 1 / float(xr[0]["S"])
        x = [(xr[0], -qx), (xr[1], qx)]
        b = scale_btc(D, t, x, [(br[0], 1.0), (br[1], -1.0)], rule or "beta-delta")
        return legs_out(x, b) if b else None
    else:
        raise ValueError(kind)
    xr, br = strikes(D, "xrp", t, e, spec), strikes(D, "btc", t, e, spec)
    if xr is None or br is None:
        return None
    qx = 1 / float(xr[0]["S"])
    x = [(r, -s * qx) for r, s in zip(xr, signs)]
    b = scale_btc(D, t, x, [(r, float(s)) for r, s in zip(br, signs)], rule)
    return legs_out(x, b) if b else None


# ------------------------------------------------------------------------------------------------ diagonals
def diagonal(D, t, tenor, back, kind, m=0.0, rule=None):
    ex = T.common_expiry(D, t, tenor, assets=("xrp",))
    eb = T.common_expiry(D, t, back, assets=("btc",))
    if ex is None or eb is None or eb <= ex:
        return None
    spec = [(True, m)] if kind == "dcall" else [(True, 0.0), (False, 0.0)]
    rule = rule or ("beta-delta" if kind == "dcall" else "beta2-gamma")
    xr, br = strikes(D, "xrp", t, ex, spec), strikes(D, "btc", t, eb, spec)
    if xr is None or br is None:
        return None
    qx = 1 / float(xr[0]["S"])
    x = [(r, -qx) for r in xr]
    b = scale_btc(D, t, x, [(r, 1.0) for r in br], rule)
    return legs_out(x, b) if b else None


# ------------------------------------------------------------------------------------------------ calendars
def calendar(D, t, tenor, back, asset):
    ef = T.common_expiry(D, t, tenor, assets=(asset,))
    eb = T.common_expiry(D, t, back, assets=(asset,))
    if ef is None or eb is None or eb <= ef:
        return None
    spec = [(True, 0.0), (False, 0.0)]
    fr, br = strikes(D, asset, t, ef, spec), strikes(D, asset, t, eb, spec)
    if fr is None or br is None:
        return None
    q = 1 / float(fr[0]["S"])
    return [T.leg(asset, r, -q) for r in fr] + [T.leg(asset, r, q) for r in br]


def xcalendar(D, t, tenor, back):
    """XRP calendar (short front, long back) + BTC reverse calendar, BTC scaled beta2 x cash gamma of the fronts."""
    ef = T.common_expiry(D, t, tenor)
    ebx = T.common_expiry(D, t, back, assets=("xrp",))
    ebb = T.common_expiry(D, t, back, assets=("btc",))
    if ef is None or ebx is None or ebb is None or min(ebx, ebb) <= ef:
        return None
    spec = [(True, 0.0), (False, 0.0)]
    xf, xb = strikes(D, "xrp", t, ef, spec), strikes(D, "xrp", t, ebx, spec)
    bf, bb = strikes(D, "btc", t, ef, spec), strikes(D, "btc", t, ebb, spec)
    if any(v is None for v in (xf, xb, bf, bb)):
        return None
    qx = 1 / float(xf[0]["S"])
    xfront = [(r, -qx) for r in xf]
    k = scale_btc(D, t, xfront, [(r, 1.0) for r in bf], "beta2-gamma")
    if k is None:
        return None
    qb = k[0][1]
    return legs_out(xfront + [(r, qx) for r in xb], [(r, qb) for r in bf] + [(r, -qb) for r in bb])


# ------------------------------------------------------------------------------------------------------ grid
def grid():
    for tenor in (7, 14, 30):
        for m in (0.5, 1.0):
            yield "put_T%d_m%g" % (tenor, m), vertical, dict(tenor=tenor, kind="put", m=m)
        yield "straddle_T%d_gamma" % tenor, vertical, dict(tenor=tenor, kind="straddle")
        yield "straddle_T%d_vega" % tenor, vertical, dict(tenor=tenor, kind="straddle", rule="vega")
        yield "strangle_T%d_m1" % tenor, vertical, dict(tenor=tenor, kind="strangle", m=1.0)
        yield "callspr_T%d_m1" % tenor, vertical, dict(tenor=tenor, kind="callspr", m=1.0)
        yield "rr_T%d" % tenor, vertical, dict(tenor=tenor, kind="rr")
    for tenor, back in ((7, 30), (7, 60), (14, 60)):
        for m in (0.0, 1.0):
            yield "dcall_T%d_B%d_m%g" % (tenor, back, m), diagonal, dict(tenor=tenor, back=back, kind="dcall", m=m)
        yield "dstraddle_T%d_B%d_gamma" % (tenor, back), diagonal, dict(tenor=tenor, back=back, kind="dstraddle")
        yield "dstraddle_T%d_B%d_vega" % (tenor, back), diagonal, dict(tenor=tenor, back=back, kind="dstraddle",
                                                                       rule="vega")
        for a in ("xrp", "btc"):
            yield "cal_%s_T%d_B%d" % (a, tenor, back), calendar, dict(tenor=tenor, back=back, asset=a)
        yield "xcal_T%d_B%d" % (tenor, back), xcalendar, dict(tenor=tenor, back=back)


def run(i=0, n=1):
    os.makedirs(OUT, exist_ok=True)
    D = T.Data()
    for j, (tag, fn, kw) in enumerate(grid()):
        path = os.path.join(OUT, "trades_%s.parquet" % tag)
        if j % n != i or os.path.exists(path):
            continue
        tr = T.run(D, fn, **kw)
        tr.to_parquet(path)
        s = T.summarise(tr, "mid") if len(tr) else {"trades": 0, "mean": np.nan, "median": np.nan, "worst": np.nan}
        print("%-26s n %4d  mean(mid) %+.4f  median %+.4f  worst %+.3f" % (
            tag, s["trades"], s["mean"], s["median"], s["worst"]), flush=True)


def report():
    rows = []
    for tag, fn, kw in grid():
        p = os.path.join(OUT, "trades_%s.parquet" % tag)
        if not os.path.exists(p):
            continue
        tr = pd.read_parquet(p)
        if len(tr) < 20:
            continue
        for c in ("mid", "pess"):
            s = T.summarise(tr, c)
            s.update(T.drift_split(tr, c))
            s["corr_ret_xrp"] = tr["pnl_" + c].corr(tr["ret_xrp"])
            s["corr_ret_btc"] = tr["pnl_" + c].corr(tr["ret_btc"])
            g = tr.groupby(tr["t"].dt.year)["pnl_" + c].mean()
            rows.append(dict(tag=tag, costs=c, **{k: v for k, v in kw.items()},
                             **{"y%d" % y: v for y, v in g.items()}, **s))
    s = pd.DataFrame(rows)
    s.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    pd.set_option("display.width", 250)
    cols = ["tag", "trades", "mean", "ann_mean", "median", "std", "hit", "worst", "p5", "mean_ex_best5pct",
            "t_stat_eff", "drift_part", "mean_ex_drift", "corr_ret_xrp", "y2024", "y2025", "y2026", "roll_sharpe"]
    for c in ("mid", "pess"):
        x = s[s["costs"] == c][cols].copy()
        for k in ("mean", "ann_mean", "median", "std", "worst", "p5", "mean_ex_best5pct", "drift_part",
                  "mean_ex_drift", "y2024", "y2025", "y2026"):
            x[k] = 100 * x[k]
        print("\n=== costs:", c, "(P&L in % of XRP notional per trade)")
        print(x.round(2).to_string(index=False))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        a = sys.argv[2] if len(sys.argv) > 2 else "0/1"
        run(*map(int, a.split("/")))
    else:
        report()
