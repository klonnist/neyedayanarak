"""Bar-bar backtest motoru, performans metrikleri ve basit parametre
optimizasyonu (in-sample / out-of-sample ayrimiyla)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .strategy import StrategyParams, build_signals

TRADING_PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "3m": 365 * 24 * 20,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "2h": 365 * 12,
    "4h": 365 * 6,
    "6h": 365 * 4,
    "12h": 365 * 2,
    "1d": 365,
    "1w": 52,
}


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int  # +1 long, -1 short
    entry_price: float
    exit_price: float
    exit_reason: str
    bars_held: int
    pnl_pct: float


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict = field(default_factory=dict)


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def _sharpe(returns: pd.Series, periods_per_year: int) -> float:
    if returns.std(ddof=0) == 0 or returns.empty:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / returns.std(ddof=0))


def _sortino(returns: pd.Series, periods_per_year: int) -> float:
    downside = returns[returns < 0]
    if downside.std(ddof=0) == 0 or downside.empty:
        return 0.0
    return float(np.sqrt(periods_per_year) * returns.mean() / downside.std(ddof=0))


def compute_metrics(equity: pd.Series, trades: list[Trade], timeframe: str) -> dict:
    periods_per_year = TRADING_PERIODS_PER_YEAR.get(timeframe.lower(), 365)
    returns = equity.pct_change().dropna()

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
    n_periods = max(len(equity) - 1, 1)
    years = n_periods / periods_per_year
    annualized_return = (
        float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0) if years > 0 and equity.iloc[0] > 0 else 0.0
    )

    wins = [t for t in trades if t.pnl_pct > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_duration = float(np.mean([t.bars_held for t in trades])) if trades else 0.0

    return {
        "total_return_pct": total_return * 100,
        "annualized_return_pct": annualized_return * 100,
        "max_drawdown_pct": _max_drawdown(equity) * 100,
        "sharpe": _sharpe(returns, periods_per_year),
        "sortino": _sortino(returns, periods_per_year),
        "win_rate_pct": win_rate * 100,
        "num_trades": len(trades),
        "avg_trade_duration_bars": avg_duration,
    }


def run_backtest(
    df: pd.DataFrame,
    timeframe: str,
    signal_col: str = "signal",
    initial_equity: float = 10_000.0,
    fee_pct: float = 0.05,  # taker fee (%) - giris + cikista uygulanir
) -> BacktestResult:
    """Tek pozisyonlu, ATR bazli stop/target ve trailing stop ile bar-bar
    backtest. ``df`` icinde en az close/high/low, ``atr`` ve ``signal_col``
    bulunmalidir. Strateji parametreleri df'e ``atr_stop_mult`` vb. olarak
    degil, ayri ``StrategyParams`` ile cagrilardan gelir; burada sabit
    carpanlar kullanilir (bkz. run_backtest_with_params)."""
    return run_backtest_with_params(df, timeframe, StrategyParams(), signal_col, initial_equity, fee_pct)


def run_backtest_with_params(
    df: pd.DataFrame,
    timeframe: str,
    params: StrategyParams,
    signal_col: str = "signal",
    initial_equity: float = 10_000.0,
    fee_pct: float = 0.05,
) -> BacktestResult:
    fee = fee_pct / 100.0
    equity = initial_equity
    equity_curve = np.empty(len(df))

    position = 0  # 0 flat, +1 long, -1 short
    entry_price = 0.0
    entry_time = None
    entry_idx = 0
    stop_price = 0.0
    target_price = 0.0
    trailing_extreme = 0.0

    trades: list[Trade] = []
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    atrs = df["atr"].to_numpy()
    signals = df[signal_col].to_numpy()
    times = df["timestamp"].to_numpy()

    def close_trade(exit_idx: int, exit_price: float, reason: str):
        nonlocal equity, position
        gross_pnl_pct = position * (exit_price / entry_price - 1.0)
        net_pnl_pct = gross_pnl_pct - 2 * fee
        equity *= (1.0 + net_pnl_pct)
        trades.append(
            Trade(
                entry_time=pd.Timestamp(entry_time),
                exit_time=pd.Timestamp(times[exit_idx]),
                direction=position,
                entry_price=entry_price,
                exit_price=exit_price,
                exit_reason=reason,
                bars_held=exit_idx - entry_idx,
                pnl_pct=net_pnl_pct * 100,
            )
        )
        position = 0

    for i in range(len(df)):
        if position != 0:
            if position == 1:
                trailing_extreme = max(trailing_extreme, highs[i])
                trail_stop = trailing_extreme - params.trailing_atr_mult * atrs[entry_idx]
                effective_stop = max(stop_price, trail_stop) if params.use_trailing_stop else stop_price
                if lows[i] <= effective_stop:
                    close_trade(i, effective_stop, "stop_loss" if effective_stop == stop_price else "trailing_stop")
                elif highs[i] >= target_price:
                    close_trade(i, target_price, "take_profit")
                elif signals[i] == -1:
                    close_trade(i, closes[i], "opposite_signal")
            else:
                trailing_extreme = min(trailing_extreme, lows[i])
                trail_stop = trailing_extreme + params.trailing_atr_mult * atrs[entry_idx]
                effective_stop = min(stop_price, trail_stop) if params.use_trailing_stop else stop_price
                if highs[i] >= effective_stop:
                    close_trade(i, effective_stop, "stop_loss" if effective_stop == stop_price else "trailing_stop")
                elif lows[i] <= target_price:
                    close_trade(i, target_price, "take_profit")
                elif signals[i] == 1:
                    close_trade(i, closes[i], "opposite_signal")

        if position == 0 and not np.isnan(atrs[i]) and atrs[i] > 0:
            if signals[i] == 1:
                position = 1
                entry_price = closes[i]
                entry_time = times[i]
                entry_idx = i
                stop_price = entry_price - params.atr_stop_mult * atrs[i]
                target_price = entry_price + params.atr_target_mult * atrs[i]
                trailing_extreme = highs[i]
            elif signals[i] == -1 and params.allow_short:
                position = -1
                entry_price = closes[i]
                entry_time = times[i]
                entry_idx = i
                stop_price = entry_price + params.atr_stop_mult * atrs[i]
                target_price = entry_price - params.atr_target_mult * atrs[i]
                trailing_extreme = lows[i]

        equity_curve[i] = equity

    if position != 0:
        close_trade(len(df) - 1, closes[-1], "end_of_data")
        equity_curve[-1] = equity

    equity_series = pd.Series(equity_curve, index=df["timestamp"])
    metrics = compute_metrics(equity_series, trades, timeframe)
    return BacktestResult(equity_curve=equity_series, trades=trades, metrics=metrics)


def buy_and_hold(df: pd.DataFrame, timeframe: str, initial_equity: float = 10_000.0) -> BacktestResult:
    equity_series = initial_equity * (df["close"] / df["close"].iloc[0])
    equity_series.index = df["timestamp"]
    metrics = compute_metrics(equity_series, [], timeframe)
    return BacktestResult(equity_curve=equity_series, trades=[], metrics=metrics)


def compare_signal_layers(df_indicators: pd.DataFrame, timeframe: str, params: StrategyParams) -> pd.DataFrame:
    """Price action / RSI / hacim katmanlarini tek basina ve birlikte
    (confluence) kullanarak backtest sonuclarini karsilastirir."""
    from . import strategy as strat_mod

    base = strat_mod.build_signals(df_indicators, params)

    layer_signal_defs = {
        "price_action_only": base["vote_price_action"],
        "rsi_only": base["vote_rsi"],
        "volume_only": base["vote_volume"],
        "confluence_2of3": base["signal"],
    }

    rows = []
    for name, votes in layer_signal_defs.items():
        temp = base.copy()
        temp["tmp_signal"] = votes
        if not params.allow_short:
            temp.loc[temp["tmp_signal"] == -1, "tmp_signal"] = 0
        result = run_backtest_with_params(temp, timeframe, params, signal_col="tmp_signal")
        row = {"layer": name, **result.metrics}
        rows.append(row)

    bh = buy_and_hold(df_indicators, timeframe)
    rows.append({"layer": "buy_and_hold", **bh.metrics})
    return pd.DataFrame(rows)


def train_test_split_chronological(df: pd.DataFrame, train_frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_idx = int(len(df) * train_frac)
    return df.iloc[:split_idx].reset_index(drop=True), df.iloc[split_idx:].reset_index(drop=True)


def optimize_params(
    df_train: pd.DataFrame,
    timeframe: str,
    grid: dict[str, list] | None = None,
) -> tuple[StrategyParams, pd.DataFrame]:
    """Kucuk bir grid uzerinde in-sample (egitim) verisiyle Sharpe orani
    maksimize edilerek en iyi parametre seti bulunur."""
    from . import strategy as strat_mod

    grid = grid or {
        "min_confluence": [2, 3],
        "atr_stop_mult": [1.5, 2.0, 2.5],
        "atr_target_mult": [2.0, 3.0, 4.0],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))

    results = []
    best_params = None
    best_sharpe = -np.inf

    for combo in combos:
        kwargs = dict(zip(keys, combo))
        params = StrategyParams(**kwargs)
        signaled = strat_mod.build_signals(df_train, params)
        result = run_backtest_with_params(signaled, timeframe, params)
        row = {**kwargs, **result.metrics}
        results.append(row)
        if result.metrics["sharpe"] > best_sharpe:
            best_sharpe = result.metrics["sharpe"]
            best_params = params

    return best_params or StrategyParams(), pd.DataFrame(results)
