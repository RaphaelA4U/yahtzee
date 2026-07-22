"""Query layer on top of the value table: best moves during play.

The Oracle answers two questions for a concrete game situation:
1. Which category do I pick for this final roll (with EV per option)?
2. Which dice do I keep (with EV per keep)?

Category logic goes through game.Scorecard.options() so the solver and the
rules engine are guaranteed to see the same choices. Keep analysis reuses
the terminal vector from build.compute_terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..game import (
    UPPER_BONUS,
    UPPER_BONUS_THRESHOLD,
    YAHTZEE,
    YAHTZEE_SCORE,
    Option,
    Scorecard,
)
from .build import compute_terminal
from .core import KEEP_INDEX, KEEP_MATRIX, ROLL_INDEX, SUBSETS, keeps_of_roll


@dataclass(frozen=True)
class RatedOption:
    option: Option
    ev: float  # expected total remaining points for this choice


@dataclass(frozen=True)
class RatedKeep:
    keep: tuple[int, ...]  # counts tuple of dice to hold
    ev: float


class Oracle:
    """Best moves according to a value table V with shape (8192, 64, 2)."""

    def __init__(self, V: np.ndarray, rules: str = "official") -> None:
        self.V = V
        self.rules = rules
        self._terminal_cache: dict[int, np.ndarray] = {}

    # -- states ------------------------------------------------------------

    def state_value(self, mask: int, upper: int, flag: int) -> float:
        return float(self.V[mask, upper, flag])

    def option_value(
        self, card: Scorecard, option: Option, mask: int, upper: int, flag: int
    ) -> float:
        """Points now + expected future value after this choice."""
        cat = option.category
        nmask = mask | (1 << cat)
        points = float(option.points + option.extra_bonus)
        nu, nflag = upper, flag
        if cat < 6:
            total = upper + option.points
            if upper < UPPER_BONUS_THRESHOLD <= total:
                points += UPPER_BONUS
            nu = min(total, UPPER_BONUS_THRESHOLD)
        elif cat == YAHTZEE and option.points >= YAHTZEE_SCORE:
            nflag = 1
        return points + float(self.V[nmask, nu, nflag])

    # -- choosing a category -------------------------------------------------

    def rated_options(self, card: Scorecard, counts: tuple[int, ...]) -> list[RatedOption]:
        mask, upper, flag = card.mask(), card.capped_upper(), card.yahtzee_flag()
        rated = [
            RatedOption(opt, self.option_value(card, opt, mask, upper, flag))
            for opt in card.options(counts)
        ]
        rated.sort(key=lambda r: r.ev, reverse=True)
        return rated

    def best_option(self, card: Scorecard, counts: tuple[int, ...]) -> RatedOption:
        return self.rated_options(card, counts)[0]

    # -- choosing keeps ------------------------------------------------------

    def _terminal_vector(self, card: Scorecard) -> np.ndarray:
        """A[roll] for the current card: value of every possible final roll."""
        mask, upper, flag = card.mask(), card.capped_upper(), card.yahtzee_flag()
        A = self._terminal_cache.get(mask)
        if A is None:
            A = compute_terminal(mask, self.V, self.rules)
            self._terminal_cache = {mask: A}  # one entry suffices (per turn)
        return A[:, upper, flag]

    def rated_keeps(
        self, card: Scorecard, counts: tuple[int, ...], rolls_left: int
    ) -> list[RatedKeep]:
        """EV per possible keep for the current roll.

        rolls_left = number of rolls still available (1 or 2).
        Keeping everything = stop now and score.
        """
        if rolls_left < 1:
            raise ValueError("No rolls left; pick a category")
        value = self._terminal_vector(card)  # value with 0 rolls left
        # Lift the value function one level at a time until we can rate the
        # keeps of the current roll.
        for _ in range(rolls_left - 1):
            ek = KEEP_MATRIX @ value
            nxt = np.empty_like(value)
            for i, subs in enumerate(SUBSETS):
                nxt[i] = ek[subs].max()
            value = nxt
        ek = KEEP_MATRIX @ value  # EV per keep (462,)
        rated = [
            RatedKeep(tuple(keep), float(ek[KEEP_INDEX[keep]]))
            for keep in keeps_of_roll(counts)
        ]
        rated.sort(key=lambda r: r.ev, reverse=True)
        return rated

    def best_keep(
        self, card: Scorecard, counts: tuple[int, ...], rolls_left: int
    ) -> RatedKeep:
        return self.rated_keeps(card, counts, rolls_left)[0]

    def turn_start_ev(self, card: Scorecard) -> float:
        """Expected remaining points at the start of the turn."""
        return self.state_value(card.mask(), card.capped_upper(), card.yahtzee_flag())
