"""Tek bir profil (sembol+zaman dilimi) icin sanal (paper) islem adimi.

Her calistirmada: guncel mumlar cekilir, indikatorler + confluence
sinyalleri hesaplanir, bir onceki calistirmadan beri kapanmis olan yeni
mumlar sirayla islenir (ATR bazli stop/target/trailing ile ayni backtest
mantigi kullanilarak), sanal hesap durumu (bakiye, acik pozisyon, islem
gecmisi) guncellenip diske kaydedilir. Gercek para/borsa hesabi
kullanilmaz.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from src.data_fetcher import fetch_ohlcv
from src.indicators import add_all_indicators
from src.strategy import StrategyParams, build_signals

from .config import Profile
from .state_store import load_state, save_state

TIMEFRAME_HOURS = {
    "1m": 1 / 60, "3m": 3 / 60, "5m": 5 / 60, "15m": 15 / 60, "30m": 0.5,
    "1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12,
    "1d": 24, "1w": 168,
}


def _fetch_window(symbol: str, timeframe: str, lookback_candles: int) -> pd.DataFrame:
    hours_per_candle = TIMEFRAME_HOURS[timeframe.lower()]
    lookback_days = int(hours_per_candle * lookback_candles / 24) + 3
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=lookback_days)
    df = fetch_ohlcv(symbol, timeframe, start.isoformat(), end.isoformat(), verbose=False)
    # Son mum genellikle henuz kapanmamis (olusum halinde) oldugu icin
    # islem kararlarinda kullanilmaz.
    return df.iloc[:-1].reset_index(drop=True)


def _close_position(position: dict, exit_price: float, exit_time, reason: str, fee_pct: float, balance: float) -> tuple[float, dict]:
    direction = position["direction"]
    entry_price = position["entry_price"]
    gross_pnl_pct = direction * (exit_price / entry_price - 1.0)
    net_pnl_pct = gross_pnl_pct - 2 * (fee_pct / 100.0)
    new_balance = balance * (1.0 + net_pnl_pct)
    trade = {
        "direction": "long" if direction == 1 else "short",
        "entry_time": position["entry_time"],
        "exit_time": str(exit_time),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_reason": reason,
        "pnl_pct": net_pnl_pct * 100,
        "pnl_usdt": new_balance - balance,
    }
    return new_balance, trade


def _maybe_open_position(row, params: StrategyParams) -> dict | None:
    if row.signal == 1:
        direction = 1
    elif row.signal == -1 and params.allow_short:
        direction = -1
    else:
        return None
    entry_price = row.close
    atr = row.atr
    if direction == 1:
        stop = entry_price - params.atr_stop_mult * atr
        target = entry_price + params.atr_target_mult * atr
        trailing_extreme = row.high
    else:
        stop = entry_price + params.atr_stop_mult * atr
        target = entry_price - params.atr_target_mult * atr
        trailing_extreme = row.low
    return {
        "direction": direction,
        "entry_price": entry_price,
        "entry_time": str(row.timestamp),
        "atr_at_entry": atr,
        "stop_price": stop,
        "target_price": target,
        "trailing_extreme": trailing_extreme,
    }


def _process_bar(row, position: dict | None, balance: float, params: StrategyParams, fee_pct: float) -> tuple[float, dict | None, dict | None]:
    """Tek bir kapanmis mumu isler. (yeni_bakiye, yeni_pozisyon, kapanan_islem) dondurur."""
    closed_trade = None

    if position is not None:
        direction = position["direction"]
        atr_entry = position["atr_at_entry"]
        if direction == 1:
            position["trailing_extreme"] = max(position["trailing_extreme"], row.high)
            trail_stop = position["trailing_extreme"] - params.trailing_atr_mult * atr_entry
            effective_stop = max(position["stop_price"], trail_stop) if params.use_trailing_stop else position["stop_price"]
            if row.low <= effective_stop:
                reason = "stop_loss" if effective_stop == position["stop_price"] else "trailing_stop"
                balance, closed_trade = _close_position(position, effective_stop, row.timestamp, reason, fee_pct, balance)
                position = None
            elif row.high >= position["target_price"]:
                balance, closed_trade = _close_position(position, position["target_price"], row.timestamp, "take_profit", fee_pct, balance)
                position = None
            elif row.signal == -1:
                balance, closed_trade = _close_position(position, row.close, row.timestamp, "opposite_signal", fee_pct, balance)
                position = None
        else:
            position["trailing_extreme"] = min(position["trailing_extreme"], row.low)
            trail_stop = position["trailing_extreme"] + params.trailing_atr_mult * atr_entry
            effective_stop = min(position["stop_price"], trail_stop) if params.use_trailing_stop else position["stop_price"]
            if row.high >= effective_stop:
                reason = "stop_loss" if effective_stop == position["stop_price"] else "trailing_stop"
                balance, closed_trade = _close_position(position, effective_stop, row.timestamp, reason, fee_pct, balance)
                position = None
            elif row.low <= position["target_price"]:
                balance, closed_trade = _close_position(position, position["target_price"], row.timestamp, "take_profit", fee_pct, balance)
                position = None
            elif row.signal == 1:
                balance, closed_trade = _close_position(position, row.close, row.timestamp, "opposite_signal", fee_pct, balance)
                position = None

    if position is None and not pd.isna(row.atr) and row.atr > 0:
        position = _maybe_open_position(row, params)

    return balance, position, closed_trade


def run_profile(
    profile: Profile,
    params: StrategyParams,
    state_dir: str,
    initial_balance: float,
    fee_pct: float,
    lookback_candles: int,
    max_equity_points: int,
) -> dict[str, Any]:
    state = load_state(state_dir, profile.id, initial_balance)
    df = _fetch_window(profile.symbol, profile.timeframe, lookback_candles)
    df = add_all_indicators(df)
    df = df.dropna(subset=["ema_200", "atr"]).reset_index(drop=True)
    signaled = build_signals(df, params)

    last_ts = state["last_processed_ts"]
    if last_ts is None:
        # Ilk calistirma: gecmisi "canliymis gibi" islemek yaniltici olur,
        # sadece baslangic noktasini isaretleyip bir sonraki yeni mumu bekle.
        last_row = signaled.iloc[-1]
        state["last_processed_ts"] = str(last_row["timestamp"])
        state["equity_curve"].append({"t": str(last_row["timestamp"]), "equity": state["balance"]})
        state["last_price"] = float(last_row["close"])
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state_dir, profile.id, state)
        return state

    new_rows = signaled[signaled["timestamp"] > pd.Timestamp(last_ts)]
    balance = state["balance"]
    position = state["position"]

    for row in new_rows.itertuples():
        balance, position, closed_trade = _process_bar(row, position, balance, params, fee_pct)
        state["equity_curve"].append({"t": str(row.timestamp), "equity": balance})
        if closed_trade is not None:
            closed_trade["symbol"] = profile.symbol
            closed_trade["timeframe"] = profile.timeframe
            state["trades"].append(closed_trade)
        state["last_processed_ts"] = str(row.timestamp)

    state["balance"] = balance
    state["position"] = position
    state["equity_curve"] = state["equity_curve"][-max_equity_points:]
    if len(df) > 0:
        state["last_price"] = float(df["close"].iloc[-1])
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_state(state_dir, profile.id, state)
    return state
