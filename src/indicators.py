"""Teknik indikator hesaplamalari: EMA, RSI (Wilder), ATR, OBV, VWAP."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder'in klasik RSI formulu (ewm ile Wilder smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.where(avg_loss != 0, 100.0)
    result = result.where(avg_gain != 0, 0.0)
    return result


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def rolling_vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Kayan pencereli VWAP (24/7 kripto piyasasi icin gunluk oturum yerine
    son N mumu baz alan pratik bir yaklasim)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum()


def daily_anchored_vwap(df: pd.DataFrame) -> pd.Series:
    """Her UTC gunu basinda sifirlanan (anchored) VWAP."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    day_key = df["timestamp"].dt.floor("D")
    cum_pv = pv.groupby(day_key).cumsum()
    cum_vol = df["volume"].groupby(day_key).cumsum()
    return cum_pv / cum_vol


def add_all_indicators(
    df: pd.DataFrame,
    rsi_periods: tuple[int, ...] = (7, 14, 21),
    ema_periods: tuple[int, ...] = (50, 200),
    atr_period: int = 14,
    volume_ma_period: int = 20,
) -> pd.DataFrame:
    out = df.copy()

    for p in ema_periods:
        out[f"ema_{p}"] = ema(out["close"], p)

    for p in rsi_periods:
        out[f"rsi_{p}"] = rsi(out["close"], p)

    out[f"atr_{atr_period}"] = atr(out, atr_period)
    out["atr"] = out[f"atr_{atr_period}"]

    out["obv"] = obv(out)
    out["obv_slope"] = out["obv"].diff(volume_ma_period)

    out["volume_ma"] = out["volume"].rolling(volume_ma_period).mean()
    out["volume_spike"] = out["volume"] > (2.0 * out["volume_ma"])

    out["vwap_rolling"] = rolling_vwap(out, window=volume_ma_period)
    out["vwap_daily"] = daily_anchored_vwap(out)

    return out
