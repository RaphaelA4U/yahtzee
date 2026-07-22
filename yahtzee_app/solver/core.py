"""Combinatorics for the solver.

- ALL_ROLLS: all 252 multisets of 5 dice (as counts tuples).
- ALL_KEEPS: all 462 multisets of 0 through 5 dice.
- KEEP_MATRIX[k, r]: probability of ending on roll r when you hold keep k
  and reroll the rest.
- SUBSETS[r]: indices of all keeps that are a sub-multiset of roll r
  (including keeping everything and rerolling everything).
- P0: distribution of a fresh roll of 5 dice (= KEEP_MATRIX[empty keep]).

Everything is computed once at import; that takes a few tens of ms.
"""

from __future__ import annotations

import itertools
from functools import lru_cache
from math import factorial

import numpy as np


def _multisets(n_dice: int) -> list[tuple[int, ...]]:
    """All counts tuples (length 6) summing to n_dice."""
    out = []
    for combo in itertools.combinations_with_replacement(range(6), n_dice):
        c = [0] * 6
        for face in combo:
            c[face] += 1
        out.append(tuple(c))
    return out


ALL_ROLLS: list[tuple[int, ...]] = _multisets(5)          # 252
ROLL_INDEX: dict[tuple[int, ...], int] = {r: i for i, r in enumerate(ALL_ROLLS)}

ALL_KEEPS: list[tuple[int, ...]] = [
    k for n in range(6) for k in _multisets(n)
]                                                          # 462
KEEP_INDEX: dict[tuple[int, ...], int] = {k: i for i, k in enumerate(ALL_KEEPS)}


def _multinomial_prob(counts: tuple[int, ...]) -> float:
    """Probability of rolling exactly this multiset with sum(counts) fair dice."""
    n = sum(counts)
    perms = factorial(n)
    for c in counts:
        perms //= factorial(c)
    return perms / (6 ** n)


def _build_keep_matrix() -> np.ndarray:
    m = np.zeros((len(ALL_KEEPS), len(ALL_ROLLS)), dtype=np.float64)
    for ki, keep in enumerate(ALL_KEEPS):
        n_reroll = 5 - sum(keep)
        for extra in _multisets(n_reroll):
            final = tuple(keep[i] + extra[i] for i in range(6))
            m[ki, ROLL_INDEX[final]] += _multinomial_prob(extra)
    return m


KEEP_MATRIX: np.ndarray = _build_keep_matrix()
P0: np.ndarray = KEEP_MATRIX[KEEP_INDEX[(0, 0, 0, 0, 0, 0)]].copy()


def _build_subsets() -> list[np.ndarray]:
    subs = []
    for roll in ALL_ROLLS:
        idxs = set()
        ranges = [range(c + 1) for c in roll]
        for keep in itertools.product(*ranges):
            idxs.add(KEEP_INDEX[keep])
        subs.append(np.array(sorted(idxs), dtype=np.int64))
    return subs


SUBSETS: list[np.ndarray] = _build_subsets()


@lru_cache(maxsize=None)
def keeps_of_roll(roll: tuple[int, ...]) -> list[tuple[int, ...]]:
    """All possible keeps (as counts tuples) for a roll."""
    ranges = [range(c + 1) for c in roll]
    seen = set()
    out = []
    for keep in itertools.product(*ranges):
        if keep not in seen:
            seen.add(keep)
            out.append(keep)
    return out
