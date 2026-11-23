"""Build slim daily option panels for XRP and BTC, plus both hourly indices, from the shared read-only chains.

    python scripts/build_cache.py   -> data/cache/chain_xrp.parquet, chain_btc.parquet, index_1h.parquet (git-ignored)

Window: the XRP chain's span, 2024-03-12 -> 2026-10-13 (the BTC chain covers it).
Snapshots: 09:00 UTC each day (one hour after Deribit's 08:00 settlement): entries, daily marks and exits.
Expiries up to 120 days. All prices in USD per 1 unit of the underlying:
    XRP_USDC  linear options, already USDC per XRP;
    BTC       inverse options, quoted in BTC: price x index -> USD per BTC. At expiry an inverse call pays
              max(S - K, 0) / S BTC = max(S - K, 0) USD, so in USD both chains have the same linear payoff.
Columns: t, expiry, strike, is_call, bid, ask, mark (USD; bid/ask 0 = no quote), iv, bid_iv, ask_iv (decimal),
delta (exchange), F (underlyingPrice), S (index).
XRP rows carried forward from an earlier snapshot are dropped; BTC_USDC linear options (from 2026-10) are excluded.
index_1h: hourly index of both (columns xrp, btc), for realised vol and settlement.
"""
import os

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

XRP = r"C:\ClaudeSandbox\shared-data\option-chain-xrp\option_chains_hourly_xrp"
BTC = r"C:\ClaudeSandbox\shared-data\option-chain\option_chain_hourly.parquet"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
START, END = pd.Timestamp("2024-03-12", tz="UTC"), pd.Timestamp("2026-10-14", tz="UTC")
HOUR, MAX_DAYS = 9, 120
OUT_COLS = ["t", "expiry", "strike", "is_call", "bid", "ask", "mark", "iv", "bid_iv", "ask_iv", "delta", "F", "S"]


def slim(t, expiry, strike, put_call, bid, ask, mark, iv, biv, aiv, delta, F, S):
    df = pd.DataFrame({"t": t, "expiry": expiry, "strike": strike.astype(float),
                       "is_call": put_call.astype(str).str.upper().str.startswith("C"),
                       "bid": bid, "ask": ask, "mark": mark, "iv": iv / 100, "bid_iv": biv / 100, "ask_iv": aiv / 100,
                       "delta": delta, "F": F, "S": S})
    days = (df["expiry"] - df["t"]).dt.total_seconds() / 86400
    return df[(days > 0) & (days <= MAX_DAYS) & (df["iv"] > 0) & (df["iv"] < 5)]


def build_xrp():
    cols = ["timestamp", "expirationTimestamp", "strike", "putCall", "bid", "ask", "markPrice", "markIv", "bidIv",
            "askIv", "delta", "underlyingPrice", "indexPrice", "isCarryForward", "multiplier"]
    d = ds.dataset(XRP, format="parquet").to_table(columns=cols).to_pandas()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    d["expirationTimestamp"] = pd.to_datetime(d["expirationTimestamp"], utc=True)
    assert (d["multiplier"] == 1000).all()
    idx = d.drop_duplicates("timestamp").set_index("timestamp")["indexPrice"].sort_index()
    s = d[(d["timestamp"].dt.hour == HOUR) & ~d["isCarryForward"]]
    out = slim(s["timestamp"], s["expirationTimestamp"], s["strike"], s["putCall"], s["bid"], s["ask"],
               s["markPrice"], s["markIv"], s["bidIv"], s["askIv"], s["delta"], s["underlyingPrice"],
               s["indexPrice"])
    return out, idx


def build_btc():
    f = pq.ParquetFile(BTC)
    cols = ["timestamp", "expirationTimestamp", "strike", "putCall", "bid", "ask", "markPrice", "markIv", "bidIv",
            "askIv", "delta", "underlyingPrice", "indexPrice", "instrument"]
    snaps, idxs = [], []
    for i in range(f.num_row_groups):
        t = f.read_row_group(i, columns=cols).to_pandas(ignore_metadata=True)  # index fields as plain columns
        t = t[(t["timestamp"] >= START) & (t["timestamp"] < END)]
        if t.empty:
            continue
        t = t[t["instrument"].str.startswith("BTC-")]
        idxs.append(t.drop_duplicates("timestamp").set_index("timestamp")["indexPrice"])
        s = t[t["timestamp"].dt.hour == HOUR]
        S = s["indexPrice"]
        snaps.append(slim(s["timestamp"], s["expirationTimestamp"], s["strike"], s["putCall"], s["bid"] * S,
                          s["ask"] * S, s["markPrice"] * S, s["markIv"], s["bidIv"], s["askIv"], s["delta"],
                          s["underlyingPrice"], S))
        print("btc row group", i, len(snaps[-1]), flush=True)
    idx = pd.concat(idxs)
    return pd.concat(snaps, ignore_index=True), idx[~idx.index.duplicated()].sort_index()


def main():
    os.makedirs(CACHE, exist_ok=True)
    x, xi = build_xrp()
    b, bi = build_btc()
    for name, df in (("xrp", x), ("btc", b)):
        df = df[OUT_COLS].sort_values(["t", "expiry", "strike", "is_call"]).reset_index(drop=True)
        df.to_parquet(os.path.join(CACHE, "chain_%s.parquet" % name), row_group_size=200_000)
        two = ((df["bid"] > 0) & (df["ask"] > 0)).mean()
        print("%s: %d rows, %d days, %.0f%% two-sided" % (name, len(df), df["t"].nunique(), 100 * two))
    idx = pd.DataFrame({"xrp": xi, "btc": bi})
    idx.index = pd.DatetimeIndex(idx.index).tz_convert("UTC")
    idx = idx[(idx.index >= START) & (idx.index < END)]
    idx.to_parquet(os.path.join(CACHE, "index_1h.parquet"))
    print("index: %d hours, missing xrp %d, btc %d" % (len(idx), idx["xrp"].isna().sum(), idx["btc"].isna().sum()))


if __name__ == "__main__":
    main()
