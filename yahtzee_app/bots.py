"""Bot opponents at four levels.

- easy:    naively holds the most common face, takes the highest
           immediate score.
- medium:  plays the rules of thumb from "I Solved Yahtzee*" (Ballpark
           Figures): keep high pairs (3s-6s), no low pairs or two-pair,
           2345 over other small straights, fill the upper section with
           three-of-a-kind rolls, preserve option boxes (Chance/straights).
- hard:    exact per-turn EV maximization with a heuristic value for the
           rest of the game.
- optimal: the full dynamic-programming table (as in the video);
           maximizes the expected final score.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .game import (
    CHANCE,
    FOUR_KIND,
    FULL_HOUSE,
    LG_STRAIGHT,
    SM_STRAIGHT,
    THREE_KIND,
    UPPER_BONUS_THRESHOLD,
    YAHTZEE,
    Option,
    Scorecard,
    category_score,
    dice_sum,
    has_straight,
    is_yahtzee,
)
from .solver.oracle import Oracle

DIFFICULTIES = ["easy", "medium", "hard", "optimal"]

DIFFICULTY_LABELS = {
    "easy": "Easy",
    "medium": "Medium",
    "hard": "Hard",
    "optimal": "Optimal",
}

DIFFICULTY_INFO = {
    "easy": "Plays by feel: holds the most common face, grabs the highest score.",
    "medium": "Follows the rules of thumb from the video I Solved Yahtzee* (Ballpark Figures).",
    "hard": "Calculates every turn exactly, estimates the rest of the game.",
    "optimal": "The full solver from the video: maximizes expected final score (~255 average).",
}

BOT_NAMES = {
    "easy": "Ben",
    "medium": "Meg",
    "hard": "Hank",
    "optimal": "Sol",
}

# Average yield per category under strong play (Verhoeff), used as a measure
# of what you give up by filling or dumping a box.
BASELINE = np.array([
    1.88, 5.28, 8.57, 12.16, 15.69, 19.19,   # ones through sixes
    21.66, 13.10, 22.59, 29.46, 32.71,        # 3 of a kind, 4 of a kind, FH, SS, LS
    16.87, 22.01,                             # yahtzee, chance
])


class Bot:
    """Interface: choose what to keep and which category to score."""

    difficulty = "?"

    def choose_keep(
        self, card: Scorecard, counts: tuple[int, ...], rolls_left: int
    ) -> tuple[int, ...]:
        """Counts tuple of dice to keep. Keeping everything = stop rolling."""
        raise NotImplementedError

    def choose_option(self, card: Scorecard, counts: tuple[int, ...]) -> Option:
        raise NotImplementedError


class EasyBot(Bot):
    difficulty = "easy"

    def choose_keep(self, card, counts, rolls_left):
        if is_yahtzee(counts) or has_straight(counts, 5):
            return counts
        # Hold the most common face; ties go to the highest face.
        best_face = max(range(6), key=lambda f: (counts[f], f))
        keep = [0] * 6
        keep[best_face] = counts[best_face]
        return tuple(keep)

    def choose_option(self, card, counts):
        options = card.options(counts)
        best = max(options, key=lambda o: o.points)
        if best.points > 0:
            return best
        # Nothing scores: cross out the topmost open box.
        return min(options, key=lambda o: o.category)


class MediumBot(Bot):
    """The video's rules of thumb, translated into a decision tree."""

    difficulty = "medium"

    def choose_keep(self, card, counts, rolls_left):
        boxes = card.boxes
        # Done is done: yahtzee, large straight, full house.
        if is_yahtzee(counts):
            return counts
        if has_straight(counts, 5) and boxes[LG_STRAIGHT] is None:
            return counts
        if 3 in counts and 2 in counts and boxes[FULL_HOUSE] is None:
            return counts

        top = max(counts)
        best_face = max(range(6), key=lambda f: (counts[f], f))

        # Four or three of a kind: keep them (the video keeps low triples
        # only without a full-house draw; we approximate that nuance by
        # keeping low triples once Full House is already gone).
        if top >= 4:
            keep = [0] * 6
            keep[best_face] = counts[best_face]
            return tuple(keep)

        # Completed small straight: keep it; with Large Straight still open
        # we reroll the spare die chasing the large straight.
        if has_straight(counts, 4) and boxes[SM_STRAIGHT] is None:
            return self._straight_keep(counts, 4)
        if has_straight(counts, 4) and boxes[LG_STRAIGHT] is None:
            return self._straight_keep(counts, 4)

        if top == 3:
            keep = [0] * 6
            keep[best_face] = 3
            return tuple(keep)

        # Preserve straight draws: 234 or 345 (video: prioritize 2345).
        if boxes[SM_STRAIGHT] is None or boxes[LG_STRAIGHT] is None:
            for run in ((1, 2, 3), (2, 3, 4)):  # faces for 234 and 345
                if all(counts[f] > 0 for f in run):
                    keep = [0] * 6
                    for f in run:
                        keep[f] = 1
                    return tuple(keep)

        # Pairs: only high pairs (3s-6s), never two pair at once.
        pair_faces = [f for f in range(6) if counts[f] == 2 and f >= 2]
        if pair_faces:
            f = max(pair_faces)
            keep = [0] * 6
            keep[f] = 2
            return tuple(keep)

        # Loose high dice (video: an upper-section die is worth ~3x its face).
        keep = [0] * 6
        for f in (5, 4):
            if counts[f] > 0 and boxes[f] is None:
                keep[f] = counts[f]
                return tuple(keep)
        return tuple(keep)

    def _straight_keep(self, counts, length):
        # Keep a straight of `length`, preferring the run that contains 2345;
        # remaining dice get rerolled.
        keep = [0] * 6
        run: list[int] = []
        best_run: list[int] = []
        for f in range(6):
            if counts[f] > 0:
                run.append(f)
                if len(run) >= len(best_run):
                    best_run = list(run)
            else:
                run = []
        for f in best_run[-5:] if len(best_run) > length else best_run[:length] or best_run:
            keep[f] = 1
        # Prefer 2345: if faces 2-5 are all present, keep exactly those.
        if all(counts[f] > 0 for f in (1, 2, 3, 4)):
            keep = [0] * 6
            for f in (1, 2, 3, 4):
                keep[f] = 1
        return tuple(keep)

    def choose_option(self, card, counts):
        options = card.options(counts)
        if len(options) == 1:
            return options[0]

        def utility(o: Option) -> float:
            pts = float(o.points + o.extra_bonus)
            # Upper section: count progress toward the bonus.
            if o.category < 6:
                before = card.upper_subtotal()
                after = before + o.points
                if before < UPPER_BONUS_THRESHOLD <= after:
                    pts += 35
                # Video: prefer filling upper boxes with 3+ dice.
                if o.points >= 3 * (o.category + 1):
                    pts += 4
            # What do you give up by using this box now?
            return pts - 0.55 * float(BASELINE[o.category])

        return max(options, key=utility)


class OracleBot(Bot):
    """Shared base for the calculating bots."""

    def __init__(self, oracle: Oracle) -> None:
        self.oracle = oracle

    def choose_keep(self, card, counts, rolls_left):
        return self.oracle.best_keep(card, counts, rolls_left).keep

    def choose_option(self, card, counts):
        return self.oracle.best_option(card, counts).option


class HardBot(OracleBot):
    difficulty = "hard"


class OptimalBot(OracleBot):
    difficulty = "optimal"


def heuristic_table() -> np.ndarray:
    """Heuristic V table for the hard bot: baselines + bonus estimate."""
    n_masks = 1 << 13
    V = np.zeros((n_masks, 64, 2), dtype=np.float64)
    u = np.arange(64, dtype=np.float64)
    for mask in range(n_masks):
        open_cats = [c for c in range(13) if not mask & (1 << c)]
        base = float(sum(BASELINE[c] for c in open_cats))
        open_upper = [c for c in open_cats if c < 6]
        if open_upper:
            potential = float(sum(BASELINE[c] for c in open_upper))
            p = np.clip(0.5 + (u + potential - 63.0) / 25.0, 0.0, 1.0)
            p[63:] = 0.0  # bonus already banked (paid out when crossing 63)
            bonus_term = 35.0 * p
        else:
            bonus_term = np.zeros(64)
        V[mask, :, 0] = base + bonus_term
        V[mask, :, 1] = base + bonus_term
    return V


_heuristic_table: Optional[np.ndarray] = None
_heuristic_oracles: dict[str, Oracle] = {}
_optimal_oracles: dict[str, Oracle] = {}


def get_optimal_oracle(rules: str = "official") -> Oracle:
    if rules not in _optimal_oracles:
        from .solver.tables import load_table

        _optimal_oracles[rules] = Oracle(load_table(rules), rules)
    return _optimal_oracles[rules]


def make_bot(difficulty: str, rules: str = "official") -> Bot:
    if difficulty == "easy":
        return EasyBot()
    if difficulty == "medium":
        return MediumBot()
    if difficulty == "hard":
        global _heuristic_table
        if rules not in _heuristic_oracles:
            if _heuristic_table is None:
                _heuristic_table = heuristic_table()
            _heuristic_oracles[rules] = Oracle(_heuristic_table, rules)
        return HardBot(_heuristic_oracles[rules])
    if difficulty == "optimal":
        return OptimalBot(get_optimal_oracle(rules))
    raise ValueError(f"Unknown difficulty: {difficulty}")
