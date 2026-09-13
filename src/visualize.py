"""Fiyat + sinyal, RSI, hacim, equity curve ve drawdown gorsellestirmeleri."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .backtest import BacktestResult

BULLISH_COLOR = "#26a69a"
BEARISH_COLOR = "#ef5350"


def _plot_candles(ax, df: pd.DataFrame):
    width = (df["timestamp"].iloc[1] - df["timestamp"].iloc[0]) * 0.6 if len(df) > 1 else pd.Timedelta(hours=1)
    for _, row in df.iterrows():
        color = BULLISH_COLOR if row["close"] >= row["open"] else BEARISH_COLOR
        ax.plot([row["timestamp"], row["timestamp"]], [row["low"], row["high"]], color=color, linewidth=0.6)
        ax.add_patch(
            plt.Rectangle(
                (mdates.date2num(row["timestamp"] - width / 2), min(row["open"], row["close"])),
                mdates.date2num(row["timestamp"] + width / 2) - mdates.date2num(row["timestamp"] - width / 2),
                max(abs(row["close"] - row["open"]), 1e-9),
                color=color,
            )
        )


def plot_price_signals(df: pd.DataFrame, symbol: str, timeframe: str, out_path: str | Path, max_candles: int = 500):
    """Fiyat + EMA + sinyaller. Cok uzun serilerde son ``max_candles`` mum gosterilir."""
    plot_df = df.tail(max_candles).reset_index(drop=True)

    fig, (ax_price, ax_rsi, ax_vol) = plt.subplots(
        3, 1, figsize=(16, 10), sharex=True, gridspec_kw={"height_ratios": [3, 1, 1]}
    )

    ax_price.plot(plot_df["timestamp"], plot_df["close"], color="#555555", linewidth=0.8, label="Close")
    if "ema_50" in plot_df:
        ax_price.plot(plot_df["timestamp"], plot_df["ema_50"], color="#1f77b4", linewidth=1, label="EMA 50")
    if "ema_200" in plot_df:
        ax_price.plot(plot_df["timestamp"], plot_df["ema_200"], color="#ff7f0e", linewidth=1, label="EMA 200")

    longs = plot_df[plot_df["signal"] == 1]
    shorts = plot_df[plot_df["signal"] == -1]
    ax_price.scatter(longs["timestamp"], longs["low"] * 0.995, marker="^", color=BULLISH_COLOR, s=60, label="Long sinyal", zorder=5)
    ax_price.scatter(shorts["timestamp"], shorts["high"] * 1.005, marker="v", color=BEARISH_COLOR, s=60, label="Short sinyal", zorder=5)

    ax_price.set_title(f"{symbol} {timeframe} — Fiyat, EMA ve Confluence Sinyalleri")
    ax_price.legend(loc="upper left", fontsize=8)
    ax_price.grid(alpha=0.2)

    if "rsi_14" in plot_df:
        ax_rsi.plot(plot_df["timestamp"], plot_df["rsi_14"], color="#8e44ad", linewidth=1, label="RSI 14")
    if "rsi_7" in plot_df:
        ax_rsi.plot(plot_df["timestamp"], plot_df["rsi_7"], color="#bbbbbb", linewidth=0.7, label="RSI 7")
    ax_rsi.axhline(70, color=BEARISH_COLOR, linestyle="--", linewidth=0.7)
    ax_rsi.axhline(30, color=BULLISH_COLOR, linestyle="--", linewidth=0.7)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel("RSI")
    ax_rsi.legend(loc="upper left", fontsize=8)
    ax_rsi.grid(alpha=0.2)

    colors = [BULLISH_COLOR if row.close >= row.open else BEARISH_COLOR for row in plot_df.itertuples()]
    ax_vol.bar(plot_df["timestamp"], plot_df["volume"], color=colors, width=0.03, alpha=0.8)
    if "volume_ma" in plot_df:
        ax_vol.plot(plot_df["timestamp"], plot_df["volume_ma"], color="black", linewidth=0.8, label="Hacim MA")
    spikes = plot_df[plot_df.get("volume_spike", False) == True]  # noqa: E712
    ax_vol.scatter(spikes["timestamp"], spikes["volume"], color="orange", s=20, label="Hacim spike", zorder=5)
    ax_vol.set_ylabel("Hacim")
    ax_vol.legend(loc="upper left", fontsize=8)
    ax_vol.grid(alpha=0.2)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_equity_and_drawdown(result: BacktestResult, bh_result: BacktestResult, symbol: str, out_path: str | Path):
    fig, (ax_eq, ax_dd) = plt.subplots(2, 1, figsize=(14, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})

    ax_eq.plot(result.equity_curve.index, result.equity_curve.values, color="#1f77b4", label="Strateji")
    ax_eq.plot(bh_result.equity_curve.index, bh_result.equity_curve.values, color="#999999", linestyle="--", label="Buy & Hold")
    ax_eq.set_title(f"{symbol} — Equity Egrisi (Strateji vs Buy & Hold)")
    ax_eq.legend(loc="upper left", fontsize=9)
    ax_eq.grid(alpha=0.2)

    running_max = result.equity_curve.cummax()
    drawdown = (result.equity_curve / running_max - 1.0) * 100
    ax_dd.fill_between(drawdown.index, drawdown.values, 0, color=BEARISH_COLOR, alpha=0.4)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.grid(alpha=0.2)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
