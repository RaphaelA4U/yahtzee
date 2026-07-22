"""Yahtzee rules engine.

This is the single source of truth for the rules (scoring, joker rules,
bonuses). Both the solver and the UI build on top of this module.

Dice are represented everywhere as a "counts" tuple of length 6:
counts[i] = number of dice showing face i+1.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

# Category indices
ONES, TWOS, THREES, FOURS, FIVES, SIXES = range(6)
THREE_KIND, FOUR_KIND, FULL_HOUSE, SM_STRAIGHT, LG_STRAIGHT, YAHTZEE, CHANCE = range(6, 13)

N_CATEGORIES = 13
UPPER = tuple(range(6))
LOWER = tuple(range(6, 13))
UPPER_BONUS_THRESHOLD = 63
UPPER_BONUS = 35
YAHTZEE_SCORE = 50
YAHTZEE_EXTRA_BONUS = 100

CATEGORY_NAMES = [
    "Ones", "Twos", "Threes", "Fours", "Fives", "Sixes",
    "Three of a Kind", "Four of a Kind", "Full House", "Small Straight",
    "Large Straight", "Yahtzee", "Chance",
]

CATEGORY_SHORT = [
    "1", "2", "3", "4", "5", "6",
    "3K", "4K", "FH", "SS", "LS", "Y", "C",
]

# Rule variants (game modes). "official" is the default.
RULESETS = ["official", "free_joker", "simple"]

RULESET_LABELS = {
    "official": "Official",
    "free_joker": "Free joker",
    "simple": "Simple",
}

RULESET_INFO = {
    "official": (
        "Official Hasbro rules: 100-point bonus for every extra Yahtzee "
        "(if the Yahtzee box holds 50) and forced joker rules."
    ),
    "free_joker": (
        "Like official, but an extra Yahtzee may go in any open box; "
        "Full House and straights count full joker value once your matching "
        "upper box is filled."
    ),
    "simple": (
        "Common house rules: no Yahtzee bonuses, no jokers. An extra Yahtzee "
        "is just a normal roll (Yahtzee scores once)."
    ),
}


def counts_of(dice: list[int]) -> tuple[int, ...]:
    """Convert a list of die values (1-6) to a counts tuple."""
    c = [0] * 6
    for d in dice:
        c[d - 1] += 1
    return tuple(c)


def dice_of(counts: tuple[int, ...]) -> list[int]:
    """Counts tuple back to a sorted list of die values."""
    out: list[int] = []
    for face, n in enumerate(counts):
        out.extend([face + 1] * n)
    return out


def dice_sum(counts: tuple[int, ...]) -> int:
    return sum((face + 1) * n for face, n in enumerate(counts))


def is_yahtzee(counts: tuple[int, ...]) -> bool:
    return max(counts) == 5


def yahtzee_face(counts: tuple[int, ...]) -> int:
    """Face index (0-5) of a yahtzee roll."""
    return counts.index(5)


def has_straight(counts: tuple[int, ...], length: int) -> bool:
    run = 0
    for n in counts:
        if n > 0:
            run += 1
            if run >= length:
                return True
        else:
            run = 0
    return False


def category_score(cat: int, counts: tuple[int, ...]) -> int:
    """Regular score of a category for this roll (without joker rules)."""
    if cat in UPPER:
        return counts[cat] * (cat + 1)
    if cat == THREE_KIND:
        return dice_sum(counts) if max(counts) >= 3 else 0
    if cat == FOUR_KIND:
        return dice_sum(counts) if max(counts) >= 4 else 0
    if cat == FULL_HOUSE:
        return 25 if (3 in counts and 2 in counts) else 0
    if cat == SM_STRAIGHT:
        return 30 if has_straight(counts, 4) else 0
    if cat == LG_STRAIGHT:
        return 40 if has_straight(counts, 5) else 0
    if cat == YAHTZEE:
        return YAHTZEE_SCORE if is_yahtzee(counts) else 0
    if cat == CHANCE:
        return dice_sum(counts)
    raise ValueError(f"Unknown category {cat}")


def joker_score(cat: int, counts: tuple[int, ...]) -> int:
    """Score of a lower category under the joker rule (yahtzee as joker)."""
    if cat == FULL_HOUSE:
        return 25
    if cat == SM_STRAIGHT:
        return 30
    if cat == LG_STRAIGHT:
        return 40
    # Three of a Kind, Four of a Kind, Chance: sum of all dice
    return dice_sum(counts)


@dataclass(frozen=True)
class Option:
    """A possible scoring choice for the current roll."""

    category: int
    points: int
    extra_bonus: int = 0     # 100-point bonus for an extra yahtzee
    is_joker: bool = False   # placed via the joker rule
    forced: bool = False     # mandatory choice (forced by the joker rule)


class Scorecard:
    """One player's scorecard, including joker and bonus logic."""

    def __init__(self, rules: str = "official") -> None:
        if rules not in RULESETS:
            raise ValueError(f"Unknown ruleset: {rules}")
        self.rules = rules
        self.boxes: list[Optional[int]] = [None] * N_CATEGORIES
        self.yahtzee_bonus_count = 0

    # -- derived totals ----------------------------------------------------

    def upper_subtotal(self) -> int:
        return sum(self.boxes[c] or 0 for c in UPPER)

    def upper_bonus(self) -> int:
        return UPPER_BONUS if self.upper_subtotal() >= UPPER_BONUS_THRESHOLD else 0

    def lower_total(self) -> int:
        return sum(self.boxes[c] or 0 for c in LOWER)

    def total(self) -> int:
        return (
            self.upper_subtotal()
            + self.upper_bonus()
            + self.lower_total()
            + self.yahtzee_bonus_count * YAHTZEE_EXTRA_BONUS
        )

    def is_full(self) -> bool:
        return all(b is not None for b in self.boxes)

    def open_categories(self) -> list[int]:
        return [c for c in range(N_CATEGORIES) if self.boxes[c] is None]

    # -- solver state ------------------------------------------------------

    def mask(self) -> int:
        m = 0
        for c in range(N_CATEGORIES):
            if self.boxes[c] is not None:
                m |= 1 << c
        return m

    def capped_upper(self) -> int:
        return min(self.upper_subtotal(), UPPER_BONUS_THRESHOLD)

    def yahtzee_flag(self) -> int:
        return 1 if (self.boxes[YAHTZEE] or 0) >= YAHTZEE_SCORE else 0

    # -- choices -----------------------------------------------------------

    def options(self, counts: tuple[int, ...]) -> list[Option]:
        """All legal choices for this roll, per the active ruleset.

        Official rules for an extra yahtzee (yahtzee box already filled):
        1. +100 bonus if the yahtzee box holds 50 (not if it holds 0).
        2. You MUST score in the matching upper box if it is open.
        3. Otherwise: free choice among open lower boxes, at full joker
           value (Full House 25, Small Straight 30, Large Straight 40,
           the rest sum of dice).
        4. If none of those are open: enter a zero in an open upper box.

        Free joker: free choice among all open boxes; FH/SS/LS count full
        joker value once the matching upper box is filled.

        Simple: no bonuses and no jokers; every roll scores regular values.
        """
        open_cats = self.open_categories()
        if not open_cats:
            return []

        extra_yahtzee = is_yahtzee(counts) and self.boxes[YAHTZEE] is not None
        if extra_yahtzee and self.rules == "official":
            bonus = YAHTZEE_EXTRA_BONUS if self.yahtzee_flag() else 0
            face = yahtzee_face(counts)
            if self.boxes[face] is None:
                return [Option(face, (face + 1) * 5, bonus, is_joker=True, forced=True)]
            lower_open = [c for c in LOWER if self.boxes[c] is None]
            if lower_open:
                return [
                    Option(c, joker_score(c, counts), bonus, is_joker=True)
                    for c in lower_open
                ]
            return [
                Option(c, 0, bonus, is_joker=True)
                for c in UPPER
                if self.boxes[c] is None
            ]
        if extra_yahtzee and self.rules == "free_joker":
            bonus = YAHTZEE_EXTRA_BONUS if self.yahtzee_flag() else 0
            face = yahtzee_face(counts)
            joker_ok = self.boxes[face] is not None
            out = []
            for c in open_cats:
                if c in (FULL_HOUSE, SM_STRAIGHT, LG_STRAIGHT) and joker_ok:
                    out.append(Option(c, joker_score(c, counts), bonus, is_joker=True))
                else:
                    out.append(Option(c, category_score(c, counts), bonus))
            return out

        return [Option(c, category_score(c, counts)) for c in open_cats]

    def apply(self, option: Option, counts: tuple[int, ...]) -> None:
        """Apply a choice to the card."""
        if self.boxes[option.category] is not None:
            raise ValueError(f"Category {option.category} is already filled")
        self.boxes[option.category] = option.points
        if option.extra_bonus:
            self.yahtzee_bonus_count += 1

    def score_option(self, cat: int, counts: tuple[int, ...]) -> Option:
        """Find the Option for a specific category (or raise if not allowed)."""
        for opt in self.options(counts):
            if opt.category == cat:
                return opt
        raise ValueError(f"{CATEGORY_NAMES[cat]} is not a legal choice right now")


@dataclass
class Player:
    name: str
    is_bot: bool = False
    difficulty: Optional[str] = None  # None for humans
    card: Scorecard = field(default_factory=Scorecard)


class TurnState:
    """One player's turn: up to 3 rolls, holding dice, then scoring."""

    MAX_ROLLS = 3

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self.rng = rng or random.Random()
        self.dice: list[int] = [1] * 5
        self.held: list[bool] = [False] * 5
        self.rolls_used = 0

    @property
    def rolls_left(self) -> int:
        return self.MAX_ROLLS - self.rolls_used

    def can_roll(self) -> bool:
        return self.rolls_left > 0 and (self.rolls_used == 0 or not all(self.held))

    def roll(self) -> None:
        if self.rolls_left <= 0:
            raise ValueError("No rolls left")
        for i in range(5):
            if self.rolls_used == 0 or not self.held[i]:
                self.dice[i] = self.rng.randint(1, 6)
        self.rolls_used += 1

    def toggle_hold(self, idx: int) -> None:
        if self.rolls_used == 0:
            raise ValueError("Roll first")
        self.held[idx] = not self.held[idx]

    def set_holds_for(self, keep_counts: tuple[int, ...]) -> None:
        """Set holds so that exactly `keep_counts` is held (for bots/auto)."""
        remaining = list(keep_counts)
        for i, d in enumerate(self.dice):
            if remaining[d - 1] > 0:
                self.held[i] = True
                remaining[d - 1] -= 1
            else:
                self.held[i] = False

    def counts(self) -> tuple[int, ...]:
        return counts_of(self.dice)

    def held_counts(self) -> tuple[int, ...]:
        return counts_of([d for d, h in zip(self.dice, self.held) if h])


class Game:
    """A full game: players, rounds, turn order."""

    ROUNDS = N_CATEGORIES

    def __init__(self, players: list[Player], seed: Optional[int] = None) -> None:
        if not players:
            raise ValueError("At least 1 player required")
        self.players = players
        self.rng = random.Random(seed)
        self.round = 1
        self.current_idx = 0
        self.turn = TurnState(self.rng)
        self.finished = False

    @property
    def current(self) -> Player:
        return self.players[self.current_idx]

    def advance(self) -> None:
        """Move to the next player / round after a scored turn."""
        self.current_idx += 1
        if self.current_idx >= len(self.players):
            self.current_idx = 0
            self.round += 1
            if self.round > self.ROUNDS:
                self.finished = True
                return
        self.turn = TurnState(self.rng)

    def rankings(self) -> list[tuple[Player, int]]:
        ranked = sorted(self.players, key=lambda p: p.card.total(), reverse=True)
        return [(p, p.card.total()) for p in ranked]
