"""Builds the optimal-strategy table via dynamic programming.

Same approach as "I Solved Yahtzee*" (Ballpark Figures / Patrick Liscio):
a state is (which boxes are filled, upper-section total capped at 63,
whether Yahtzee was scored for 50). V[state] = expected remaining points
under optimal play. States are processed by decreasing number of filled
boxes.

Validation: V[empty card] must be ~254.59 under official (forced-joker)
rules. Switching to Verhoeff's free-choice joker rule reproduces the
published 254.5896 exactly, which pins down the rest of the model.
"""

from __future__ import annotations

import time

import numpy as np

from ..game import (
    CHANCE,
    FOUR_KIND,
    FULL_HOUSE,
    LG_STRAIGHT,
    SM_STRAIGHT,
    THREE_KIND,
    UPPER_BONUS,
    UPPER_BONUS_THRESHOLD,
    YAHTZEE,
    YAHTZEE_EXTRA_BONUS,
    YAHTZEE_SCORE,
    category_score,
    is_yahtzee,
)
from .core import ALL_ROLLS, KEEP_MATRIX, P0, ROLL_INDEX, SUBSETS

N_MASKS = 1 << 13
FULL_MASK = N_MASKS - 1
NU = UPPER_BONUS_THRESHOLD + 1  # 0..63
N_ROLLS = len(ALL_ROLLS)

# Regular scores per category per roll: (13, 252)
SCORES = np.array(
    [[category_score(c, r) for r in ALL_ROLLS] for c in range(13)],
    dtype=np.float64,
)
IS_Y = np.array([is_yahtzee(r) for r in ALL_ROLLS])
# Roll index of each yahtzee (five 1s through five 6s)
YROLL_IDX = [
    ROLL_INDEX[tuple(5 if i == face else 0 for i in range(6))] for face in range(6)
]
U = np.arange(NU)
JOKER_LOWER = (THREE_KIND, FOUR_KIND, FULL_HOUSE, SM_STRAIGHT, LG_STRAIGHT, CHANCE)


def _joker_points(cat: int, face: int) -> float:
    if cat == FULL_HOUSE:
        return 25.0
    if cat == SM_STRAIGHT:
        return 30.0
    if cat == LG_STRAIGHT:
        return 40.0
    return 5.0 * (face + 1)


def compute_terminal(mask: int, V: np.ndarray, rules: str = "official") -> np.ndarray:
    """Value of every final roll: A[roll, upper total, flag].

    A = best choice of (points + bonuses + V[next state]), applying the
    extra-yahtzee rules of the active ruleset ("official", "free_joker",
    or "simple").
    """
    A = np.full((N_ROLLS, NU, 2), -np.inf)

    for c in range(13):
        if mask & (1 << c):
            continue
        Vn = V[mask | (1 << c)]  # (64, 2)
        if c < 6:
            sc = SCORES[c].astype(np.int64)
            new_u = np.minimum(U[None, :] + sc[:, None], UPPER_BONUS_THRESHOLD)
            crossed = (U[None, :] < UPPER_BONUS_THRESHOLD) & (
                U[None, :] + sc[:, None] >= UPPER_BONUS_THRESHOLD
            )
            cand = (
                sc[:, None, None]
                + UPPER_BONUS * crossed[:, :, None]
                + Vn[new_u]
            )
        elif c == YAHTZEE:
            # Non-yahtzee roll: 0 points, flag stays as it is.
            cand = np.broadcast_to(Vn[None, :, :], (N_ROLLS, NU, 2)).copy()
            # Yahtzee roll: 50 points, flag becomes 1.
            cand[IS_Y] = YAHTZEE_SCORE + Vn[:, 1][None, :, None]
        else:
            cand = SCORES[c][:, None, None] + np.broadcast_to(
                Vn[None, :, :], (N_ROLLS, NU, 2)
            )
        np.maximum(A, cand, out=A)

    # Extra-yahtzee handling: yahtzee rolled while the box is already filled.
    if rules == "simple" or not mask & (1 << YAHTZEE):
        return A

    bonus = np.array([0.0, float(YAHTZEE_EXTRA_BONUS)])  # per flag

    if rules == "free_joker":
        # Free choice among all open boxes; FH/SS/LS at joker value once the
        # matching upper box is filled. The +100 applies to every choice.
        for face in range(6):
            d = YROLL_IDX[face]
            best = np.full((NU, 2), -np.inf)
            joker_ok = bool(mask & (1 << face))
            for c in range(13):
                if mask & (1 << c):
                    continue
                Vn = V[mask | (1 << c)]
                if c < 6:
                    sc = 5 * (face + 1) if c == face else 0
                    new_u = np.minimum(U + sc, UPPER_BONUS_THRESHOLD)
                    crossed = (U < UPPER_BONUS_THRESHOLD) & (
                        U + sc >= UPPER_BONUS_THRESHOLD
                    )
                    cand = sc + UPPER_BONUS * crossed[:, None] + Vn[new_u]
                elif c in (FULL_HOUSE, SM_STRAIGHT, LG_STRAIGHT):
                    sc = _joker_points(c, face) if joker_ok else 0.0
                    cand = sc + Vn[U]
                else:
                    cand = SCORES[c][d] + Vn[U]
                np.maximum(best, cand, out=best)
            A[d] = bonus[None, :] + best
        return A

    # Official: forced joker rules.
    for face in range(6):
        d = YROLL_IDX[face]
        if not mask & (1 << face):
            # Forced into the matching upper box.
            sc = 5 * (face + 1)
            new_u = np.minimum(U + sc, UPPER_BONUS_THRESHOLD)
            crossed = (U < UPPER_BONUS_THRESHOLD) & (
                U + sc >= UPPER_BONUS_THRESHOLD
            )
            Vn = V[mask | (1 << face)]
            A[d] = (
                bonus[None, :]
                + sc
                + UPPER_BONUS * crossed[:, None]
                + Vn[new_u]
            )
            continue
        lower_open = [c for c in JOKER_LOWER if not mask & (1 << c)]
        if lower_open:
            stack = np.stack(
                [_joker_points(c, face) + V[mask | (1 << c)] for c in lower_open]
            )
        else:
            upper_open = [c for c in range(6) if not mask & (1 << c)]
            stack = np.stack([V[mask | (1 << c)] for c in upper_open])
        A[d] = bonus[None, :] + stack.max(axis=0)

    return A


def turn_value(A: np.ndarray) -> np.ndarray:
    """Value of a whole turn (3 rolls, optimal holds) per (upper, flag)."""
    flat = A.reshape(N_ROLLS, NU * 2)
    ek2 = KEEP_MATRIX @ flat
    e2 = np.empty_like(flat)
    for i, subs in enumerate(SUBSETS):
        e2[i] = ek2[subs].max(axis=0)
    ek1 = KEEP_MATRIX @ e2
    e1 = np.empty_like(flat)
    for i, subs in enumerate(SUBSETS):
        e1[i] = ek1[subs].max(axis=0)
    return (P0 @ e1).reshape(NU, 2)


def build_table(rules: str = "official", progress: bool = True) -> np.ndarray:
    """Build the full V table for a ruleset: shape (8192, 64, 2), float64."""
    V = np.zeros((N_MASKS, NU, 2), dtype=np.float64)
    order = sorted(range(N_MASKS), key=lambda m: bin(m).count("1"), reverse=True)
    t0 = time.time()
    for i, mask in enumerate(order):
        if mask == FULL_MASK:
            continue
        V[mask] = turn_value(compute_terminal(mask, V, rules))
        if progress and i % 1024 == 0:
            pct = 100.0 * i / N_MASKS
            print(f"  building {rules}: {pct:5.1f}%  ({time.time() - t0:.0f}s)", flush=True)
    if progress:
        print(f"  {rules} done in {time.time() - t0:.0f}s, EV empty card = {V[0, 0, 0]:.4f}")
    return V


# Reference values: official is the forced-joker optimum; free_joker matches
# Verhoeff's published 254.5896.
EXPECTED_EV = {
    "official": (254.5, 254.7),
    "free_joker": (254.5, 254.7),
    "simple": (240.0, 254.7),
}


def main() -> None:
    from ..game import RULESETS
    from .tables import save_table

    for rules in RULESETS:
        print(f"Building the optimal-strategy table for '{rules}'...")
        V = build_table(rules)
        path = save_table(V, rules)
        print(f"Saved: {path}")
        lo, hi = EXPECTED_EV[rules]
        ev = V[0, 0, 0]
        if not lo < ev < hi:
            print(f"WARNING: EV {ev:.4f} outside the expected range ({lo}-{hi})")


if __name__ == "__main__":
    main()
