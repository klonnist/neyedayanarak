"""Price action + RSI + hacim katmanlarini birlestiren confluence stratejisi.

Her katman bagimsiz olarak -1 (bearish) / 0 (notr) / +1 (bullish) oyu verir.
Nihai sinyal, en az ``min_confluence`` katmanin ayni yonde oy vermesiyle
uretilir.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1) Price action: mum formasyonlari, breakout, trend filtresi
# ---------------------------------------------------------------------------

def _body(df: pd.DataFrame) -> pd.Series:
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    return (df["high"] - df["low"]).replace(0, np.nan)


def detect_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = _body(df)
    rng = _range(df)
    upper_wick = h - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - l

    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_body = body.shift(1)

    # Doji: govde, toplam menzilin cok kucuk bir kismi
    out["doji"] = body <= 0.1 * rng

    # Bullish / bearish engulfing
    out["bullish_engulfing"] = (
        (c > o) & (prev_c < prev_o) & (c >= prev_o) & (o <= prev_c)
    )
    out["bearish_engulfing"] = (
        (c < o) & (prev_c > prev_o) & (o >= prev_c) & (c <= prev_o)
    )

    # Hammer (asagi golgeli, govde ustte) / Shooting star (yukari golgeli, govde altta)
    out["hammer"] = (lower_wick >= 2 * body) & (upper_wick <= 0.3 * body.replace(0, np.nan)) & (body > 0)
    out["shooting_star"] = (upper_wick >= 2 * body) & (lower_wick <= 0.3 * body.replace(0, np.nan)) & (body > 0)

    # Pin bar: tek yonlu uzun golge, kucuk govde (hammer/shooting star'in genellemesi)
    out["bullish_pin_bar"] = (lower_wick >= 0.66 * rng) & (body <= 0.25 * rng)
    out["bearish_pin_bar"] = (upper_wick >= 0.66 * rng) & (body <= 0.25 * rng)

    # Inside bar: onceki mumun high/low araligina tamamen sigan mum
    out["inside_bar"] = (h <= h.shift(1)) & (l >= l.shift(1))

    return out.fillna(False)


def detect_swings(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """Basit fraktal bazli swing high/low tespiti: her iki tarafta
    ``lookback`` bar boyunca en yuksek/dusuk olan noktalar."""
    out = pd.DataFrame(index=df.index)
    high_roll_max = df["high"].rolling(2 * lookback + 1, center=True).max()
    low_roll_min = df["low"].rolling(2 * lookback + 1, center=True).min()
    out["swing_high"] = df["high"] == high_roll_max
    out["swing_low"] = df["low"] == low_roll_min
    return out


def detect_breakouts(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    prior_high = df["high"].rolling(lookback).max().shift(1)
    prior_low = df["low"].rolling(lookback).min().shift(1)
    out["resistance"] = prior_high
    out["support"] = prior_low
    out["breakout_up"] = df["close"] > prior_high
    out["breakout_down"] = df["close"] < prior_low
    return out


def trend_filter(df: pd.DataFrame, fast_col: str = "ema_50", slow_col: str = "ema_200") -> pd.Series:
    fast, slow = df[fast_col], df[slow_col]
    trend = pd.Series("sideways", index=df.index)
    trend[(df["close"] > fast) & (fast > slow)] = "uptrend"
    trend[(df["close"] < fast) & (fast < slow)] = "downtrend"
    return trend


def price_action_vote(df: pd.DataFrame, patterns: pd.DataFrame, breakouts: pd.DataFrame, trend: pd.Series) -> pd.Series:
    bullish = (
        patterns["bullish_engulfing"] | patterns["hammer"] | patterns["bullish_pin_bar"] | breakouts["breakout_up"]
    )
    bearish = (
        patterns["bearish_engulfing"] | patterns["shooting_star"] | patterns["bearish_pin_bar"] | breakouts["breakout_down"]
    )
    vote = pd.Series(0, index=df.index)
    vote[bullish & (trend != "downtrend")] = 1
    vote[bearish & (trend != "uptrend")] = -1
    # Ayni barda hem bullish hem bearish isaret varsa notrle
    vote[bullish & bearish] = 0
    return vote


# ---------------------------------------------------------------------------
# 2) RSI: esikler + divergence
# ---------------------------------------------------------------------------

def rsi_cross_votes(df: pd.DataFrame, rsi_col: str = "rsi_14", oversold: float = 30, overbought: float = 70) -> pd.Series:
    rsi_series = df[rsi_col]
    prev = rsi_series.shift(1)
    vote = pd.Series(0, index=df.index)
    vote[(prev < oversold) & (rsi_series >= oversold)] = 1
    vote[(prev > overbought) & (rsi_series <= overbought)] = -1
    return vote


def detect_rsi_divergence(df: pd.DataFrame, swings: pd.DataFrame, rsi_col: str = "rsi_14", lookback: int = 40) -> pd.Series:
    """Fiyat ile RSI arasindaki son iki swing noktasi uzerinden basit
    regular divergence tespiti (+1 bullish, -1 bearish, 0 yok)."""
    vote = pd.Series(0, index=df.index)
    low_idx = df.index[swings["swing_low"]].tolist()
    high_idx = df.index[swings["swing_high"]].tolist()

    for i in range(1, len(low_idx)):
        cur, prev = low_idx[i], low_idx[i - 1]
        if cur - prev > lookback:
            continue
        if df["low"][cur] < df["low"][prev] and df[rsi_col][cur] > df[rsi_col][prev]:
            vote.loc[cur] = 1  # bullish divergence: fiyat dusuk yapiyor, RSI yapmiyor

    for i in range(1, len(high_idx)):
        cur, prev = high_idx[i], high_idx[i - 1]
        if cur - prev > lookback:
            continue
        if df["high"][cur] > df["high"][prev] and df[rsi_col][cur] < df[rsi_col][prev]:
            vote.loc[cur] = -1  # bearish divergence: fiyat yuksek yapiyor, RSI yapmiyor

    return vote


def rsi_vote(df: pd.DataFrame, rsi_col: str = "rsi_14", swings: pd.DataFrame | None = None) -> pd.Series:
    cross = rsi_cross_votes(df, rsi_col)
    if swings is None:
        return cross
    div = detect_rsi_divergence(df, swings, rsi_col)
    combined = cross.copy()
    combined[div != 0] = div[div != 0]
    return combined


# ---------------------------------------------------------------------------
# 3) Hacim: spike + yon uyumu + OBV
# ---------------------------------------------------------------------------

def volume_vote(df: pd.DataFrame) -> pd.Series:
    bullish_bar = df["close"] > df["open"]
    bearish_bar = df["close"] < df["open"]
    obv_rising = df["obv_slope"] > 0
    obv_falling = df["obv_slope"] < 0

    vote = pd.Series(0, index=df.index)
    vote[df["volume_spike"] & bullish_bar & obv_rising] = 1
    vote[df["volume_spike"] & bearish_bar & obv_falling] = -1
    # Spike yoksa ama OBV net yon veriyorsa daha zayif bir teyit olarak kullan
    weak_bull = (~df["volume_spike"]) & bullish_bar & obv_rising & (df["close"] > df["vwap_daily"])
    weak_bear = (~df["volume_spike"]) & bearish_bar & obv_falling & (df["close"] < df["vwap_daily"])
    vote[weak_bull & (vote == 0)] = 1
    vote[weak_bear & (vote == 0)] = -1
    return vote


# ---------------------------------------------------------------------------
# Confluence: sinyal uretimi
# ---------------------------------------------------------------------------

@dataclass
class StrategyParams:
    rsi_col: str = "rsi_14"
    swing_lookback: int = 3
    breakout_lookback: int = 20
    min_confluence: int = 2  # 3 katmandan en az kaci ayni yonde olmali
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    atr_target_mult: float = 3.0
    use_trailing_stop: bool = True
    trailing_atr_mult: float = 2.5
    allow_short: bool = True


def build_signals(df: pd.DataFrame, params: StrategyParams | None = None) -> pd.DataFrame:
    """Indikatorlerin zaten eklenmis oldugu bir df alir; her katmanin oyunu
    ve nihai confluence sinyalini ekler."""
    params = params or StrategyParams()
    out = df.copy()

    patterns = detect_candle_patterns(out)
    swings = detect_swings(out, lookback=params.swing_lookback)
    breakouts = detect_breakouts(out, lookback=params.breakout_lookback)
    trend = trend_filter(out)

    for col, series in patterns.items():
        out[f"pattern_{col}"] = series
    out["swing_high"] = swings["swing_high"]
    out["swing_low"] = swings["swing_low"]
    out["resistance"] = breakouts["resistance"]
    out["support"] = breakouts["support"]
    out["breakout_up"] = breakouts["breakout_up"]
    out["breakout_down"] = breakouts["breakout_down"]
    out["trend"] = trend

    out["vote_price_action"] = price_action_vote(out, patterns, breakouts, trend)
    out["vote_rsi"] = rsi_vote(out, rsi_col=params.rsi_col, swings=swings)
    out["vote_volume"] = volume_vote(out)

    out["confluence_score"] = out["vote_price_action"] + out["vote_rsi"] + out["vote_volume"]
    bullish_layers = (
        (out["vote_price_action"] > 0).astype(int)
        + (out["vote_rsi"] > 0).astype(int)
        + (out["vote_volume"] > 0).astype(int)
    )
    bearish_layers = (
        (out["vote_price_action"] < 0).astype(int)
        + (out["vote_rsi"] < 0).astype(int)
        + (out["vote_volume"] < 0).astype(int)
    )

    out["signal"] = 0
    out.loc[bullish_layers >= params.min_confluence, "signal"] = 1
    out.loc[bearish_layers >= params.min_confluence, "signal"] = -1
    if not params.allow_short:
        out.loc[out["signal"] == -1, "signal"] = 0

    return out
