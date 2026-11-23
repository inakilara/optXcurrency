# optXcurrency: cross-currency option structures on Deribit (XRP vs BTC)

| Document | Content |
|---|---|
| [SUMMARY.md](SUMMARY.md) | **the answer, the candidate structure, limits (start here)** |
| [00_brief.md](00_brief.md) | the research brief |
| [01_iv_premium_skew.md](01_iv_premium_skew.md) | phase 1: IV, volatility premium, skew and co-movement of XRP and BTC |
| [02_cross_calls.md](02_cross_calls.md) | phase 2: short XRP call / long BTC call by tenor, moneyness and hedge sizing |
| [03_other_structures.md](03_other_structures.md) | phases 3–4: puts, straddles, strangles, call spreads, risk reversals, diagonals, calendars; robustness |
| [04_cross_put_portfolio.md](04_cross_put_portfolio.md) | phase 5: the cross-put as a portfolio (CAGR, vol, MDD, Sharpe), tenor / distance / hedge / sizing iterations |

**Status (2026-11-23):** phases 1–5 run.

## Reproduce

```
.venv\Scripts\python.exe scripts\build_cache.py               # slim daily chains + hourly index -> data/cache (git-ignored)
.venv\Scripts\python.exe scripts\iv_study.py build            # phase 1, then: iv_study.py report
.venv\Scripts\python.exe scripts\cross_calls.py run           # phase 2 (about 10 min), then: cross_calls.py report
.venv\Scripts\python.exe scripts\other_structures.py run      # phases 3-4 (about 15 min), then: other_structures.py report
.venv\Scripts\python.exe scripts\robustness.py                # robustness of the winners, cumulative P&L chart
.venv\Scripts\python.exe scripts\cross_put.py grid             # phase 5 (about 8 min), then: cross_put.py variants, cross_put.py final
.venv\Scripts\python.exe -m pytest tests
```

Run one study at a time: each loads both chains into memory.
