"""Coach: track every human decision, measure EV loss, grade the game.

Every keep and category decision is compared against the optimal solver.
COACH mode shows the verdict right after each decision; the post-game
review lists them all, worst first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .game import CATEGORY_NAMES, Scorecard, dice_of
from .solver.oracle import Oracle


@dataclass
class Decision:
    round: int
    kind: str          # "keep" | "score"
    dice: str          # the roll as text
    chosen: str
    best: str
    loss: float        # EV points given away (0 = perfect)


@dataclass
class CoachTracker:
    decisions: list[Decision] = field(default_factory=list)

    @property
    def total_loss(self) -> float:
        return sum(d.loss for d in self.decisions)

    def accuracy(self) -> int:
        """Chess-style accuracy: 100 for perfect play, decaying with EV loss."""
        return round(100 * math.exp(-self.total_loss / 40))

    def worst(self, n: int = 5) -> list[Decision]:
        return sorted(self.decisions, key=lambda d: d.loss, reverse=True)[:n]


def _fmt_keep(keep: tuple[int, ...]) -> str:
    if sum(keep) == 0:
        return "reroll all"
    return "keep " + " ".join(str(d) for d in dice_of(keep))


def record_keep(
    tracker: CoachTracker,
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    chosen_keep: tuple[int, ...],
    rolls_left: int,
    round_no: int,
) -> Decision:
    """Grade a committed keep decision (called right before the reroll)."""
    rated = oracle.rated_keeps(card, counts, rolls_left)
    best = rated[0]
    chosen_ev = next(r.ev for r in rated if r.keep == chosen_keep)
    decision = Decision(
        round=round_no,
        kind="keep",
        dice=" ".join(str(d) for d in dice_of(counts)),
        chosen=_fmt_keep(chosen_keep),
        best=_fmt_keep(best.keep),
        loss=max(0.0, best.ev - chosen_ev),
    )
    tracker.decisions.append(decision)
    return decision


def record_score(
    tracker: CoachTracker,
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    chosen_cat: int,
    round_no: int,
    rolls_left: int = 0,
) -> Decision:
    """Grade a category choice.

    If the player still had rolls left, the reference is the best keep
    (which includes stopping), so cashing in too early is graded too.
    """
    rated = oracle.rated_options(card, counts)
    best_opt = rated[0]
    chosen_ev = next(r.ev for r in rated if r.option.category == chosen_cat)
    best_ev = best_opt.ev
    best_desc = f"score {CATEGORY_NAMES[best_opt.option.category]}"
    if rolls_left > 0:
        best_keep = oracle.best_keep(card, counts, rolls_left)
        if best_keep.ev > best_ev + 1e-9 and best_keep.keep != counts:
            best_ev = best_keep.ev
            best_desc = _fmt_keep(best_keep.keep) + " and roll on"
    decision = Decision(
        round=round_no,
        kind="score",
        dice=" ".join(str(d) for d in dice_of(counts)),
        chosen=f"score {CATEGORY_NAMES[chosen_cat]}",
        best=best_desc,
        loss=max(0.0, best_ev - chosen_ev),
    )
    tracker.decisions.append(decision)
    return decision


def verdict_line(decision: Decision) -> str:
    """One-line COACH feedback for a decision."""
    if decision.loss < 0.05:
        return f"Coach: {decision.chosen} was perfect."
    return (
        f"Coach: {decision.chosen} lost {decision.loss:.1f} EV; "
        f"best was {decision.best}."
    )
