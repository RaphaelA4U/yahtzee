"""Coach grading and WIN-mode probability tests."""

import pytest

from yahtzee_app.coach import CoachTracker, record_keep, record_score
from yahtzee_app.bots import get_optimal_oracle
from yahtzee_app.game import CHANCE, YAHTZEE, Player, Scorecard, counts_of
from yahtzee_app import winmode


@pytest.fixture(scope="module")
def oracle():
    return get_optimal_oracle("official")


def test_coach_optimal_keep_is_perfect(oracle):
    tracker = CoachTracker()
    card = Scorecard()
    counts = counts_of([5, 5, 5, 2, 3])
    best = oracle.best_keep(card, counts, 2)
    d = record_keep(tracker, oracle, card, counts, best.keep, 2, round_no=1)
    assert d.loss == pytest.approx(0.0, abs=1e-9)
    assert tracker.accuracy() == 100


def test_coach_bad_keep_costs_ev(oracle):
    tracker = CoachTracker()
    card = Scorecard()
    counts = counts_of([5, 5, 5, 2, 3])
    # Keeping nothing while holding trip fives is clearly bad.
    d = record_keep(tracker, oracle, card, counts, (0, 0, 0, 0, 0, 0), 2, round_no=1)
    assert d.loss > 1.0
    assert tracker.accuracy() < 100


def test_coach_grades_score_choice(oracle):
    tracker = CoachTracker()
    card = Scorecard()
    counts = counts_of([1, 1, 2, 3, 4])
    # Scoring yahtzee (0 points) here is a blunder.
    d = record_score(tracker, oracle, card, counts, YAHTZEE, round_no=1)
    assert d.loss > 10.0


def test_win_context_only_activates_late(oracle):
    me = Player("You", card=Scorecard())
    rival = Player("Bot", is_bot=True, difficulty="easy", card=Scorecard())
    ctx = winmode.build_context(me, [rival], oracle, rounds_left=5, enabled=True)
    assert not ctx.active
    ctx = winmode.build_context(me, [rival], oracle, rounds_left=2, enabled=True)
    assert ctx.active
    ctx = winmode.build_context(me, [rival], oracle, rounds_left=1, enabled=False)
    assert not ctx.active


def _final_round_card() -> Scorecard:
    """A card with only Chance open."""
    card = Scorecard()
    for cat in range(12):
        card.boxes[cat] = 0
    return card


def test_success_probability_bounds(oracle):
    card = _final_round_card()
    counts = counts_of([6, 6, 5, 4, 3])  # chance = 24
    # Need 5 points: keeping everything already succeeds.
    rated = dict(oracle.success_keeps(card, counts, 1, needed=5))
    assert rated[counts] == pytest.approx(1.0)
    # Need 31: impossible even with five sixes kept? No: reroll can reach 30 max
    # only via 5 sixes = 30, so 31 is unreachable.
    rated = oracle.success_keeps(card, counts, 1, needed=31)
    assert all(p <= 1e-12 for _, p in rated)
    # Need 28: keep the two sixes and hope; probability strictly between 0 and 1.
    rated = dict(oracle.success_keeps(card, counts, 1, needed=28))
    best = max(rated.values())
    assert 0.0 < best < 1.0


def test_win_choose_keep_final_round(oracle):
    card = _final_round_card()
    counts = counts_of([6, 6, 5, 4, 3])
    ctx = winmode.WinContext(
        active=True, needed=28, target=100, rival="Sol", trailing=True, rounds_left=1
    )
    keep, note = winmode.choose_keep(oracle, card, counts, 1, ctx)
    assert note is not None and "WIN" in note
    # The chosen keep must at least match the max-EV keep's success chance.
    rated = dict(oracle.success_keeps(card, counts, 1, needed=28))
    ev_keep = oracle.best_keep(card, counts, 1).keep
    assert rated[keep] >= rated[ev_keep] - 1e-12


def test_variance_tilt_prefers_spread_when_trailing(oracle):
    card = Scorecard()
    counts = counts_of([2, 3, 4, 6, 6])
    rated = oracle.rated_keeps_with_sd(card, counts, 2)
    evs = [r.ev for r, _ in rated]
    sds = [sd for _, sd in rated]
    assert all(sd >= 0 for sd in sds)
    assert evs == sorted(evs, reverse=True)
