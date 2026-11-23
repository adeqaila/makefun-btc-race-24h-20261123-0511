# BTC Race Bot — btc-race-24h-20261123-0511 (slot 1)

[![make.fun](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![Rank](https://make.fun/badge/btc-race-24h-20261123-0511/adeqaila/makefun-btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![Reward](https://make.fun/badge/btc-race-24h-20261123-0511/adeqaila/makefun-btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)

Bot trading cbBTC/USDC minute by minute on Solana (Orca Whirlpool), for the
make.fun bounty "Race a BTC trading bot live for 24 hours" ($50, top 10 paid).

## Strategy — "Early Dip + Late Rally", trailing-exit edition

Evolved from the grind-max champion `hy-tp50-late100`: the fixed +50 bps
take-profit is replaced by a trailing exit, so a strong trend day is ridden
instead of being sold at +0.50%.

- **Phase 1 (bars 0–59):** buy all-in when close dips ≥ 0.23% vs race OPEN.
  Exit (trailing): arms at +0.50% above fill, sells on a 0.25% give-back
  from the post-entry peak.
- **Phase 2 (bars 1380+, only if Phase 1 never triggered):** buy all-in on a
  dip ≥ 0.50% vs the 60-bar peak close; hold to close.
- **Fallback (bar 1410, only if still flat):** market buy, only if close < OPEN.
- **Late round (after a Phase-1 sale, bars 1380+):** buy once if close dips
  ≥ 1.00% below OPEN and the day high exceeded OPEN +0.50%; hold to close.
- Max 2 filled buys. No stop loss. Deterministic, integer math, stdlib only.

## Gate results (exact replay: 4 bps fee + 2 bps slippage + pool impact)

| Window | Net PnL | Trades | Max DD |
|---|---|---|---|
| dev 0511 (this race, FRESH) | **+$15.73** | 1 buy + 1 sell | 0.53% |
| dev 0828 | +$0.11 | 1 + 1 | 0.47% |
| dev 0603 | +$0.90 | 1 + 1 | 0.45% |
| live 0828 | +$18.87 | 2 + 2 | 0.77% |
| live 0603 | −$2.50 | 1 + 1 | 0.27% |

Worst case −$2.50, 5-window mean +$6.62. Passes the dev gate (net > $0) on
every window; trades in every window (≥1 trade guardrail); max drawdown
≤ 0.93% everywhere (limit 25%).

Rejected during the grind: fixed TP ≥ +0.75% (up to +$34.32 on dev 0511)
scores **−$40.43 on dev 0828** — it never exits on a down day. The fixed
+0.50% champion scores only +$3.02 on dev 0511.

## Files

- `main.py` — the bot (Python 3.13, stdlib only)
- `vendor/makefun_bars.py` — official protocol shim (vendored from the kit)
- `LICENSE` — MIT

## Run

The bot speaks the `agent-fun/bars-replay/v1` protocol on stdin/stdout
(hello + one batch per minute, answers with buy/sell orders). No network,
no wall clock, no files outside the repo; two runs on the same data produce
identical orders (verified: 2-run action logs byte-identical).
