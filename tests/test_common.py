import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xc.common import b76, b76_delta, b76_vega, constant_maturity, fill, strike_for_delta  # noqa: E402
from xc import trades as T  # noqa: E402


def test_put_call_parity():
    F, K, s, tau = 2.0, 2.2, 0.8, 30 / 365.25
    assert abs(b76(F, K, s, tau, True) - b76(F, K, s, tau, False) - (F - K)) < 1e-12


def test_strike_for_delta_roundtrip():
    F, s, tau = 60000.0, 0.5, 14 / 365.25
    for d, c in ((0.25, True), (-0.25, False), (0.5, True)):
        K = strike_for_delta(F, s, tau, d, c)
        assert abs(b76_delta(F, K, s, tau, c) - d) < 1e-9


def test_vega_finite_difference():
    F, K, s, tau = 1.0, 1.1, 0.7, 10 / 365.25
    h = 1e-5
    fd = (b76(F, K, s + h, tau, True) - b76(F, K, s - h, tau, True)) / (2 * h)
    assert abs(fd - b76_vega(F, K, s, tau)) < 1e-7


def test_constant_maturity_total_variance():
    pts = [{"days": 7.0, "atm": 0.6}, {"days": 14.0, "atm": 0.8}]
    v = constant_maturity(pts, 10, "atm")
    assert abs(v ** 2 * 10 - ((4 / 7) * 0.36 * 7 + (3 / 7) * 0.64 * 14)) < 1e-12
    assert constant_maturity(pts, 7, "atm") == 0.6
    assert np.isnan(constant_maturity(pts, 40, "atm"))


def test_fill_conventions():
    q = {"bid": 0.09, "ask": 0.11}
    assert abs(fill(q, 1, 1.0, "mid") - (0.10 + 0.001)) < 1e-12           # mid + 10 bps of the underlying
    assert abs(fill(q, -1, 1.0, "pess") - (-0.09 + 0.0003)) < 1e-12       # sell at the bid + 3 bps
    q = {"bid": 0.0009, "ask": 0.0011}
    assert abs(fill(q, 1, 1.0, "mid") - 0.001 * 1.125) < 1e-12             # fee capped at 12.5 % of the price


class _D:
    """Minimal Data stand-in: one leg held to expiry, settled at the index."""

    def __init__(self, S_exp):
        t0, e = pd.Timestamp("2025-01-03 09:00", tz="UTC"), pd.Timestamp("2025-01-10 08:00", tz="UTC")
        idx = pd.date_range(t0, e, freq="h")
        self.idx = pd.DataFrame({"xrp": np.linspace(2.0, S_exp, len(idx)), "btc": 1e5}, index=idx)
        self.quote = {"xrp": {}, "btc": {}}
        self.t0, self.e = t0, e

    def settle(self, asset, expiry):
        return float(self.idx[asset].asof(expiry))


def test_evaluate_short_call_settlement():
    D = _D(S_exp=2.5)
    row = pd.Series({"bid": 0.09, "ask": 0.11, "S": 2.0, "expiry": D.e, "strike": 2.2, "is_call": True})
    leg = {"asset": "xrp", "expiry": D.e, "strike": 2.2, "is_call": True, "qty": -0.5, "row": row}
    r = T.evaluate(D, D.t0, [leg], "mid")
    fee = min(10e-4 * 2.0, 0.125 * 0.10) * 0.5
    assert abs(r["pnl"] - (0.5 * 0.10 - fee - 0.5 * 0.3)) < 1e-12           # premium - fee - payoff
    assert abs(r["ret_xrp"] - 0.25) < 1e-12
