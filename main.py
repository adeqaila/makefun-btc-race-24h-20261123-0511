"""BTC race bot -- btc-race-24h-20261123-0511 (slot 1).

Strategy: "Early Dip + Late Rally", trailing-exit edition.

The bot trades cbBTC/USDC minute by minute on the agent-fun/bars-replay/v1
protocol (hello + one batch per minute, answers with buy/sell orders).
Python 3.13, standard library only, deterministic integer math, no network,
no wall clock, no files outside the repository.

Rules of the strategy
---------------------
* Phase 1 (bars 0-59): buy all-in when the close dips >= 0.23% below the
  race OPEN (the open of bar 0). Exit is a trailing stop: it arms once the
  post-entry peak reaches +0.50% above the buy's fill price, and sells when
  the close gives back 0.25% from that peak.
* Phase 2 (bars 1380+, only if Phase 1 never triggered): buy all-in when
  the close dips >= 0.50% below the peak close of the last 60 bars; hold
  to the close of the window.
* Fallback (bar 1410, only if still flat, i.e. no buy ever filled): market
  buy, but only when the close is below the race OPEN.
* Late round (bars 1380+, after a Phase-1 sale): buy once when the close
  dips >= 1.00% below the race OPEN and the day's high has at some point
  exceeded OPEN + 0.50%; hold to the close of the window.
* At most 2 filled buys. No stop loss.

Fills land one bar after the decision, at the next bar's open, so every
threshold is judged on the close the batch just delivered. All comparisons
are integer cross-multiplications, never floats, so two runs on the same
data answer every batch identically.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10_000

# Largest move the fill may make from the latest close we were sent, in
# basis points. The modelled slippage (2 bps) plus the pool impact of an
# all-in order is far below this, so the cap never binds on this window;
# it only guards against a fill landing absurdly far from the close.
MAX_SLIPPAGE_BPS = 300

# Phase 1: dip vs the race OPEN, in bps, and the last bar it may fire on.
PHASE1_DIP_BPS = 23
PHASE1_LAST_BAR = 59

# Trailing exit: arm level above the fill, in bps, and the give-back from
# the post-entry peak that triggers the sale, in bps.
TRAIL_ARM_BPS = 50
TRAIL_GIVEBACK_BPS = 25

# Late window: first bar of Phase 2 / the late round, and the fallback bar.
LATE_START_BAR = 1380
FALLBACK_BAR = 1410

# Phase 2: dip vs the peak close of the last 60 bars, in bps.
PHASE2_DIP_BPS = 50
PHASE2_PEAK_BARS = 60

# Late round: dip below the race OPEN, in bps, and how far above the race
# OPEN the day's high must have reached, in bps.
LATE_DIP_BPS = 100
DAY_HIGH_BPS = 50

# Hard cap on filled buys over the whole window. A buy counts toward the
# cap only once its fill lands, never when the order is merely sent.
MAX_FILLED_BUYS = 2


class Strategy:
    """The bot's memory: everything it has learned from the batches so far."""

    def __init__(self):
        # The race OPEN: the open of bar 0, learned from the first batch.
        self.race_open = None
        # Highest high of any bar seen so far (the day high).
        self.day_high = None
        # Last PHASE2_PEAK_BARS closes, oldest first, for the Phase-2 peak.
        self.recent_closes = []
        # True once a Phase-1 buy order has been sent.
        self.phase1_triggered = False
        # True once a Phase-1 trailing sale has been sent.
        self.phase1_sold = False
        # True once the one late-round buy has been sent.
        self.late_bought = False
        # Number of buy orders that actually filled.
        self.buys_filled = 0
        # Fill price of the buy currently held, at the symbol's price scale.
        self.fill_price = None
        # Highest close since the current entry (the trailing peak). It
        # starts at the fill price, so the peak is never below the entry.
        self.peak = None
        # True once the peak has reached the arm level above the fill.
        self.armed = False

    def note_bar(self, bar):
        """Fold one fresh bar into the rolling history."""
        close = int(bar["c"])
        high = int(bar["h"])
        if self.race_open is None:
            # Bar 0: its open is the race OPEN every dip is measured from.
            self.race_open = int(bar["o"])
        if self.day_high is None or high > self.day_high:
            self.day_high = high
        self.recent_closes.append(close)
        if len(self.recent_closes) > PHASE2_PEAK_BARS:
            self.recent_closes.pop(0)
        return close

    def note_fills(self, fills):
        """Fold the batch's fills in: count buys, learn the fill price."""
        for fill in fills:
            if fill.get("status") != "filled":
                continue
            if fill.get("symbol") != SYMBOL:
                continue
            if fill.get("side") == "buy":
                self.buys_filled += 1
                self.fill_price = int(fill["price"])
                self.peak = self.fill_price
                self.armed = False

    def dip_vs(self, price, reference, dip_bps):
        """True when price sits at least dip_bps below reference.

        Written as a cross-multiplication so no float ever appears:
        price <= reference * (10000 - dip_bps) / 10000.
        """
        return price * BPS <= reference * (BPS - dip_bps)

    def rise_vs(self, price, reference, rise_bps):
        """True when price sits strictly more than rise_bps above reference."""
        return price * BPS > reference * (BPS + rise_bps)


def on_batch(state, batch):
    """Decide the orders for one batch; None or [] means no orders."""
    bar = None
    for candidate in batch.get("bars", []):
        if candidate.get("symbol") == SYMBOL:
            bar = candidate
            break
    if bar is None:
        # CBBTC missed this minute: nothing to decide on.
        return []

    bot = state.strategy
    close = bot.note_bar(bar)
    bot.note_fills(batch.get("fills", []))
    seq = state.seq

    holding = state.positions.get(SYMBOL)
    if holding is not None and holding.qty > 0:
        # --- Trailing exit on the open position. ---
        if bot.peak is not None:
            if close > bot.peak:
                bot.peak = close
            if bot.fill_price is not None and bot.rise_vs(
                bot.peak, bot.fill_price, TRAIL_ARM_BPS
            ):
                # The peak has cleared +0.50% above the fill: armed.
                bot.armed = True
            if bot.armed and bot.dip_vs(close, bot.peak, TRAIL_GIVEBACK_BPS):
                # Give-back of 0.25% from the peak: sell the whole position.
                bot.phase1_sold = True
                return [
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": holding.qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                ]
        return []

    # Flat: no open position. A buy is possible only while warming-up is
    # over and the filled-buy cap still has room.
    if state.warming_up or bot.buys_filled >= MAX_FILLED_BUYS:
        return []

    order = None
    if not bot.phase1_triggered and seq <= PHASE1_LAST_BAR:
        # --- Phase 1: early dip vs the race OPEN. ---
        if bot.dip_vs(close, bot.race_open, PHASE1_DIP_BPS):
            order = {
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": state.cash,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
            bot.phase1_triggered = True
    elif seq >= LATE_START_BAR:
        if not bot.phase1_triggered:
            # --- Phase 2: dip vs the 60-bar peak close. ---
            peak_close = max(bot.recent_closes)
            if bot.dip_vs(close, peak_close, PHASE2_DIP_BPS):
                order = {
                    "side": "buy",
                    "symbol": SYMBOL,
                    "notional_quote_units": state.cash,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
                bot.phase1_triggered = True
        elif bot.phase1_sold and not bot.late_bought:
            # --- Late round: deep dip after a strong day. ---
            if bot.dip_vs(close, bot.race_open, LATE_DIP_BPS) and bot.rise_vs(
                bot.day_high, bot.race_open, DAY_HIGH_BPS
            ):
                order = {
                    "side": "buy",
                    "symbol": SYMBOL,
                    "notional_quote_units": state.cash,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }
                bot.late_bought = True
        if order is None and seq == FALLBACK_BAR:
            # --- Fallback: still flat at bar 1410, buy if below OPEN. ---
            if (
                not bot.phase1_triggered
                and bot.buys_filled == 0
                and close < bot.race_open
            ):
                order = {
                    "side": "buy",
                    "symbol": SYMBOL,
                    "notional_quote_units": state.cash,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }

    return [order] if order is not None else []


def on_hello(state):
    """Attach the strategy memory to the run's state before batch 0."""
    state.strategy = Strategy()


makefun_bars.run(on_batch, on_hello=on_hello)
