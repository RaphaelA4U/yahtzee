"""Hints powered by the optimal solver, explained in plain language.

Hint lines come back as (kind, text) pairs so the UI can style them:
  "main"  the advice itself
  "rule"  the matching rule of thumb from "I Solved Yahtzee*"
  "alt"   compressed alternatives with their EV cost
"""

from __future__ import annotations

from .game import (
    CATEGORY_NAMES,
    Scorecard,
    dice_of,
    is_yahtzee,
)
from .solver.oracle import Oracle

HintLine = tuple[str, str]


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
            return "high pairs (3s-6s) are worth keeping"
        if face is not None and face < 2:
            return None
    if kept == 0 and any(counts[f] == 2 for f in range(2)):
        return "pairs of 1s or 2s are not worth it; reroll everything"
    pairs = [f for f in range(6) if counts[f] == 2]
    if len(pairs) >= 2 and kept <= 2:
        return "never keep two pair at once"
    if kept == 4 and max(keep) == 1 and all(keep[f] for f in (1, 2, 3, 4)):
        return "2345 is the best small straight (open on both ends)"
    if kept == 3 and max(keep) == 1:
        return "preserve straight draws like 234/345"
    if kept >= 3 and max(keep) >= 3:
        return "fill the upper section with 3 or more of a kind"
    return None


def keep_hint(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    rolls_left: int,
    top_n: int = 3,
) -> list[HintLine]:
    """Advice on what to keep, with EV per alternative."""
    rated = oracle.rated_keeps(card, counts, rolls_left)
    best = rated[0]
    lines: list[HintLine] = []
    if best.keep == counts:
        opt = oracle.best_option(card, counts)
        lines.append(
            (
                "main",
                f"Stop and score {CATEGORY_NAMES[opt.option.category]} "
                f"({opt.option.points} pts, EV +{best.ev:.1f})",
            )
        )
    else:
        reroll = sum(counts) - sum(best.keep)
        lines.append(
            (
                "main",
                f"Keep {_fmt_dice(best.keep)}, reroll {reroll} (EV +{best.ev:.1f})",
            )
        )
    rule = _rule_of_thumb(best.keep, counts)
    if rule:
        lines.append(("rule", rule))
    alts = []
    for alt in rated[1:top_n]:
        diff = best.ev - alt.ev
        if diff > 25:
            break
        alts.append(f"keep {_fmt_dice(alt.keep)} ({diff:+.1f})".replace("+", "-", 1))
    if alts:
        lines.append(("alt", "also fine: " + "  ·  ".join(alts)))
    return lines


def option_hint(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    top_n: int = 3,
) -> list[HintLine]:
    """Advice on which box to fill."""
    rated = oracle.rated_options(card, counts)
    best = rated[0]
    o = best.option
    extra = f" +{o.extra_bonus} bonus" if o.extra_bonus else ""
    joker = " via the joker rule" if o.is_joker else ""
    lines: list[HintLine] = [
        (
            "main",
            f"Score {CATEGORY_NAMES[o.category]}: {o.points} pts{extra}{joker} "
            f"(EV after: +{best.ev - o.points - o.extra_bonus:.1f})",
        )
    ]
    alts = []
    for alt in rated[1:top_n]:
        diff = best.ev - alt.ev
        alts.append(
            f"{CATEGORY_NAMES[alt.option.category]} {alt.option.points} pts (-{diff:.1f})"
        )
    if alts:
        lines.append(("alt", "also fine: " + "  ·  ".join(alts)))
    return lines


def hint_for(
    oracle: Oracle,
    card: Scorecard,
    counts: tuple[int, ...],
    rolls_left: int,
) -> list[HintLine]:
    if rolls_left > 0:
        return keep_hint(oracle, card, counts, rolls_left)
    return option_hint(oracle, card, counts)
