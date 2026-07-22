"""Solver tests: reference EVs and solver/rules-engine consistency."""

import random

import numpy as np
import pytest

from yahtzee_app.game import RULESETS, Scorecard, YAHTZEE
from yahtzee_app.solver.build import compute_terminal
from yahtzee_app.solver.core import ALL_ROLLS, ROLL_INDEX
from yahtzee_app.solver.oracle import Oracle
from yahtzee_app.solver.tables import load_table

# Published references: forced joker (official Hasbro), Verhoeff's
# free-choice joker (254.5896), and no-bonus/no-joker play (245.87).
EXPECTED = {
    "official": 254.5877,
    "free_joker": 254.5896,
    "simple": 245.8708,
}


@pytest.mark.parametrize("rules", RULESETS)
def test_reference_ev(rules):
    V = load_table(rules)
    assert V[0, 0, 0] == pytest.approx(EXPECTED[rules], abs=0.002)


def _random_state(rng, rules):
    """A random reachable-ish scorecard state."""
    card = Scorecard(rules)
    n_filled = rng.randrange(0, 13)
    cats = rng.sample(range(13), n_filled)
    upper = 0
    for cat in cats:
        if cat < 6:
            n = rng.randrange(0, 6)
            card.boxes[cat] = n * (cat + 1)
            upper += card.boxes[cat]
        elif cat == YAHTZEE:
            card.boxes[cat] = rng.choice([0, 50])
        else:
            card.boxes[cat] = 0  # value does not matter for the state
    return card


@pytest.mark.parametrize("rules", RULESETS)
def test_terminal_matches_rules_engine(rules):
    """The vectorized solver and the rules engine must agree exactly.

    For random states and all 252 rolls, compute_terminal's best value must
    equal the best (points + bonus + V[next]) over Scorecard.options().
    """
    V = load_table(rules)
    oracle = Oracle(V, rules)
    rng = random.Random(42)
    for _ in range(60):
        card = _random_state(rng, rules)
        if card.is_full():
            continue
        mask, upper, flag = card.mask(), card.capped_upper(), card.yahtzee_flag()
        A = compute_terminal(mask, V, rules)
        for counts in ALL_ROLLS:
            best = max(
                oracle.option_value(card, opt, mask, upper, flag)
                for opt in card.options(counts)
            )
            got = A[ROLL_INDEX[counts], upper, flag]
            assert got == pytest.approx(best, abs=1e-9), (
                f"mismatch rules={rules} mask={mask:013b} upper={upper} "
                f"flag={flag} roll={counts}"
            )


def test_keep_all_is_stop_and_score():
    """Keeping all five dice must equal the best category value."""
    V = load_table("official")
    oracle = Oracle(V, "official")
    card = Scorecard("official")
    counts = (0, 0, 2, 3, 0, 0)  # 3 3 4 4 4
    rated = oracle.rated_keeps(card, counts, rolls_left=1)
    keep_all = next(r for r in rated if r.keep == counts)
    best_option = oracle.best_option(card, counts)
    assert keep_all.ev == pytest.approx(best_option.ev, abs=1e-9)


def test_more_rolls_never_worse():
    """With 2 rolls left the best keep EV is >= with 1 roll left."""
    V = load_table("official")
    oracle = Oracle(V, "official")
    card = Scorecard("official")
    rng = random.Random(7)
    for _ in range(20):
        counts = ALL_ROLLS[rng.randrange(len(ALL_ROLLS))]
        ev1 = oracle.best_keep(card, counts, 1).ev
        ev2 = oracle.best_keep(card, counts, 2).ev
        assert ev2 >= ev1 - 1e-9
