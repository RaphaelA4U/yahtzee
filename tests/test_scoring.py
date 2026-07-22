"""Rules engine tests: scoring, jokers, bonuses."""

from yahtzee_app.game import (
    CHANCE,
    FIVES,
    FOUR_KIND,
    FULL_HOUSE,
    LG_STRAIGHT,
    ONES,
    SIXES,
    SM_STRAIGHT,
    THREE_KIND,
    THREES,
    YAHTZEE,
    Option,
    Scorecard,
    category_score,
    counts_of,
)


def c(*dice):
    return counts_of(list(dice))


def test_upper_scores():
    assert category_score(ONES, c(1, 1, 2, 3, 4)) == 2
    assert category_score(SIXES, c(6, 6, 6, 2, 1)) == 18
    assert category_score(THREES, c(1, 2, 4, 5, 6)) == 0


def test_lower_scores():
    assert category_score(THREE_KIND, c(3, 3, 3, 2, 1)) == 12
    assert category_score(THREE_KIND, c(3, 3, 2, 2, 1)) == 0
    assert category_score(FOUR_KIND, c(5, 5, 5, 5, 2)) == 22
    assert category_score(FULL_HOUSE, c(2, 2, 3, 3, 3)) == 25
    assert category_score(FULL_HOUSE, c(2, 2, 2, 2, 3)) == 0
    assert category_score(SM_STRAIGHT, c(1, 2, 3, 4, 6)) == 30
    assert category_score(SM_STRAIGHT, c(2, 3, 4, 5, 5)) == 30
    assert category_score(SM_STRAIGHT, c(1, 2, 3, 5, 6)) == 0
    assert category_score(LG_STRAIGHT, c(1, 2, 3, 4, 5)) == 40
    assert category_score(LG_STRAIGHT, c(2, 3, 4, 5, 6)) == 40
    assert category_score(LG_STRAIGHT, c(1, 2, 3, 4, 4)) == 0
    assert category_score(YAHTZEE, c(4, 4, 4, 4, 4)) == 50
    assert category_score(CHANCE, c(1, 2, 3, 4, 5)) == 15


def test_full_house_is_not_five_of_a_kind():
    assert category_score(FULL_HOUSE, c(6, 6, 6, 6, 6)) == 0


def test_upper_bonus():
    card = Scorecard()
    for cat, dice in [
        (0, c(1, 1, 1, 2, 3)),
        (1, c(2, 2, 2, 1, 1)),
        (2, c(3, 3, 3, 1, 1)),
        (3, c(4, 4, 4, 1, 1)),
        (4, c(5, 5, 5, 1, 1)),
    ]:
        card.apply(card.score_option(cat, dice), dice)
    assert card.upper_bonus() == 0
    dice = c(6, 6, 6, 1, 1)
    card.apply(card.score_option(5, dice), dice)
    assert card.upper_subtotal() == 63
    assert card.upper_bonus() == 35


def test_official_joker_forced_upper():
    card = Scorecard("official")
    y = c(3, 3, 3, 3, 3)
    card.boxes[YAHTZEE] = 50
    opts = card.options(y)
    assert len(opts) == 1
    assert opts[0].category == THREES
    assert opts[0].points == 15
    assert opts[0].extra_bonus == 100
    assert opts[0].forced


def test_official_joker_lower_choices():
    card = Scorecard("official")
    card.boxes[YAHTZEE] = 50
    card.boxes[THREES] = 9
    y = c(3, 3, 3, 3, 3)
    opts = card.options(y)
    cats = {o.category for o in opts}
    assert cats == {THREE_KIND, FOUR_KIND, FULL_HOUSE, SM_STRAIGHT, LG_STRAIGHT, CHANCE}
    by_cat = {o.category: o for o in opts}
    assert by_cat[FULL_HOUSE].points == 25
    assert by_cat[SM_STRAIGHT].points == 30
    assert by_cat[LG_STRAIGHT].points == 40
    assert by_cat[THREE_KIND].points == 15
    assert all(o.extra_bonus == 100 for o in opts)


def test_official_joker_no_bonus_after_zeroed_yahtzee():
    card = Scorecard("official")
    card.boxes[YAHTZEE] = 0
    card.boxes[FIVES] = 15
    y = c(5, 5, 5, 5, 5)
    opts = card.options(y)
    assert all(o.extra_bonus == 0 for o in opts)
    assert any(o.category == FULL_HOUSE and o.points == 25 for o in opts)


def test_official_joker_zero_upper_when_all_lower_filled():
    card = Scorecard("official")
    for cat in range(6, 13):
        card.boxes[cat] = 0
    card.boxes[THREES] = 9
    y = c(3, 3, 3, 3, 3)
    opts = card.options(y)
    assert all(o.category < 6 and o.points == 0 for o in opts)
    assert THREES not in {o.category for o in opts}


def test_free_joker_any_open_box():
    card = Scorecard("free_joker")
    card.boxes[YAHTZEE] = 50
    y = c(3, 3, 3, 3, 3)
    opts = card.options(y)
    by_cat = {o.category: o for o in opts}
    # Matching upper box open: FH/straights only at regular value (0).
    assert by_cat[THREES].points == 15
    assert by_cat[FULL_HOUSE].points == 0
    assert all(o.extra_bonus == 100 for o in opts)
    # Once the matching upper box is filled, joker values unlock.
    card.boxes[THREES] = 9
    by_cat = {o.category: o for o in card.options(y)}
    assert by_cat[FULL_HOUSE].points == 25
    assert by_cat[LG_STRAIGHT].points == 40


def test_simple_rules_no_bonus_no_joker():
    card = Scorecard("simple")
    card.boxes[YAHTZEE] = 50
    y = c(3, 3, 3, 3, 3)
    opts = card.options(y)
    by_cat = {o.category: o for o in opts}
    assert all(o.extra_bonus == 0 for o in opts)
    assert by_cat[FULL_HOUSE].points == 0
    assert by_cat[THREE_KIND].points == 15
    assert by_cat[THREES].points == 15
    assert not any(o.forced for o in opts)


def test_yahtzee_bonus_counted_in_total():
    card = Scorecard("official")
    card.boxes[YAHTZEE] = 50
    card.boxes[THREES] = 9
    y = c(3, 3, 3, 3, 3)
    opt = next(o for o in card.options(y) if o.category == CHANCE)
    card.apply(opt, y)
    assert card.yahtzee_bonus_count == 1
    assert card.total() == 50 + 9 + 15 + 100
