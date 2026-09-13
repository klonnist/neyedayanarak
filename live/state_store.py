"""Her profil icin sanal hesap durumunu (bakiye, acik pozisyon, islem
gecmisi) JSON dosyasi olarak diskte saklar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def state_path(state_dir: str, profile_id: str) -> Path:
    return Path(state_dir) / f"{profile_id}.json"


def load_state(state_dir: str, profile_id: str, initial_balance: float) -> dict[str, Any]:
    path = state_path(state_dir, profile_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "balance": initial_balance,
        "initial_balance": initial_balance,
        "position": None,
        "last_processed_ts": None,
        "trades": [],
        "equity_curve": [],
    }


def save_state(state_dir: str, profile_id: str, state: dict[str, Any]) -> None:
    path = state_path(state_dir, profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)
