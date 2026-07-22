"""Settings and statistics in ~/.config/yahtzee/."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "yahtzee"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
STATS_FILE = CONFIG_DIR / "stats.json"
SAVE_FILE = CONFIG_DIR / "saved_game.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "normal",           # normal | hints | coach | auto
    "n_bots": 2,                # an average game: 3 players total
    "difficulty": "medium",
    "n_games": 3,               # games per match: a column each, like the pad
    "speed": "normal",          # slow | normal | fast | instant
    "win_mode": True,           # endgame win-probability play in hints/auto
    "last_seen_version": None,  # for the what's-new message after updates
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


def save_game_snapshot(snapshot: dict[str, Any]) -> None:
    _write_json(SAVE_FILE, snapshot)


def load_game_snapshot() -> dict[str, Any] | None:
    snapshot = _read_json(SAVE_FILE, None)
    return snapshot if isinstance(snapshot, dict) else None


def clear_saved_game() -> None:
    try:
        SAVE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def record_game(
    players: list[tuple[str, bool, str | None, int]],
    rules: str | None = None,
    accuracy: int | None = None,
) -> None:
    """Legacy match record (kept for compatibility)."""
    stats = load_stats()
    entry: dict[str, Any] = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "players": [
            {"name": n, "bot": b, "difficulty": d, "score": s}
            for n, b, d, s in players
        ],
    }
    if rules:
        entry["rules"] = rules
    if accuracy is not None:
        entry["accuracy"] = accuracy
    stats["games"].append(entry)
    _write_json(STATS_FILE, stats)


def record_game_result(entry: dict[str, Any]) -> None:
    """Record one COMPLETED game (also mid-match), so abandoning a match
    later never erases games that were actually played."""
    stats = load_stats()
    entry = dict(entry, date=datetime.now().isoformat(timespec="seconds"))
    stats.setdefault("games_v2", []).append(entry)
    _write_json(STATS_FILE, stats)


def _bucket(games: list[dict], key) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for g in games:
        for k in key(g):
            out.setdefault(str(k), []).append(g)
    return out


def _line(label: str, games: list[dict]) -> str:
    n = len(games)
    wins = sum(1 for g in games if g.get("won"))
    avg = sum(g.get("your_score", 0) for g in games) / n
    return f"  {label:<12} {n:>4} games   won {100 * wins / n:>3.0f}%   avg {avg:6.1f}"


def stats_summary() -> list[str]:
    stats = load_stats()
    games = stats.get("games_v2", [])
    legacy = len(stats.get("games", []))
    if not games:
        lines = ["No games recorded yet (every finished game counts, even"]
        lines.append("if you abandon the match afterwards).")
        if legacy:
            lines.append(f"[dim]{legacy} matches from older versions not shown.[/dim]")
        return lines
    n = len(games)
    wins = sum(1 for g in games if g.get("won"))
    scores = [g.get("your_score", 0) for g in games]
    accs = [g["accuracy"] for g in games if g.get("accuracy") is not None]
    lines = [
        "[b]Overall[/b]",
        f"  Games played  {n}   won {wins} ({100 * wins / n:.0f}%)",
        f"  Average score {sum(scores) / n:.1f}   highest {max(scores)}",
    ]
    if accs:
        lines.append(f"  Average accuracy {sum(accs) / len(accs):.0f}%")
    lines.append("  [dim]The optimal strategy averages 254.6 per game.[/dim]")

    by_assist = _bucket(games, lambda g: [g.get("assist", "none")])
    if by_assist:
        lines += ["", "[b]By assistance[/b]"]
        for k in ("none", "hints", "coach", "auto"):
            if k in by_assist:
                lines.append(_line(k, by_assist[k]))

    by_diff = _bucket(games, lambda g: sorted(set(g.get("difficulties", []))))
    if by_diff:
        lines += ["", "[b]Against difficulty[/b]  [dim](game counts once per level present)[/dim]"]
        for k in ("easy", "medium", "hard", "optimal"):
            if k in by_diff:
                lines.append(_line(k, by_diff[k]))

    by_size = _bucket(games, lambda g: [g.get("n_opponents", "?")])
    if by_size:
        lines += ["", "[b]By table size[/b]"]
        for k in sorted(by_size):
            label = f"{k} bot" + ("s" if k != "1" else "")
            lines.append(_line(label, by_size[k]))

    by_rules = _bucket(games, lambda g: [g.get("rules", "official")])
    if len(by_rules) > 1:
        lines += ["", "[b]By rule variant[/b]"]
        for k, v in sorted(by_rules.items()):
            lines.append(_line(k, v))

    if legacy:
        lines += ["", f"[dim]Plus {legacy} matches recorded by older versions.[/dim]"]
    return lines
