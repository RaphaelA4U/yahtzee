"""Hints powered by the optimal solver, explained in plain language.

Where the advice matches a rule of thumb from "I Solved Yahtzee*"
(Ballpark Figures) we call out that rule explicitly.
"""

from __future__ import annotations

from .game import (
    CATEGORY_NAMES,
    Scorecard,
    dice_of,
    is_yahtzee,
)
from .solver.oracle import Oracle


def _fmt_dice(counts: tuple[int, ...]) -> str:
    if sum(counts) == 0:
        return "nothing"
    return " ".join(str(d) for d in dice_of(counts))


def _rule_of_thumb(keep: tuple[int, ...], counts: tuple[int, ...]) -> str | None:
    """Recognize the video rule of thumb that matches this advice."""
    kept = sum(keep)
    if is_yahtzee(counts):
        return None
    if kept == 2:
        face = next((f for f in range(6) if keep[f] == 2), None)
        if face is not None and face >= 2:
            return "Rule of thumb: high pairs (3s-6s) are worth keeping."
        if face is not None and face < 2:
            return None
    if kept == 0 and any(counts[f] == 2 for f in range(2)):
        return "Rule of thumb: pairs of 1s or 2s are not worth it; reroll everything."
    pairs = [f for f in range(6) if counts[f] == 2]
    if len(pairs) >= 2 and kept <= 2:
        return "Rule of thumb: never keep two pair at once."
    if kept == 4 and max(keep) == 1 and all(keep[f] for f in (1, 2, 3, 4)):
        return "Rule of thumb: 2345 is the best small straight (open on both ends)."
    if kept == 3 and max(keep) == 1:
        return "Rule of thumb: preserve straight draws like 234/345."
    if kept >= 3 and max(keep) >= 3:
        return "Rule of thumb: fill the upper section with 3 or more of a kind."
    return None


def keep_hint(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    rolls_left: int,
    top_n: int = 3,
) -> list[str]:
    """Advice on what to keep, with EV per alternative."""
    rated = oracle.rated_keeps(card, counts, rolls_left)
    best = rated[0]
    lines: list[str] = []
    if best.keep == counts:
        opt = oracle.best_option(card, counts)
        lines.append(
            f"Stop rolling and score {CATEGORY_NAMES[opt.option.category]} "
            f"({opt.option.points} pts). Expected value: +{best.ev:.1f} points."
        )
    else:
        reroll = sum(counts) - sum(best.keep)
        lines.append(
            f"Keep {_fmt_dice(best.keep)} and reroll {reroll}. "
            f"Expected value: +{best.ev:.1f} points."
        )
    rule = _rule_of_thumb(best.keep, counts)
    if rule:
        lines.append(rule)
    for alt in rated[1:top_n]:
        diff = best.ev - alt.ev
        if diff > 25:
            break
        lines.append(
            f"  alternative: keep {_fmt_dice(alt.keep)} (EV +{alt.ev:.1f}, -{diff:.1f})"
        )
    return lines


def option_hint(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    top_n: int = 3,
) -> list[str]:
    """Advice on which category to score."""
    rated = oracle.rated_options(card, counts)
    best = rated[0]
    o = best.option
    extra = f" (+{o.extra_bonus} bonus)" if o.extra_bonus else ""
    joker = " via the joker rule" if o.is_joker else ""
    lines = [
        f"Score {CATEGORY_NAMES[o.category]}: {o.points} points{extra}{joker}. "
        f"Expected value after: +{best.ev - o.points - o.extra_bonus:.1f} points."
    ]
    for alt in rated[1:top_n]:
        diff = best.ev - alt.ev
        lines.append(
            f"  alternative: {CATEGORY_NAMES[alt.option.category]} "
            f"({alt.option.points} pts, EV -{diff:.1f})"
        )
    return lines


def hint_for(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    rolls_left: int,
) -> list[str]:
    if rolls_left > 0:
        return keep_hint(oracle, card, counts, rolls_left)
    return option_hint(oracle, card, counts)
