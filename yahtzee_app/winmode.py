"""WIN mode: play for the win, not for maximum points.

The video's asterisk: maximizing expected score is not the same as
maximizing win probability in a multiplayer game. This module adds a
practical endgame layer on top of the EV solver:

- Final round: exact. We compute the probability of reaching the target
  (the best opponent's projected final score) for every keep, via the
  within-turn DP on a success indicator.
- Second-to-last round: variance tilt. Among keeps within a small EV band
  of the best, prefer high variance when trailing and low variance when
  leading.
- Earlier rounds: EV play is effectively optimal; WIN mode stays quiet.
"""

from __future__ import annotations

from dataclasses import dataclass

from .game import Player
from .solver.oracle import Oracle

# Tunables, set by arena experiments (tools/arena.py, 3000-match runs):
# exact final-round win-probability play alone scored best (51.25% vs pure
# EV head-to-head); the earlier-round variance tilt consistently HURT the
# win rate, so it is off by default (WIN_ROUNDS=1 never reaches it).
WIN_ROUNDS = 1
EV_BAND = 1.5
TILT_WHEN_LEADING = False


@dataclass
class WinContext:
    active: bool
    needed: float = 0.0       # points this turn must produce (final round)
    target: float = 0.0       # projected score to beat
    rival: str = ""           # name of the projected best opponent
    trailing: bool = False
    rounds_left: int = 0


def build_context(
    me: Player,
    opponents: list[Player],
    oracle: Oracle,
    rounds_left: int,
    enabled: bool,
) -> WinContext:
    """Assess the standings. Only activates near the end of the game."""
    if not enabled or not opponents or rounds_left > WIN_ROUNDS:
        return WinContext(active=False)
    # Match totals: in a multi-game match earlier columns count too. For a
    # single game match_total() equals the current card total.
    projections = [
        (p.match_total() + oracle_for(p, oracle).turn_start_ev(p.card), p.name)
        for p in opponents
    ]
    target, rival = max(projections)
    my_projection = me.match_total() + oracle.turn_start_ev(me.card)
    needed = target - me.match_total()
    return WinContext(
        active=True,
        needed=needed,
        target=target,
        rival=rival,
        trailing=my_projection < target,
        rounds_left=rounds_left,
    )


def oracle_for(player: Player, fallback: Oracle) -> Oracle:
    """Opponents are projected with the same (optimal) oracle."""
    return fallback


def choose_keep(
    oracle: Oracle,
    card,
    counts: tuple[int, ...],
    rolls_left: int,
    ctx: WinContext,
) -> tuple[tuple[int, ...], str | None]:
    """Win-aware keep choice. Returns (keep, note) with an explanation."""
    if not ctx.active:
        return oracle.best_keep(card, counts, rolls_left).keep, None

    if ctx.rounds_left == 1:
        rated = oracle.success_keeps(card, counts, rolls_left, ctx.needed)
        best_keep, p_win = rated[0]
        ev_keep = oracle.best_keep(card, counts, rolls_left)
        if p_win <= 0.0:
            return ev_keep.keep, (
                f"WIN: {ctx.needed:.0f} pts needed to catch {ctx.rival} is out "
                f"of reach; playing for points."
            )
        p_ev = next(p for k, p in rated if k == ev_keep.keep)
        if best_keep == ev_keep.keep:
            note = f"WIN: need {ctx.needed:.0f} pts to pass {ctx.rival}; chance {p_win:.0%}."
        else:
            note = (
                f"WIN: need {ctx.needed:.0f} pts to pass {ctx.rival}; this keep "
                f"wins {p_win:.0%} vs {p_ev:.0%} for the max-EV keep."
            )
        return best_keep, note

    # Second-to-last round: tilt variance inside the EV band.
    rated = oracle.rated_keeps_with_sd(card, counts, rolls_left)
    best_ev = rated[0][0].ev
    band = [r for r in rated if best_ev - r[0].ev <= EV_BAND]
    if ctx.trailing:
        pick = max(band, key=lambda r: r[1])
        style = "gambling for spread"
    elif TILT_WHEN_LEADING:
        pick = min(band, key=lambda r: r[1])
        style = "protecting the lead"
    else:
        pick = rated[0]
        style = "playing for points"
    if pick[0].keep == rated[0][0].keep:
        return pick[0].keep, None
    note = (
        f"WIN: {style} vs {ctx.rival} "
        f"(-{best_ev - pick[0].ev:.1f} EV, sd {pick[1]:.0f})."
    )
    return pick[0].keep, note


def choose_option(oracle: Oracle, card, counts: tuple[int, ...], ctx: WinContext):
    """Category choice: on the final turn the max-points option maximizes
    win chance too, so EV choice is correct everywhere."""
    return oracle.best_option(card, counts).option


class WinAwareBot:
    """Optimal EV play plus the win-aware endgame layer.

    Used by AUTO mode and by the arena (tools/arena.py) to tune the
    win-mode parameters for maximum win rate.
    """

    difficulty = "optimal+win"

    def __init__(self, oracle: Oracle, me: Player, opponents: list[Player]) -> None:
        self.oracle = oracle
        self.me = me
        self.opponents = opponents

    def _context(self) -> WinContext:
        rounds_left = sum(1 for b in self.me.card.boxes if b is None)
        return build_context(self.me, self.opponents, self.oracle, rounds_left, True)

    def choose_keep(self, card, counts, rolls_left):
        keep, _ = choose_keep(self.oracle, card, counts, rolls_left, self._context())
        return keep

    def choose_option(self, card, counts):
        return self.oracle.best_option(card, counts).option
