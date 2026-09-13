"""OKX public REST API'den OHLCV mum verisi çekme.

Kimlik dogrulama gerektirmez. /market/history-candles endpoint'i ile
gecmise donuk sayfalama (pagination) yaparak istenen tarih araligindaki
tum mumlari toplar.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OKX_BASE_URL = "https://www.okx.com"
HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"
CANDLES_PATH = "/api/v5/market/candles"

# OKX public endpoint rate limiti: 20 istek / 2 saniye. Guvenli pay birakiyoruz.
REQUEST_SLEEP_SECONDS = 0.15
MAX_RETRIES = 5
PAGE_LIMIT = 100

# Kullanicidan gelen esnek zaman dilimi yazimlarini OKX'in bekledigi "bar"
# koduna cevirir (ör. "1h" -> "1H", "1d" -> "1D", "15m" -> "15m").
TIMEFRAME_ALIASES = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W", "1m_month": "1M",
}

CANDLE_COLUMNS = [
    "ts", "open", "high", "low", "close", "volume", "vol_ccy", "vol_ccy_quote", "confirm",
]


def normalize_timeframe(timeframe: str) -> str:
    key = timeframe.strip().lower()
    if key not in TIMEFRAME_ALIASES:
        raise ValueError(
            f"Desteklenmeyen zaman dilimi: {timeframe!r}. "
            f"Gecerli degerler: {sorted(TIMEFRAME_ALIASES)}"
        )
    return TIMEFRAME_ALIASES[key]


def _to_ms(dt_str: str) -> int:
    dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _request_with_retry(session: requests.Session, url: str, params: dict) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(1.0 * attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") not in ("0", 0):
                raise RuntimeError(f"OKX API hatasi: {payload}")
            return payload
        except (requests.RequestException, RuntimeError) as exc:
            last_exc = exc
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"OKX istegi {MAX_RETRIES} denemede basarisiz oldu: {last_exc}")


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    verbose: bool = True,
) -> pd.DataFrame:
    """[start, end] tarih araligindaki (YYYY-MM-DD, UTC) tum mumlari cek.

    OKX en yeni mumdan geriye dogru sayfalar; ``after`` parametresi
    "bu zaman damgasindan daha eski kayitlari getir" anlamina gelir.
    """
    bar = normalize_timeframe(timeframe)
    start_ms = _to_ms(start)
    end_ms = _to_ms(end) + 24 * 60 * 60 * 1000  # bitis gununu de dahil et

    session = requests.Session()
    all_rows: list[list] = []
    after = end_ms
    url = OKX_BASE_URL + HISTORY_CANDLES_PATH

    while True:
        params = {
            "instId": symbol,
            "bar": bar,
            "limit": str(PAGE_LIMIT),
            "after": str(after),
        }
        payload = _request_with_retry(session, url, params)
        rows = payload.get("data", [])
        if not rows:
            break

        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])

        if verbose:
            oldest_dt = datetime.fromtimestamp(oldest_ts / 1000, tz=timezone.utc)
            print(f"  ...{len(all_rows)} mum cekildi, en eski: {oldest_dt:%Y-%m-%d %H:%M} UTC")

        if oldest_ts <= start_ms:
            break
        after = oldest_ts
        time.sleep(REQUEST_SLEEP_SECONDS)

    if not all_rows:
        raise RuntimeError(
            f"{symbol} / {bar} icin {start}..{end} araliginda veri bulunamadi."
        )

    df = pd.DataFrame(all_rows, columns=CANDLE_COLUMNS)
    df = df.drop_duplicates(subset="ts")
    for col in ["open", "high", "low", "close", "volume", "vol_ccy", "vol_ccy_quote"]:
        df[col] = df[col].astype(float)
    df["ts"] = df["ts"].astype("int64")
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[(df["ts"] >= start_ms) & (df["ts"] < end_ms)]
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return df


def fetch_and_cache(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    data_dir: str | Path = "data",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Veriyi ceker ve data/ altina CSV olarak onbelleklar (gitignore'lu)."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_file = data_dir / f"{symbol}_{normalize_timeframe(timeframe)}_{start}_{end}.csv"

    if cache_file.exists() and not force_refresh:
        print(f"[data_fetcher] Onbellekten okunuyor: {cache_file}")
        df = pd.read_csv(cache_file, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    print(f"[data_fetcher] OKX'ten cekiliyor: {symbol} {timeframe} {start} -> {end}")
    df = fetch_ohlcv(symbol, timeframe, start, end)
    df.to_csv(cache_file, index=False)
    print(f"[data_fetcher] {len(df)} mum kaydedildi -> {cache_file}")
    return df
