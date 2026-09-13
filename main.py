"""neyedayanarak — OKX mum verisi uzerinde price action + RSI + hacim
confluence stratejisi backtest CLI.

Ornek kullanim:
    python main.py --symbol BTC-USDT --timeframe 1H --start 2023-01-01 --end 2026-09-01 --optimize
    python main.py --symbols BTC-USDT,ETH-USDT --timeframe 4H --optimize
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.backtest import (
    StrategyParams,
    buy_and_hold,
    compare_signal_layers,
    optimize_params,
    run_backtest_with_params,
    train_test_split_chronological,
)
from src.data_fetcher import fetch_and_cache
from src.indicators import add_all_indicators
from src.strategy import build_signals
from src.visualize import plot_equity_and_drawdown, plot_price_signals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OKX price action + RSI + hacim confluence backtest")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--symbol", default="BTC-USDT", help="Tek sembol, ör. BTC-USDT")
    group.add_argument("--symbols", help="Virgulle ayrilmis birden fazla sembol, ör. BTC-USDT,ETH-USDT")

    parser.add_argument(
        "--timeframe", default="1H",
        choices=["1m", "3m", "5m", "15m", "30m", "1H", "2H", "4H", "6H", "12H", "1D", "1W"],
        help="Mum zaman dilimi (varsayilan: 1H)",
    )
    parser.add_argument("--start", default="2023-01-01", help="Baslangic tarihi YYYY-MM-DD (UTC)")
    parser.add_argument("--end", default="2026-09-01", help="Bitis tarihi YYYY-MM-DD (UTC)")
    parser.add_argument("--outdir", default="outputs", help="Sonuc/grafik klasoru")
    parser.add_argument("--data-dir", default="data", help="Ham CSV onbellek klasoru")
    parser.add_argument("--train-frac", type=float, default=0.7, help="In-sample (egitim) orani")
    parser.add_argument("--optimize", action="store_true", help="In-sample veride grid-search parametre optimizasyonu yap")
    parser.add_argument("--min-confluence", type=int, default=2, help="Sinyal icin gereken minimum katman sayisi (optimize kapaliysa kullanilir)")
    parser.add_argument("--atr-stop-mult", type=float, default=2.0)
    parser.add_argument("--atr-target-mult", type=float, default=3.0)
    parser.add_argument("--initial-equity", type=float, default=10_000.0)
    parser.add_argument("--allow-short", action="store_true", default=True)
    parser.add_argument("--long-only", dest="allow_short", action="store_false")
    parser.add_argument("--force-refresh", action="store_true", help="Onbellegi yoksayip OKX'ten yeniden cek")
    return parser.parse_args()


def run_for_symbol(symbol: str, args: argparse.Namespace) -> dict:
    print(f"\n{'=' * 70}\n{symbol} {args.timeframe} icin pipeline calisiyor\n{'=' * 70}")

    raw_df = fetch_and_cache(
        symbol, args.timeframe, args.start, args.end,
        data_dir=args.data_dir, force_refresh=args.force_refresh,
    )
    df = add_all_indicators(raw_df)
    df = df.dropna(subset=["ema_200", "atr"]).reset_index(drop=True)

    train_df, test_df = train_test_split_chronological(df, args.train_frac)
    print(f"In-sample: {len(train_df)} mum ({train_df['timestamp'].min()} -> {train_df['timestamp'].max()})")
    print(f"Out-of-sample: {len(test_df)} mum ({test_df['timestamp'].min()} -> {test_df['timestamp'].max()})")

    if args.optimize:
        print("Grid-search parametre optimizasyonu (in-sample)...")
        best_params, grid_results = optimize_params(train_df, args.timeframe)
        outdir = Path(args.outdir) / symbol
        outdir.mkdir(parents=True, exist_ok=True)
        grid_results.sort_values("sharpe", ascending=False).to_csv(outdir / "param_grid_results.csv", index=False)
        print(f"En iyi parametreler: {best_params}")
    else:
        best_params = StrategyParams(
            min_confluence=args.min_confluence,
            atr_stop_mult=args.atr_stop_mult,
            atr_target_mult=args.atr_target_mult,
            allow_short=args.allow_short,
        )

    best_params.allow_short = args.allow_short

    full_signaled = build_signals(df, best_params)
    train_signaled = full_signaled.iloc[: len(train_df)].reset_index(drop=True)
    test_signaled = full_signaled.iloc[len(train_df):].reset_index(drop=True)

    train_result = run_backtest_with_params(train_signaled, args.timeframe, best_params, initial_equity=args.initial_equity)
    test_result = run_backtest_with_params(test_signaled, args.timeframe, best_params, initial_equity=args.initial_equity)
    bh_test = buy_and_hold(test_signaled, args.timeframe, initial_equity=args.initial_equity)

    layer_comparison = compare_signal_layers(test_df, args.timeframe, best_params)

    outdir = Path(args.outdir) / symbol
    outdir.mkdir(parents=True, exist_ok=True)

    plot_price_signals(test_signaled, symbol, args.timeframe, outdir / "price_signals.png")
    plot_equity_and_drawdown(test_result, bh_test, symbol, outdir / "equity_drawdown.png")
    layer_comparison.to_csv(outdir / "layer_comparison.csv", index=False)

    report = {
        "symbol": symbol,
        "timeframe": args.timeframe,
        "start": args.start,
        "end": args.end,
        "params": vars(best_params) if hasattr(best_params, "__dict__") else best_params.__dict__,
        "in_sample_metrics": train_result.metrics,
        "out_of_sample_metrics": test_result.metrics,
        "buy_and_hold_out_of_sample": bh_test.metrics,
        "num_candles": len(df),
    }
    with open(outdir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n--- {symbol} OUT-OF-SAMPLE SONUCLARI ---")
    for k, v in test_result.metrics.items():
        print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
    print(f"  buy_and_hold_total_return_pct: {bh_test.metrics['total_return_pct']:.3f}")
    print(f"\nKatman karsilastirmasi (out-of-sample):\n{layer_comparison[['layer', 'total_return_pct', 'sharpe', 'win_rate_pct', 'num_trades']].to_string(index=False)}")
    print(f"\nCiktilar kaydedildi: {outdir.resolve()}")

    return report


def main():
    args = parse_args()
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else [args.symbol]

    all_reports = []
    for symbol in symbols:
        all_reports.append(run_for_symbol(symbol, args))

    if len(symbols) > 1:
        summary = pd.DataFrame(
            [
                {
                    "symbol": r["symbol"],
                    "oos_total_return_pct": r["out_of_sample_metrics"]["total_return_pct"],
                    "oos_sharpe": r["out_of_sample_metrics"]["sharpe"],
                    "oos_max_drawdown_pct": r["out_of_sample_metrics"]["max_drawdown_pct"],
                    "oos_win_rate_pct": r["out_of_sample_metrics"]["win_rate_pct"],
                    "buy_hold_total_return_pct": r["buy_and_hold_out_of_sample"]["total_return_pct"],
                }
                for r in all_reports
            ]
        )
        summary_path = Path(args.outdir) / "symbol_comparison.csv"
        summary.to_csv(summary_path, index=False)
        print(f"\n{'=' * 70}\nSEMBOL KARSILASTIRMASI\n{'=' * 70}\n{summary.to_string(index=False)}")
        print(f"\nOzet kaydedildi: {summary_path.resolve()}")


if __name__ == "__main__":
    main()
