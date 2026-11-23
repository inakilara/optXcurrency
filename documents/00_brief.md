# Research brief (2026-11-23)

Study the feasibility of option structures on Deribit where the market risk is approximately cancelled by
hedging with options on a different currency. The idea: **go short the currencies with the higher implied
volatility premium and long the ones with the lower premium**, for example short XRP linear options and long BTC
options.

1. Test the distributions of option IV on Deribit: what the volatility premium and the skew have been historically.
2. Test the simplest structure. XRP has call skew, so sell a call on XRP and buy a call on BTC.
   - Test different tenors and different moneyness, measuring strike distance with each asset's realised vol (so
     the ratio of the two realised vols sets the relative strike distance).
3. Propose and test other vertical and diagonal cross-currency structures.
4. Test calendar structures as well.

**Data available** (shared, read-only): Deribit XRP_USDC option chain (hourly, 2024-03-12 → 2026-10-13) and
Deribit BTC option chain (hourly, 2019-11 → 2026-10). No other currency's option chain is available, so the pair is
XRP against BTC over their common window.
