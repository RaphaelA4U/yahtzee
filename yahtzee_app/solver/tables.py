"""Loading/saving the optimal-strategy tables (one per ruleset)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
FALLBACK_DIR = Path.home() / ".config" / "yahtzee"

_cached: dict[str, np.ndarray] = {}


def _filename(rules: str) -> str:
    return f"state_values_{rules}.npz"


def save_table(V: np.ndarray, rules: str = "official", directory: Path = DATA_DIR) -> Path:
    path = directory / _filename(rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, V=V.astype(np.float32), ev_start=V[0, 0, 0])
    return path


def load_table(rules: str = "official") -> np.ndarray:
    """Load a ruleset's table; build it once if it cannot be found anywhere."""
    if rules in _cached:
        return _cached[rules]
    for directory in (DATA_DIR, FALLBACK_DIR):
        path = directory / _filename(rules)
        if path.exists():
            with np.load(path) as npz:
                _cached[rules] = npz["V"].astype(np.float64)
            return _cached[rules]
    # Fallback: build once (should not be needed; tables ship in the repo).
    from .build import build_table

    print(f"Solver table for '{rules}' not found; building it once (~15s-2min)...")
    V = build_table(rules)
    try:
        save_table(V, rules, DATA_DIR)
    except OSError:
        save_table(V, rules, FALLBACK_DIR)
    _cached[rules] = V
    return _cached[rules]
