"""Benchmark the bot difficulty levels by simulating full games.

Usage: python -m tools.simulate [games] [rules]
"""

from __future__ import annotations

import statistics
import sys
import time

from yahtzee_app.bots import DIFFICULTIES, make_bot
from yahtzee_app.game import Game, Player, Scorecard


def play_game(bot, rules: str, seed: int) -> int:
    player = Player("Bot", is_bot=True, difficulty=bot.difficulty, card=Scorecard(rules))
    game = Game([player], seed=seed)
    while not game.finished:
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
    return player.card.total()


def main() -> None:
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rules = sys.argv[2] if len(sys.argv) > 2 else "official"
    print(f"{n_games} games per difficulty, rules: {rules}\n")
    for difficulty in DIFFICULTIES:
        bot = make_bot(difficulty, rules)
        t0 = time.time()
        scores = [play_game(bot, rules, seed) for seed in range(n_games)]
        avg = statistics.mean(scores)
        sd = statistics.stdev(scores)
        print(
            f"{difficulty:8s}  avg {avg:6.1f}  sd {sd:5.1f}  "
            f"min {min(scores):3d}  max {max(scores):3d}  "
            f"({time.time() - t0:.0f}s)"
        )


if __name__ == "__main__":
    main()
