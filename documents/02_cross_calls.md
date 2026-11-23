# Phase 2: short XRP call, long BTC call

- **Code:** `xc/trades.py` (trade engine), `scripts/cross_calls.py run | report`.
- **Outputs:** `reports/phase2/` (`summary.csv`, `by_year.csv`; per-trade files are git-ignored).

## Method

- **Entries:** every day at 09:00 UTC, 2024-03 → 2026-10 (730–920 trades per configuration, overlapping).
- **Expiry:** one expiry listed on both assets, closest to the target tenor (7, 14, 30 days).
- **Strikes:** K = F × exp(m × σ_RV × √τ), with σ_RV each asset's trailing 30-day realised vol and m = 0, 0.5, 1,
  1.5. So the BTC strike is closer in percentage terms by the ratio of the two realised vols. An alternative uses
  25-delta calls on both.
- **Size:** short 1 USD of XRP notional; P&L in % of that notional.
- **BTC leg sizing:**
  - **beta:** BTC dollar delta = beta × XRP dollar delta (trailing 30-day hourly beta);
  - **dollar:** equal dollar deltas;
  - **vega:** equal vega;
  - **none:** the short XRP call alone, for reference.
- **Exit:** held to expiry, settled at the index (an inverse BTC option pays max(S − K, 0) USD when converted at
  settlement).
- **Costs:**
  - **mid:** mid + 10 bps of the underlying per leg;
  - **pessimistic:** bid/ask + 3 bps;
  - both fees capped at 12.5 % of the option price.
- **Drift split.** P&L is regressed on XRP's move relative to BTC (rel = XRP return − beta × BTC return, with a
  squared term). The drift part, slope × average rel, is what the trade earned or lost from XRP out- or
  under-performing BTC on average. Over this window XRP outperformed BTC, which hurts short-XRP-call structures.

## Results

**Mean P&L per trade, % of XRP notional, mid costs, dollar-delta hedge** (pessimistic is 0.05–0.25 lower):

| Tenor | m = 0 (ATM) | m = 0.5 | m = 1 | m = 1.5 | 25-delta |
|---|---|---|---|---|---|
| 7 d | −0.46 | −0.74 | −1.00 | −0.86 | −0.84 |
| 14 d | −1.07 | −1.42 | −1.82 | −1.74 | −1.58 |
| 30 d | −5.50 | −6.92 | −7.09 | −6.54 | −6.67 |

**7-day ATM by hedge rule (mid):**

| Hedge | Mean | Median | Hit rate | Std | 5th pct | Worst | Variance removed vs naked | Corr. with XRP return |
|---|---|---|---|---|---|---|---|---|
| none (naked short XRP call) | −0.26 | +2.88 | 75 % | 11.0 | −19.7 | −100 | – | −0.91 |
| beta | −0.67 | +0.94 | 74 % | 9.5 | −12.6 | −93 | 25 % | −0.81 |
| dollar | −0.46 | +1.31 | 77 % | 9.3 | −12.0 | −90 | 29 % | −0.83 |
| vega | −0.44 | +1.34 | 76 % | 9.3 | −12.3 | −91 | 28 % | −0.83 |

**Robustness (dollar hedge, ATM, mid):**

| | All | Without Q4-2024 entries | Mar 2024–Jun 2025 | Jul 2025–Oct 2026 | Drift-adjusted |
|---|---|---|---|---|---|
| 7 d | −0.46 | +0.54 (t 0.9) | −1.19 | +0.25 (t 0.4) | +0.07 |
| 30 d | −5.50 | +2.39 (t 1.2) | −13.1 | +1.81 (t 1.1) | −0.43 |

The five worst 7-day trades were all entered on 12–26 November 2024, losing 55–90 % of notional each.

## Findings

1. **Short XRP call / long BTC call loses money in every configuration** (60 tested), at mid and at pessimistic
   costs. Losses grow with tenor and with distance from the money.
2. **The BTC leg does not cancel the market risk.**
   - It removes only 15–30 % of the variance of the naked short XRP call.
   - The P&L still correlates −0.8 to −0.95 with XRP's own return.
   - The reason: XRP's large up-moves are its own, not BTC's. From 5 November to 3 December 2024 XRP rose +442 %
     and BTC +41 %; over the life of the worst 7-day trades (12–22 November) XRP doubled while BTC rose 11 %. The
     BTC calls paid a fraction of the XRP call losses.
   - Beta, dollar and vega sizing make little difference. Beta sizing is slightly worse on average.
3. **The losses come from one episode, but the edge outside it is small.**
   - Without the entries of Q4 2024, the ATM structures are positive: +0.5 % per 7-day trade, +2.4 % per 30-day
     trade. That is not significant (t ≈ 1).
   - Removing XRP's average outperformance leaves the 7-day ATM version at about zero (+0.07 %) and every OTM or
     longer version negative. The OTM calls are where XRP's call skew is, and they lose even after the drift is
     removed: XRP's rallies justified the skew.
4. **Verdict:** the simplest cross structure is not feasible as a market-neutral premium trade. It is a short
   position in XRP's idiosyncratic upside, and it pays the full price when that upside arrives.
