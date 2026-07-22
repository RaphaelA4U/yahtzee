"""Arena: headless engine-vs-engine matches to tune strategies.

This is the hidden test mode: it runs many games without the UI, pitting
strategies against each other, and reports win rates. Used to tune the
win-mode parameters (winmode.WIN_ROUNDS, winmode.EV_BAND) for the highest
possible win rate.

Usage:
  python -m tools.arena                      # win-aware vs optimal, 400 games
  python -m tools.arena 1000                 # more games
  python -m tools.arena 400 optimal medium   # any two strategies
  python -m tools.arena 400 winaware optimal official 3   # rules + games/match

Strategies: easy | medium | hard | optimal | winaware
"""

from __future__ import annotations

import sys
import time

from yahtzee_app.bots import get_optimal_oracle, make_bot
from yahtzee_app.game import Game, Player, Scorecard
from yahtzee_app import winmode


def make_strategy(name: str, rules: str, me: Player, opponents: list[Player]):
    if name == "winaware":
        return winmode.WinAwareBot(get_optimal_oracle(rules), me, opponents)
    return make_bot(name, rules)


def play_match(
    strategy_names: list[str], rules: str, seed: int, n_games: int = 1
) -> list[int]:
    """Play one match; returns final match totals per player."""
    players = [
        Player(f"P{i}", is_bot=True, difficulty=name, card=Scorecard(rules))
        for i, name in enumerate(strategy_names)
    ]
    strategies = [
        make_strategy(name, rules, players[i], players[:i] + players[i + 1 :])
        for i, name in enumerate(strategy_names)
    ]
    for game_no in range(n_games):
        game = Game(players, seed=seed * 1000 + game_no)
        while not game.finished:
            player = game.current
            bot = strategies[game.current_idx]
            turn = game.turn
            turn.roll()
            while turn.rolls_left > 0:
                keep = bot.choose_keep(player.card, turn.counts(), turn.rolls_left)
                if keep == turn.counts():
                    break
                turn.set_holds_for(keep)
                turn.roll()
            option = bot.choose_option(player.card, turn.counts())
            player.card.apply(option, turn.counts())
            game.advance()
        if game_no < n_games - 1:
            for p in players:
                p.history.append(p.card)
                p.card = Scorecard(rules)
    return [p.match_total() for p in players]


def run_series(
    strategy_names: list[str], n_matches: int, rules: str = "official", n_games: int = 1
) -> dict:
    wins = [0.0] * len(strategy_names)
    totals = [0] * len(strategy_names)
    t0 = time.time()
    for seed in range(n_matches):
        scores = play_match(strategy_names, rules, seed, n_games)
        best = max(scores)
        winners = [i for i, s in enumerate(scores) if s == best]
        for i in winners:
            wins[i] += 1.0 / len(winners)  # split ties
        for i, s in enumerate(scores):
            totals[i] += s
    return {
        "wins": wins,
        "win_pct": [100.0 * w / n_matches for w in wins],
        "avg": [t / n_matches for t in totals],
        "seconds": time.time() - t0,
    }


def main() -> None:
    args = sys.argv[1:]
    n_matches = int(args[0]) if args else 400
    names = [a for a in args[1:] if not a.isdigit() and a not in ("official", "free_joker", "simple")]
    rules = next((a for a in args[1:] if a in ("official", "free_joker", "simple")), "official")
    trailing_ints = [a for a in args[1:] if a.isdigit()]
    n_games = int(trailing_ints[0]) if trailing_ints else 1
    if not names:
        names = ["winaware", "optimal"]
    result = run_series(names, n_matches, rules, n_games)
    print(f"{n_matches} matches, rules={rules}, games/match={n_games} "
          f"({result['seconds']:.0f}s)")
    for i, name in enumerate(names):
        print(
            f"  {name:10s} win {result['win_pct'][i]:5.1f}%   avg {result['avg'][i]:6.1f}"
        )


if __name__ == "__main__":
    main()
