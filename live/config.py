"""Canli sanal (paper) islem panosu icin sabit ayarlar.

Gercek para/borsa hesabi kullanilmaz: her profil, sifirdan baslayan
sanal bir USDT bakiyesi uzerinden src/strategy.py'deki ayni confluence
stratejisiyle pozisyon acip kapatir.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.strategy import StrategyParams


@dataclass(frozen=True)
class Profile:
    symbol: str
    timeframe: str

    @property
    def id(self) -> str:
        return f"{self.symbol}_{self.timeframe}"


PROFILES: list[Profile] = [
    Profile("BTC-USDT", "1H"),
    Profile("BTC-USDT", "4H"),
    Profile("ETH-USDT", "1H"),
    Profile("ETH-USDT", "4H"),
]

INITIAL_BALANCE = 10_000.0
FEE_PCT = 0.05  # taker ucreti (%), giris + cikista uygulanir

# Indikatorlerin (EMA200 dahil) saglikli hesaplanabilmesi icin her
# calistirmada geriye donuk cekilen mum sayisi.
LOOKBACK_CANDLES = 1500

# Her profil icin ayni varsayilan (backtest'te optimize edilmemis) confluence
# parametreleri kullanilir; bkz. README "Canli pano" bolumu.
DEFAULT_STRATEGY_PARAMS = StrategyParams()

MAX_EQUITY_POINTS = 1000
# Strateji dusuk frekansli oldugu icin (bkz. README) bu limite pratikte
# uzun sure ulasilmaz; panoda "gecmis islemler" fiilen tam gecmisi gosterir.
# Tam/sinirsiz gecmis her zaman live/state/<profil>.json icinde durur.
MAX_RECENT_TRADES = 500

STATE_DIR = "live/state"
DASHBOARD_DATA_PATH = "docs/data/status.json"
