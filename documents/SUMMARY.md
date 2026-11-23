# optXcurrency: summary

**Question.** Can option structures on Deribit cancel market risk by hedging with options on a different currency:
short the currency with the higher implied-vol premium (XRP), long the one with the lower premium (BTC)?

**Data.** Deribit XRP_USDC (linear) and BTC (inverse) option chains, daily at 09:00 UTC, 2024-03-12 →
2026-10-13. These are the only two option chains available, so the pair is XRP against BTC over 2.6 years. Every
structure is entered every day and held to its (front) expiry, at mid + 10 bps and at bid/ask + 3 bps.

## Answer

**Mostly no.** Cross-currency hedging cancels XRP's downside but not its upside, so only put structures work.

1. **The premium exists, but only at short tenors** ([01](01_iv_premium_skew.md)).
   - At 7 days XRP options carry a median premium of +11 vol points over the vol that followed, against +3.5 for
     BTC. At 30 days the two are level, and at 60 days XRP is cheaper.
   - XRP calls are rich relative to BTC calls: the XRP − BTC risk-reversal difference is +2 to +4.5 points.
   - XRP's premium has a long left tail (5th percentile −62 points at 7 d), from its rallies.
2. **The hedge is asymmetric.** Correlation of returns is 0.70–0.75, but XRP's big rallies are its own (November
   2024: XRP +442 %, BTC +41 %), while its sell-offs are shared with BTC.
   - A long BTC put removes about **60 %** of a short XRP put's variance, at almost no cost.
   - A long BTC call removes only **15–30 %** of a short XRP call's variance.
3. **Short XRP call / long BTC call (the simplest structure) loses** in all 60 configurations tested: 3 tenors,
   5 strike rules and 4 hedge sizings ([02](02_cross_calls.md)). It is a short position in XRP's idiosyncratic
   upside. Outside Q4 2024 it is about break-even.
4. **Short XRP put / long BTC put is the one feasible cross structure** ([03](03_other_structures.md)).
   - At bid/ask it earns **+0.4–1.3 % of XRP notional per 14–30 day trade** (about 9–17 %/yr of notional).
   - Worst trade −8 to −15 %, 5th percentile −0.4 to −4 %.
   - Positive in 2024, 2025 and 2026, in both halves of the sample, and without Q4 2024.
   - t ≈ 1.7–2.2, among about 100 configurations tested.
   - The return is XRP's put premium; the BTC put leg is the risk reducer.
5. **Delta-neutral vol trades across currencies lose.** Hedged straddles, strangles, vega-matched diagonals and
   the skew trade (short XRP risk reversal / long BTC risk reversal) all lose, the skew trade worst.
6. **XRP's own calendar is the strongest premium, but costs eat it.** Short 7–14 day / long 30–60 day XRP straddles
   earn +1.4–2.5 % per trade at mid (t up to 4.4). At bid/ask that falls to +0.4–0.6 %, because XRP back months are
   illiquid. BTC calendars lose, so the cross calendar adds nothing.

## Candidate to pursue: the cross-put ([04](04_cross_put_portfolio.md))

**Every Friday, sell a 30-day XRP put 0.5σ below the forward and buy ATM BTC puts sized to beta × the XRP put's
dollar delta; about 1 × equity of XRP notional open (weekly tranches), held to expiry.**

| Size | Costs | CAGR | Vol | Max DD | Sharpe | Worst month | Peak margin | Sharpe in / out of sample |
|---|---|---|---|---|---|---|---|---|
| 1 × | bid/ask | 16.6 % | 13.7 % | −8.7 % | 1.19 | −2.4 % | 0.36 | 1.23 / 1.14 |
| 1 × | mid | 17.8 % | 13.7 % | −8.5 % | 1.26 | −2.5 % | 0.36 | 1.35 / 1.17 |
| 2 × | bid/ask | 34.4 % | 27.4 % | −16.9 % | 1.22 | −4.8 % | 0.73 | 1.27 / 1.16 |

- Against the naked short XRP put (18.0 %, MDD −16.2 %, Sharpe 0.87), the BTC hedge halves the drawdown and cuts
  the worst month from −15 % to −2.4 %.
- Iterating helped: 30-day over 14-day, 0.5σ strikes, a full beta hedge and an ATM BTC put. Premium gates and
  further-OTM BTC puts made it worse.
- The configuration chosen on the first half alone (hedge 0.5 ×) had an out-of-sample Sharpe of 0.58, so a
  realistic expectation is a Sharpe between about 0.6 and 1.2.

- Fits the earlier optXRP finding that XRP's premium sits at the money and on the put side.
- **Open questions:**
  - real fills on XRP puts;
  - margin: separate USDC and BTC collateral on Deribit;
  - whether XRP's outperformance of BTC, about a quarter to half of the return, persists;
  - out-of-sample behaviour in an XRP crash that BTC does not follow.
- **Possible next steps:**
  - combine the cross put with optXRP's delta-hedged straddle (the put structure's risk is mostly orthogonal);
  - work XRP calendars with limit orders on the back leg;
  - add ETH or SOL chains for a pair with a tighter correlation.

## Limits

- **Short sample:** 2.6 years, one dominant event (Q4 2024).
- **Many configurations tested:** about 200 in total (60 in phase 2, 45 in phases 3–4, about 90 in phase 5). Treat t-values of about 2 as suggestive, not proof.
- **Daily entries overlap,** so t-statistics use the effective number of independent trades (trades × 1 / days
  held).
- **Not modelled:**
  - intra-trade marks and margin calls;
  - BTC premium paid in BTC (USD value moves with BTC before expiry);
  - Deribit's settlement TWAP (the hourly index at 08:00 is used);
  - delivery fees.
