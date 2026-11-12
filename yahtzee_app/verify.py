"""`yahtzee --verify`: check one games.jsonl record against its seed.

The record is the only input. The dice of every roll are recomputed from the
seed (the same key the game rolls with, see TurnState.roll and Game.dice_key),
every turn is replayed with the game's own rules, and the result is computed,
not copied. Nothing here writes a file, opens the UI, checks for updates,
touches the network or loads the solver tables.
"""

from __future__ import annotations

import json
import random
import sys
from typing import Any

from . import __version__
from .game import N_CATEGORIES, RULESETS, Game, replay

MAX_INPUT = 2_000_000  # a game is a few KB; anything this big is not a record


class Refused(Exception):
    """The record does not hold up; the message is the reason."""


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(f"bad {what}")
    return value


def _seed_dice(key: str, rolls: list, held: list) -> list[list[int]]:
    """The rolls this turn must show, given its holds (as TurnState.roll)."""
    dice = [1] * 5
    out = []
    for k in range(len(rolls)):
        rng = random.Random(f"{key}:{k}")
        for i in range(5):
            value = rng.randint(1, 6)
            if k == 0 or not held[k - 1][i]:
                dice[i] = value
        out.append(list(dice))
    return out


def _check_turn(t: Any, seed: int, game_no: int, n_players: int) -> tuple[int, int]:
    if not isinstance(t, dict):
        raise Refused("bad turn")
    round_no = _int(t.get("round"), "round")
    player = _int(t.get("player"), "player")
    if not 1 <= round_no <= Game.ROUNDS or not 0 <= player < n_players:
        raise Refused(f"bad turn: round {round_no}, player {player}")
    cat = _int(t.get("cat"), "box")
    if not 0 <= cat < N_CATEGORIES:
        raise Refused(f"round {round_no}: illegal box {cat}")
    _int(t.get("points"), "points")
    if "bonus" in t:
        _int(t["bonus"], "bonus")
    rolls, held = t.get("rolls"), t.get("held", [])
    if not isinstance(rolls, list) or not 1 <= len(rolls) <= 3:
        raise Refused(f"round {round_no}: no rolls")
    if not isinstance(held, list) or len(held) != len(rolls) - 1:
        raise Refused(f"round {round_no}: bad holds")
    for r in rolls:
        if not (isinstance(r, list) and len(r) == 5
                and all(_int(d, "die") in range(1, 7) for d in r)):
            raise Refused(f"round {round_no}: bad roll")
    for h in held:
        if not (isinstance(h, list) and len(h) == 5 and all(isinstance(x, bool) for x in h)):
            raise Refused(f"round {round_no}: bad holds")
    expected = _seed_dice(f"{seed}:{game_no}:{round_no}", rolls, held)
    for k, (got, want) in enumerate(zip(rolls, expected)):
        if got != want:
            who = "you" if player == 0 else f"player {player}"
            raise Refused(f"round {round_no}, roll {k + 1} ({who}): dice do not match the seed")
    return round_no, player


def _verify(record: Any, out: dict) -> None:
    if not isinstance(record, dict):
        raise Refused("not a record")
    seed = record.get("seed")
    if seed is None:
        raise Refused("no seed")
    seed = _int(seed, "seed")
    out["seed"] = seed
    rules = record.get("rules")
    bots = record.get("bots")
    level = record.get("level")
    out["settings"] = {
        "rules": rules if isinstance(rules, str) else None,
        "bots": str(bots) if isinstance(bots, int) and not isinstance(bots, bool) else None,
        "level": level if isinstance(level, str) else None,
    }
    if rules not in RULESETS:
        raise Refused("unknown rules")
    bots = _int(bots, "bots")
    if not 0 <= bots <= 4:
        raise Refused("bad bots")
    game_no = _int(record.get("game_no"), "game_no")
    if game_no < 1:
        raise Refused("bad game_no")
    players = record.get("players")
    if players is None:
        n_players = bots + 1
    elif isinstance(players, list) and bots + 1 <= len(players) <= 8:
        n_players = len(players)
    else:
        raise Refused("bad players")

    turns = record.get("turns")
    if not isinstance(turns, list):
        raise Refused("no turns")
    seen = set()
    for t in turns:
        key = _check_turn(t, seed, game_no, n_players)
        if key in seen:
            raise Refused(f"round {key[0]}: player {key[1]} played twice")
        seen.add(key)
    if len(seen) != Game.ROUNDS * n_players:
        raise Refused("missing rounds")
    out["moves"] = sum(1 for t in turns if t["player"] == 0)

    ordered = sorted(turns, key=lambda t: (t["round"], t["player"]))
    try:
        cards = replay(ordered, n_players, rules)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    totals = [c.total() for c in cards]
    score, won = totals[0], totals[0] >= max(totals)
    out["score"], out["won"] = score, won

    if record.get("your_score") != score or isinstance(record.get("your_score"), bool):
        raise Refused("your_score differs from the replay")
    if record.get("won") is not won:
        raise Refused("won differs from the replay")
    if "boxes" in record and record["boxes"] != cards[0].boxes:
        raise Refused("boxes differ from the replay")
    if isinstance(players, list):
        for i, (p, total) in enumerate(zip(players, totals)):
            if isinstance(p, dict) and "score" in p and p["score"] != total:
                raise Refused(f"player {i} score differs from the replay")


def verify_record(record: Any) -> dict:
    """Check one games.jsonl record. Never raises: a record that does not
    hold up (or is not a record at all) gives ok false with a short reason."""
    out: dict = {
        "ok": False,
        "game": "yahtzee",
        "seed": None,
        "settings": {"rules": None, "bots": None, "level": None},
        "won": None,
        "time": None,  # yahtzee has no clock
        "score": None,
        "moves": None,
        "version": __version__,
        "reason": "",
    }
    try:
        _verify(record, out)
    except Refused as exc:
        out["reason"] = str(exc)
        return out
    except Exception:  # noqa: BLE001  a malformed record, never a traceback
        out["reason"] = "malformed record"
        return out
    out["ok"] = True
    return out


def main() -> int:
    """Read one record on stdin, print one JSON line; 0 if it holds up."""
    try:
        text = sys.stdin.read(MAX_INPUT + 1)
    except Exception:  # noqa: BLE001
        text = ""
    if len(text) > MAX_INPUT:
        result = verify_record(None)
        result["reason"] = "record too large"
    else:
        try:
            record = json.loads(text)
        except Exception:  # noqa: BLE001  not JSON, or nested too deep
            result = verify_record(None)
            result["reason"] = "not JSON"
        else:
            result = verify_record(record)
    print(json.dumps(result))
    return 0 if result["ok"] else 1
