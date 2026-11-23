"""Shared helpers: cache loaders, Black-76 on the forward, smile points per expiry, realised vol, costs."""
import os

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
REPORTS = os.path.join(ROOT, "reports")
YEAR = 365.25
HOURS_YEAR = 8766.0
ASSETS = ("xrp", "btc")


# ------------------------------------------------------------------------------------------------- data
def load_chain(asset):
    df = pd.read_parquet(os.path.join(CACHE, "chain_%s.parquet" % asset))
    df["tau"] = (df["expiry"] - df["t"]).dt.total_seconds() / (YEAR * 86400)
    df["days"] = df["tau"] * YEAR
    df["mid"] = np.where((df["bid"] > 0) & (df["ask"] > 0), 0.5 * (df["bid"] + df["ask"]), np.nan)
    df["delta_bs"] = b76_delta(df["F"].to_numpy(), df["strike"].to_numpy(), df["iv"].to_numpy(),
                               df["tau"].to_numpy(), df["is_call"].to_numpy())
    return df


def load_index():
    idx = pd.read_parquet(os.path.join(CACHE, "index_1h.parquet"))
    return idx.interpolate(limit=3)


# ---------------------------------------------------------------------------------------------- Black-76
def b76(F, K, s, tau, is_call):
    v = np.maximum(s * np.sqrt(np.maximum(tau, 1e-9)), 1e-9)
    d1 = (np.log(F / K) + 0.5 * v * v) / v
    c = F * ndtr(d1) - K * ndtr(d1 - v)
    return np.where(is_call, c, c - F + K)


def b76_delta(F, K, s, tau, is_call):
    v = np.maximum(s * np.sqrt(np.maximum(tau, 1e-9)), 1e-9)
    d1 = (np.log(F / K) + 0.5 * v * v) / v
    return np.where(is_call, ndtr(d1), ndtr(d1) - 1.0)


def b76_vega(F, K, s, tau):
    """USD per unit of underlying per 1.00 of vol (divide by 100 for per vol point)."""
    v = np.maximum(s * np.sqrt(np.maximum(tau, 1e-9)), 1e-9)
    d1 = (np.log(F / K) + 0.5 * v * v) / v
    return F * np.exp(-0.5 * d1 * d1) / np.sqrt(2 * np.pi) * np.sqrt(np.maximum(tau, 1e-9))


def strike_for_delta(F, s, tau, delta, is_call):
    """Strike with Black-76 delta `delta` (call delta in (0,1), put delta in (-1,0))."""
    v = s * np.sqrt(tau)
    d1 = ndtri(delta) if is_call else ndtri(delta + 1.0)
    return F * np.exp(-d1 * v + 0.5 * v * v)


# ------------------------------------------------------------------------------------------------ smile
def smile_points(g):
    """One expiry's slice -> dict(atm, c25, p25, c10, p10) implied vols (mark IV, OTM options only)."""
    F = float(g["F"].iloc[0])
    otm = g[(g["is_call"] & (g["strike"] >= F)) | (~g["is_call"] & (g["strike"] < F))]
    out = {"F": F, "days": float(g["days"].iloc[0])}
    if len(otm) < 3:
        return None
    k = np.log(otm["strike"].to_numpy() / F)
    o = np.argsort(k)
    k, iv = k[o], otm["iv"].to_numpy()[o]
    if k[0] > 0 or k[-1] < 0:
        return None
    out["atm"] = float(np.interp(0.0, k, iv))
    calls, puts = g[g["is_call"]].sort_values("delta_bs"), g[~g["is_call"]].sort_values("delta_bs")
    for name, x, target in (("c25", calls, 0.25), ("c10", calls, 0.10), ("p25", puts, -0.25), ("p10", puts, -0.10)):
        d = x["delta_bs"].to_numpy()
        out[name] = float(np.interp(target, d, x["iv"].to_numpy())) if len(d) > 1 and d[0] <= target <= d[-1] \
            else np.nan
    return out


def constant_maturity(points, target_days, key):
    """Interpolate `key` across expiries to `target_days`: ATM in total variance, skew points linearly in time,
    between the nearest expiries on each side within [0.6, 1.5] x target. With an expiry on one side only (XRP
    often lists nothing between the month-end and the quarterly), use the nearest expiry in that window as is."""
    p = sorted((q for q in points if q is not None and np.isfinite(q.get(key, np.nan))), key=lambda q: q["days"])
    p = [q for q in p if 0.6 * target_days <= q["days"] <= 1.5 * target_days]
    if not p:
        return np.nan
    lo = [q for q in p if q["days"] <= target_days]
    hi = [q for q in p if q["days"] >= target_days]
    if not lo or not hi:
        return float(min(p, key=lambda q: abs(np.log(q["days"] / target_days)))[key])
    a, b = lo[-1], hi[0]
    if a["days"] == b["days"]:
        return a[key]
    w = (target_days - a["days"]) / (b["days"] - a["days"])
    if key == "atm":
        var = (1 - w) * a[key] ** 2 * a["days"] + w * b[key] ** 2 * b["days"]
        return float(np.sqrt(var / target_days))
    return float((1 - w) * a[key] + w * b[key])


# ---------------------------------------------------------------------------------------------- realised
def realised_vol(px, t0, t1):
    """Annualised realised vol of hourly log returns of series px over (t0, t1]."""
    r = np.log(px[(px.index >= t0) & (px.index <= t1)]).diff().dropna()
    if len(r) < 12:
        return np.nan
    return float(np.sqrt((r ** 2).mean() * HOURS_YEAR))


# ------------------------------------------------------------------------------------------------- costs
COSTS = {
    # mid + 10 bps of the underlying per leg; touch (ask to buy, bid to sell) + 3 bps. Both capped at 12.5 % of the
    # option price (Deribit's fee cap). The same conventions as optXRP.
    "mid": dict(fill="mid", fee=10e-4),
    "pess": dict(fill="touch", fee=3e-4),
}
FEE_CAP = 0.125


def fill(q, qty, S, costs):
    """Cash paid per unit (positive = pay) to trade qty units at quote row q (needs two-sided bid/ask)."""
    c = COSTS[costs]
    mid = 0.5 * (q["bid"] + q["ask"])
    px = mid if c["fill"] == "mid" else (q["ask"] if qty > 0 else q["bid"])
    fee = min(c["fee"] * S, FEE_CAP * px)
    return qty * px + abs(qty) * fee
