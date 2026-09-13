"""GitHub Actions tarafindan periyodik calistirilan giris noktasi.

Her profil icin bir adim ilerletir ve docs/data/status.json panosunu
gunceller (GitHub Pages bu dosyayi okuyarak canli goruntuler).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    DASHBOARD_DATA_PATH,
    DEFAULT_STRATEGY_PARAMS,
    FEE_PCT,
    INITIAL_BALANCE,
    LOOKBACK_CANDLES,
    MAX_EQUITY_POINTS,
    MAX_RECENT_TRADES,
    PROFILES,
    STATE_DIR,
)
from .paper_engine import run_profile


def build_profile_summary(profile, state: dict) -> dict:
    trades = state.get("trades", [])
    wins = [t for t in trades if t["pnl_pct"] > 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    total_pnl = state["balance"] - state["initial_balance"]
    total_pnl_pct = (state["balance"] / state["initial_balance"] - 1.0) * 100

    return {
        "id": profile.id,
        "symbol": profile.symbol,
        "timeframe": profile.timeframe,
        "balance": round(state["balance"], 2),
        "initial_balance": state["initial_balance"],
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 3),
        "win_rate_pct": round(win_rate, 1),
        "num_trades": len(trades),
        "open_position": state.get("position"),
        "last_price": state.get("last_price"),
        "updated_at": state.get("updated_at"),
        "equity_curve": state.get("equity_curve", [])[-300:],
    }


def main():
    profile_summaries = []
    all_trades = []

    for profile in PROFILES:
        print(f"[live] {profile.id} isleniyor...")
        state = run_profile(
            profile=profile,
            params=DEFAULT_STRATEGY_PARAMS,
            state_dir=STATE_DIR,
            initial_balance=INITIAL_BALANCE,
            fee_pct=FEE_PCT,
            lookback_candles=LOOKBACK_CANDLES,
            max_equity_points=MAX_EQUITY_POINTS,
        )
        profile_summaries.append(build_profile_summary(profile, state))
        for t in state.get("trades", []):
            all_trades.append(t)

    all_trades.sort(key=lambda t: t["exit_time"], reverse=True)

    dashboard = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Sanal (paper) hesap simulasyonudur; gercek para/borsa hesabi kullanilmaz. Yatirim tavsiyesi degildir.",
        "profiles": profile_summaries,
        "recent_trades": all_trades[:MAX_RECENT_TRADES],
    }

    out_path = Path(DASHBOARD_DATA_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False, default=str)

    print(f"[live] Pano verisi yazildi: {out_path.resolve()}")


if __name__ == "__main__":
    main()
