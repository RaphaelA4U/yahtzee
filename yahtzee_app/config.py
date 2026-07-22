"""Settings and statistics in ~/.config/yahtzee/."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "yahtzee"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATS_FILE = CONFIG_DIR / "stats.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "normal",           # normal | hints | auto
    "n_bots": 2,                # an average game: 3 players total
    "difficulty": "medium",
    "speed": "normal",          # slow | normal | fast | instant
}

SPEED_DELAYS = {
    "slow": 1.1,
    "normal": 0.65,
    "fast": 0.25,
    "instant": 0.0,
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError:
        pass


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    settings.update(_read_json(SETTINGS_FILE, {}))
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    _write_json(SETTINGS_FILE, settings)


def load_stats() -> dict[str, Any]:
    return _read_json(STATS_FILE, {"games": []})


def record_game(players: list[tuple[str, bool, str | None, int]]) -> None:
    """players: (name, is_bot, difficulty, score), winner first."""
    stats = load_stats()
    stats["games"].append(
        {
            "date": datetime.now().isoformat(timespec="seconds"),
            "players": [
                {"name": n, "bot": b, "difficulty": d, "score": s}
                for n, b, d, s in players
            ],
        }
    )
    _write_json(STATS_FILE, stats)


def stats_summary() -> list[str]:
    stats = load_stats()
    games = stats.get("games", [])
    if not games:
        return ["No games played yet."]
    human_scores = []
    wins = 0
    for g in games:
        humans = [p for p in g["players"] if not p["bot"]]
        if not humans:
            continue
        score = humans[0]["score"]
        human_scores.append(score)
        best = max(p["score"] for p in g["players"])
        if score >= best:
            wins += 1
    if not human_scores:
        return ["No games played yet."]
    n = len(human_scores)
    return [
        f"Games played: {n}",
        f"Won: {wins} ({100 * wins / n:.0f}%)",
        f"Average score: {sum(human_scores) / n:.1f}",
        f"Highest score: {max(human_scores)}",
        "For reference: the optimal strategy averages 254.6.",
    ]
