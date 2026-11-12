"""`yahtzee --verify`: a games.jsonl record is checked against its seed."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yahtzee_app.bots import make_bot
from yahtzee_app.game import CATEGORY_NAMES, Game, Player, Scorecard
from yahtzee_app.verify import verify_record

ROOT = Path(__file__).resolve().parent.parent


def _play(seed: int, levels=("easy", "medium"), rules: str = "official", game_no: int = 1) -> dict:
    """One seeded game on the bare engine, you against bots, recorded the way
    the app records it (_record_current_game: the stats entry plus the game)."""
    players = [Player("You", card=Scorecard(rules))] + [
        Player(f"Bot{i}", is_bot=True, difficulty=lv, card=Scorecard(rules))
        for i, lv in enumerate(levels, start=1)
    ]
    bots = {i: make_bot(lv, rules) for i, lv in enumerate(levels, start=1)}
    game = Game(players, seed=seed, game_no=game_no)
    while not game.finished:
        turn, card = game.turn, game.current.card
        turn.roll()
        bot = bots.get(game.current_idx)
        while turn.rolls_left > 0:
            counts = turn.counts()
            if bot:
                keep = bot.choose_keep(card, counts, turn.rolls_left)
                if keep == counts:
                    break
                turn.set_holds_for(keep)
            else:
                face = max(range(6), key=lambda f: (counts[f], f))
                turn.held = [d == face + 1 for d in turn.dice]
                if all(turn.held):
                    break
            turn.roll()
        counts = turn.counts()
        if bot:
            option = bot.choose_option(card, counts)
        else:
            option = max(card.options(counts), key=lambda o: (o.points, -o.category))
        card.apply(option, counts)
        game.record_turn(option)
        game.advance()
    your = players[0].card.total()
    best = max(p.card.total() for p in players)
    entry = {
        "rules": rules,
        "n_opponents": len(levels),
        "difficulties": list(levels),
        "assist": "none",
        "your_score": your,
        "won": your >= best,
        "accuracy": None,
        "boxes": list(players[0].card.boxes),
        "players": [
            {"name": p.name, "bot": p.is_bot, "difficulty": p.difficulty, "score": p.card.total()}
            for p in players
        ],
    }
    record = {
        **entry,
        "date": "2026-11-12T12:00:00",
        "seed": seed,
        "version": "1.16.0",
        "rules": rules,
        "bots": len(levels),
        "level": ",".join(levels) or None,
        "game_no": game_no,
        "n_games": 1,
        "turns": list(game.log),
        "coach": [],
    }
    return json.loads(json.dumps(record))  # exactly what lands in games.jsonl


def test_a_seeded_game_verifies():
    record = _play(42)
    result = verify_record(record)
    assert result["ok"], result
    assert result["reason"] == ""
    assert result["game"] == "yahtzee" and result["seed"] == 42
    assert result["score"] == record["your_score"] == record["players"][0]["score"]
    assert result["won"] is record["won"]
    assert result["moves"] == 13
    assert result["time"] is None
    assert result["settings"] == {"rules": "official", "bots": "2", "level": "easy,medium"}
    json.dumps(result)


@pytest.mark.parametrize("seed,rules,game_no", [(7, "free_joker", 1), (123456, "simple", 2), (3, "official", 3)])
def test_other_rules_and_games_verify(seed, rules, game_no):
    record = _play(seed, levels=("medium",), rules=rules, game_no=game_no)
    assert verify_record(record)["ok"], verify_record(record)


def test_a_lost_game_verifies_with_won_false():
    for seed in range(1, 40):
        record = _play(seed, levels=("medium", "medium", "medium"))
        if not record["won"]:
            result = verify_record(record)
            assert result["ok"] and result["won"] is False
            return
    pytest.skip("no lost game in these seeds")


def _first_reroll(turns, player=0):
    return next(t for t in turns if t["player"] == player and len(t["rolls"]) > 1)


def test_a_changed_die_fails():
    record = _play(42)
    t = _first_reroll(record["turns"])
    i = t["held"][0].index(False)  # a rerolled die, so the hold check alone misses it
    t["rolls"][1][i] = t["rolls"][1][i] % 6 + 1
    result = verify_record(record)
    assert not result["ok"] and "seed" in result["reason"]


def test_a_changed_first_roll_fails():
    record = _play(42)
    t = _first_reroll(record["turns"])
    i = t["held"][0].index(False)  # rerolled next, so only the seed shows it
    t["rolls"][0][i] = t["rolls"][0][i] % 6 + 1
    result = verify_record(record)
    assert not result["ok"] and "roll 1" in result["reason"]


def test_a_bot_roll_is_checked_too():
    record = _play(42)
    t = next(t for t in record["turns"] if t["player"] == 1)
    t["rolls"][-1][0] = t["rolls"][-1][0] % 6 + 1
    result = verify_record(record)
    assert not result["ok"] and "player 1" in result["reason"]


def test_a_flipped_hold_fails():
    record = _play(42)
    t = _first_reroll(record["turns"])
    t["held"][0] = [not h for h in t["held"][0]]
    assert not verify_record(record)["ok"]


def test_changed_points_fail():
    record = _play(42)
    t = next(t for t in record["turns"] if t["player"] == 0)
    t["points"] += 5
    result = verify_record(record)
    assert not result["ok"] and "scores" in result["reason"]


def test_a_changed_box_fails():
    record = _play(42)
    turns = [t for t in record["turns"] if t["player"] == 0]
    a, b = turns[0], turns[1]
    a["cat"], b["cat"] = b["cat"], a["cat"]
    a["category"], b["category"] = CATEGORY_NAMES[a["cat"]], CATEGORY_NAMES[b["cat"]]
    assert not verify_record(record)["ok"]
    record = _play(42)
    record["turns"][0]["cat"] = 13
    assert verify_record(record)["reason"].startswith("round 1: illegal box")


def test_a_higher_score_fails():
    record = _play(42)
    record["your_score"] += 10
    result = verify_record(record)
    assert not result["ok"] and result["reason"] == "your_score differs from the replay"


def test_won_flipped_fails():
    record = _play(42)
    record["won"] = not record["won"]
    result = verify_record(record)
    assert not result["ok"] and result["reason"] == "won differs from the replay"


def test_no_seed_fails():
    record = _play(42)
    record["seed"] = None
    assert verify_record(record)["reason"] == "no seed"
    del record["seed"]
    assert verify_record(record)["reason"] == "no seed"


def test_a_removed_turn_fails():
    record = _play(42)
    record["turns"].pop()
    assert verify_record(record)["reason"] == "missing rounds"
    record = _play(42)
    record["turns"][5] = copy.deepcopy(record["turns"][2])
    assert not verify_record(record)["ok"]


def test_unknown_rules_fail():
    record = _play(42)
    record["rules"] = "house"
    assert verify_record(record)["reason"] == "unknown rules"


def test_another_seed_fails():
    record = _play(42)
    record["seed"] = 43
    assert "seed" in verify_record(record)["reason"]


@pytest.mark.parametrize("record", [None, [], "x", 5, {}, {"seed": "42"},
                                    {"seed": 1, "rules": "official", "bots": 1, "game_no": 1, "turns": [None]},
                                    {"seed": 1, "rules": "official", "bots": 1, "game_no": 1,
                                     "turns": [{"round": 1, "player": 0, "cat": 0, "points": 0, "rolls": [[1, 2]]}]}])
def test_malformed_records_never_raise(record):
    result = verify_record(record)
    assert result["ok"] is False and result["reason"]


def _run_cli(text: str, home: Path):
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.pop("YAHTZEE_PROFILE", None)
    env.pop("XDG_CONFIG_HOME", None)
    return subprocess.run(
        [sys.executable, "-m", "yahtzee_app", "--verify"],
        input=text, capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=30,
    )


def test_cli_verify_writes_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    record = _play(42)

    good = _run_cli(json.dumps(record), home)
    assert good.returncode == 0, good.stderr
    lines = good.stdout.strip().splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert out["ok"] and out["score"] == record["your_score"]

    record["your_score"] += 1
    bad = _run_cli(json.dumps(record), home)
    assert bad.returncode == 1 and json.loads(bad.stdout)["ok"] is False

    junk = _run_cli("{not json", home)
    assert junk.returncode == 1 and json.loads(junk.stdout)["reason"] == "not JSON"
    assert "Traceback" not in junk.stderr

    empty = _run_cli("", home)
    assert empty.returncode == 1 and json.loads(empty.stdout)["ok"] is False

    assert list(home.rglob("*")) == []
