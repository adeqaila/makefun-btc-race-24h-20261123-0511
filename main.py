"""Early Dip + Late Rally, trailing-exit edition (btc-race-24h-20261123-0511, slot 1).

Evolved from the grind-max champion hy-tp50-late100 ("Early Dip + Late Rally"):
the fixed +50 bps take-profit is replaced by a trailing exit, so a strong
trend day is ridden instead of sold at +0.50%.

Phase 1 (bars 0-59): buy all-in on dip >= 23 bps vs race OPEN.
  Exit (trailing): arms once close reaches +50 bps above fill, then sells
  on a 25 bps give-back from the post-entry peak.
Phase 2 (bars 1380+, only if Phase 1 never triggered): buy all-in on dip
  >= 50 bps vs the 60-bar peak close; hold to close.
Fallback (bar 1410, only if still flat): market buy, only if close < OPEN.
Late round (after a Phase-1 sale, bars 1380+): buy once if close dips
  >= 100 bps below OPEN and the day high exceeded OPEN +50 bps; hold to close.
Max 2 filled buys. No stop loss. Deterministic, integer math, stdlib only.

Gate results (exact replay, fee 4 bps + slippage 2 bps + pool impact):
  dev 0511 (this race, FRESH): +$15.73, 1 buy + 1 sell, max DD 0.53%
  dev 0828: +$0.11 | dev 0603: +$0.90 | live 0828: +$18.87 (2 rounds)
  live 0603: -$2.50 | worst-case -$2.50, 5-window mean +$6.62.
  (Fixed-TP +0.50% champion on dev 0511: +$3.02. Fixed TP >= +0.75% scores
  -$40.43 on dev 0828 and was rejected: it never exits on a down day.)
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
)

import makefun_bars

SYMBOL = "CBBTC"

PHASE1_END = 59
DIP1_NUM = 9977
TAKE_PROFIT_NUM = 10050
PHASE1_TRAIL_BPS = 25
PHASE2_START = 1380
DIP2_NUM = 9950
FALLBACK_BAR = 1410
FALLBACK_COND = 1
LATE_DIP_OPEN_NUM = 9900
LATE_HIGH_NUM = 10050
LAST_SEQ = 1439

SLIPPAGE_BPS = 300
MIN_ORDER = 1_000_000

_open0 = None
_day_high = 0
_closes = []
_buy_pending = False
_pending_phase1 = False
_pending_late = False
_sell_pending = False
_buy_price = None
_peak1 = None
_armed1 = False
_phase1 = False
_holding = False
_sold = False
_late_bought = False


def _reset():
    global _open0, _day_high, _closes, _buy_pending, _pending_phase1
    global _pending_late, _sell_pending, _buy_price, _peak1, _armed1
    global _phase1, _holding, _sold, _late_bought
    _open0 = None
    _day_high = 0
    _closes = []
    _buy_pending = False
    _pending_phase1 = False
    _pending_late = False
    _sell_pending = False
    _buy_price = None
    _peak1 = None
    _armed1 = False
    _phase1 = False
    _holding = False
    _sold = False
    _late_bought = False


def on_hello(state):
    _reset()


def _buy_all_in(state, phase1, late=False):
    global _buy_pending, _pending_phase1, _pending_late
    size = state.cash
    room = state.weight_room(SYMBOL)
    if size > room:
        size = room
    if size < MIN_ORDER:
        return []
    _buy_pending = True
    _pending_phase1 = phase1
    _pending_late = late
    return [
        {
            "side": "buy",
            "symbol": SYMBOL,
            "notional_quote_units": size,
            "max_slippage_bps": SLIPPAGE_BPS,
        }
    ]


def _sell_all(state):
    global _sell_pending
    holding = state.positions.get(SYMBOL)
    if holding is None or holding.qty <= 0:
        return []
    _sell_pending = True
    return [
        {
            "side": "sell",
            "symbol": SYMBOL,
            "qty": holding.qty,
            "max_slippage_bps": SLIPPAGE_BPS,
        }
    ]


def _bar_for(batch):
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            return b
    return None


def on_batch(state, batch):
    global _open0, _day_high, _closes, _buy_pending, _pending_phase1
    global _pending_late, _sell_pending, _buy_price, _peak1, _armed1
    global _phase1, _holding, _sold, _late_bought
    bar = _bar_for(batch)
    if bar is None:
        return []

    if _open0 is None:
        _open0 = int(bar["o"])
    _day_high = max(_day_high, int(bar["h"]))

    for f in batch.get("fills", []):
        if f.get("symbol") != SYMBOL:
            continue
        side = f.get("side")
        status = f.get("status")
        if side == "buy" and status == "filled":
            _buy_price = int(f["price"])
            _peak1 = _buy_price
            _armed1 = False
            _phase1 = _pending_phase1
            _holding = True
            _buy_pending = False
            if _pending_late:
                _late_bought = True
        elif side == "buy" and status == "rejected":
            _buy_pending = False
        elif side == "sell" and status == "filled":
            _sold = True
            _holding = False
            _sell_pending = False
        elif side == "sell" and status == "rejected":
            _sell_pending = False

    if state.warming_up:
        return []

    if _buy_pending or _sell_pending:
        return []

    close = int(bar["c"])
    seq = state.seq
    _closes.append(close)

    if _holding:
        if _phase1 and _buy_price is not None:
            if close > _peak1:
                _peak1 = close
            if PHASE1_TRAIL_BPS:
                if close * 10000 >= _buy_price * 10050:
                    _armed1 = True
                if _armed1 and close * 10000 <= _peak1 * (10000 - PHASE1_TRAIL_BPS):
                    return _sell_all(state)
            else:
                if close * 10000 >= _buy_price * TAKE_PROFIT_NUM:
                    return _sell_all(state)
        return []

    if seq >= LAST_SEQ:
        return []
    if _sold:
        # late round only: bars 1380+, dip vs OPEN + day-high condition
        if (not _late_bought and LATE_DIP_OPEN_NUM and seq >= PHASE2_START
                and close * 10000 <= _open0 * LATE_DIP_OPEN_NUM
                and _day_high * 10000 > _open0 * LATE_HIGH_NUM):
            return _buy_all_in(state, phase1=False, late=True)
        return []
    if seq <= PHASE1_END:
        if close * 10000 <= _open0 * DIP1_NUM:
            return _buy_all_in(state, phase1=True)
        return []
    if seq >= FALLBACK_BAR:
        if FALLBACK_COND == 1 and close >= _open0:
            return []
        if FALLBACK_COND == 2:
            peak = max(_closes[-60:])
            if close * 10000 > peak * 9950:
                return []
        return _buy_all_in(state, phase1=False)
    if seq >= PHASE2_START:
        peak = max(_closes[-61:])
        if close * 10000 <= peak * DIP2_NUM:
            return _buy_all_in(state, phase1=False)
        return []
    return []


makefun_bars.run(on_batch, on_hello=on_hello)
