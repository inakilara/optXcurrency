# Phase 1: XRP vs BTC implied vol, volatility premium and skew

- **Code:** `scripts/build_cache.py` (data), `scripts/iv_study.py build | report`.
- **Outputs:** `reports/phase1/` (`surface_daily.csv`, `cross_daily.csv`, `moments.csv`, `by_year_median.csv`,
  `distributions.png`, `time_series.png`).

## Method

- **Snapshots:** daily at 09:00 UTC, 2024-03-12 → 2026-10-13 (about 945 days).
- **Constant maturities** of 7, 14, 30 and 60 days.
  - ATM IV is interpolated in total variance between the expiries on either side of the target.
  - When XRP lists an expiry on one side only (often nothing between the month-end and the quarterly), the nearest
    expiry within 0.6–1.5 × the target is used.
- **Smile points** come from mark IVs. ATM is interpolated at log-moneyness 0 from OTM options. The 25-delta and
  10-delta points use Black-76 deltas computed from mark IV, so the inverse BTC and linear XRP chains are treated
  the same way.
- **Volatility premium** = ATM IV − realised vol of hourly index returns over the option's life ("next RV").
- **Co-movement:** correlation and beta of XRP on BTC hourly returns over the same window.

## Results (medians, vol points)

| Tenor | XRP IV | BTC IV | IV ratio | RV ratio (next) | XRP premium | BTC premium | XRP − BTC premium | XRP RR25 | BTC RR25 | XRP BF25 | BTC BF25 | corr | beta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7 d | 71.0 | 43.0 | 1.65 | 1.54 | **+11.2** | +3.5 | **+7.7** | −0.3 | −2.1 | 2.7 | 1.1 | 0.75 | 1.13 |
| 14 d | 70.6 | 44.7 | 1.62 | 1.57 | +9.9 | +3.2 | +5.7 | +0.6 | −1.8 | 2.9 | 1.0 | 0.75 | 1.13 |
| 30 d | 70.5 | 46.4 | 1.60 | 1.59 | +2.9 | +3.5 | +1.3 | +2.1 | −1.3 | 3.4 | 1.1 | 0.74 | 1.16 |
| 60 d | 67.0 | 47.8 | 1.56 | 1.59 | −1.8 | +3.0 | −1.1 | +2.2 | −0.3 | 3.1 | 1.0 | 0.73 | 1.18 |

RR25 = 25d call IV − 25d put IV (> 0 = call skew). BF25 = average of the 25d wings − ATM (wing richness).

**Moments (7 d / 30 d):**

| Series | Mean | Std | Skewness | Excess kurtosis | 5th / 95th pct | Share > 0 |
|---|---|---|---|---|---|---|
| XRP premium, 7 d | +3.4 | 31.3 | −1.9 | 4.8 | −62 / +39 | 71 % |
| BTC premium, 7 d | +0.6 | 13.1 | −1.7 | 4.6 | −23 / +16 | 63 % |
| XRP − BTC premium, 7 d | +2.9 | 25.2 | −2.0 | 6.0 | −44 / +32 | 68 % |
| XRP premium, 30 d | −2.4 | 28.2 | −1.7 | 4.3 | −50 / +30 | 54 % |
| BTC premium, 30 d | +1.5 | 9.8 | −0.7 | 0.2 | −19 / +15 | 63 % |
| XRP RR25, 30 d | +2.8 | 6.8 | 2.2 | 11.9 | −6 / +14 | 63 % |
| BTC RR25, 30 d | −1.6 | 3.5 | −0.4 | −0.1 | −8 / +4 | 37 % |
| XRP − BTC RR25, 30 d | +4.5 | 5.2 | 2.9 | 21.1 | −2 / +11 | 90 % |

**By year (7 d medians):**

| Year | XRP premium | BTC premium | Difference | XRP RR25 | BTC RR25 | IV ratio | RV ratio | corr | beta |
|---|---|---|---|---|---|---|---|---|---|
| 2024 | +12.7 | +4.8 | +6.5 | +1.5 | −0.4 | 1.42 | 1.26 | 0.61 | 0.77 |
| 2025 | +12.8 | +3.3 | +10.6 | +0.5 | −2.0 | 1.96 | 1.78 | 0.77 | 1.31 |
| 2026 | +8.4 | +3.1 | +6.4 | −3.1 | −4.4 | 1.46 | 1.35 | 0.82 | 1.05 |

## Findings

1. **XRP's relative premium is a short-tenor phenomenon.**
   - At 7 days, XRP options carry a median premium of +11 vol points over the vol that followed, against +3.5 for
     BTC. The difference is positive on 68 % of days.
   - It fades with tenor. At 30 days the two premiums are level, and at 60 days XRP is cheaper than BTC.
2. **The premium is the median, not the mean.** XRP's premium distribution has a long left tail (5th percentile
   −62 points at 7 days), from rallies such as November 2024. Its mean (+3.4 at 7 d) is much smaller than its median.
   That tail is what a short-XRP-vol position pays for.
3. **In ratio terms XRP is fairly priced.** The XRP/BTC IV ratio (1.6–1.65) is close to the ratio of the realised
   vols that followed (1.54–1.59). The extra premium is a few vol points on top of a ratio that is mostly justified.
4. **Skew: XRP calls are rich relative to BTC calls.**
   - BTC has put skew at every tenor (RR25 −0.3 to −2.1).
   - XRP is about flat at 7 days and has call skew beyond 14 days (+2 points at 30–60 d).
   - The XRP − BTC risk reversal difference is positive on 90 % of days at 30 d. It has a fat right tail (excess
     kurtosis 21), driven by the late-2024 rally.
   - Both skews moved toward puts in 2026.
5. **XRP's wings are rich.** Its 25d butterfly is about 3 points, against about 1 for BTC: XRP prices its tails, on
   both sides, at a premium.
6. **Co-movement is high but not tight.** Correlation of hourly returns is 0.70–0.75 and beta about 1.15. It ranged
   from 0.6 / 0.8 (2024) to 0.8 / 1.05 (2026). A linear hedge with BTC can remove at most about half of XRP's
   variance (R² ≈ ρ²), less for convex payoffs.
