# Yahtzee TUI

Yahtzee in your terminal. Fully playable with **mouse**, **keyboard**, and
**slash commands**, against bots ranging from clueless to mathematically
perfect. The solver, hints, and bot levels are based on the video
[*I Solved Yahtzee**](https://www.youtube.com/watch?v=DOgb5wrb7mM) by
Ballpark Figures (Patrick Liscio): dynamic programming over every scorecard
state, for an expected score of ~254.6.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/RaphaelA4U/yahtzee/main/install.sh | bash
```

Then start the game with:

```bash
yahtzee
```

Requirements: `git` and `python3` 3.10+. The installer puts everything in
`~/.yahtzee` and links the `yahtzee` command into `~/.local/bin`.

## Auto-update

The app checks for updates in the background every time you open it and
installs them silently; the new version runs the next time you start (or
immediately via `/restart`). If an update fails, run `/update` inside the
app or reopen it with an internet connection. Playing itself is fully
offline.

## How to play

Everything works with the mouse (click dice to hold them, click a category
to score) and with the keyboard:

| Key | Action |
| --- | --- |
| `space` / `r` | roll |
| `1` to `5` | hold / release a die |
| arrow keys + `enter` | pick and score a category |
| `h` | hint from the optimal solver |
| `shift+tab` | switch mode: NORMAL, HINTS, AUTO |
| `/` | open the command bar |
| `?` / `F1` | help |
| `n` | new game, `q` quit, `escape` menu |

Commands: `/help` `/hint` `/hints on|off` `/auto` `/mode` `/new` `/rules`
`/speed` `/stats` `/update` `/restart` `/version` `/menu` `/quit`.

### Modes

- **NORMAL**: regular play.
- **HINTS**: after every roll the optimal solver tells you what to keep or
  score, with expected values and the video's rules of thumb.
- **AUTO**: the solver plays your turns while you watch.

### Opponents

Pick 1 to 4 bots and a difficulty (defaults: 2 bots, medium):

| Level | Average score | Plays like |
| --- | --- | --- |
| Easy | ~180 | keeps the most common face, grabs points |
| Medium | ~230 | the video's rules of thumb |
| Hard | ~241 | exact per-turn EV with a heuristic future |
| Optimal | ~255 | the full dynamic-programming solver |

### Game modes (rule variants)

- **Official** (default): Hasbro rules. 100-point bonus for every extra
  Yahtzee (if the Yahtzee box holds 50) and forced joker rules.
- **Free joker**: an extra Yahtzee may go in any open box; Full House and
  straights count full joker value once your matching upper box is filled.
- **Simple**: common house rules. No bonuses, no jokers; an extra Yahtzee
  is just a normal roll.

## The math

The solver computes, for all 8192 combinations of filled boxes, every upper
section total, and the Yahtzee bonus state, the expected remaining points
under optimal play, then plays every keep and category decision by exact
expected value. Each rule variant gets its own table:

| Variant | Expected score (optimal play) |
| --- | --- |
| Official (forced joker) | 254.588 |
| Free joker | 254.590 (matches the published optimum) |
| Simple (no bonus) | 245.871 (matches the published optimum) |

The tables ship with the repo (`data/`), so nothing needs to be computed on
your machine.

## Development

```bash
git clone https://github.com/RaphaelA4U/yahtzee.git && cd yahtzee
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                            # rules, solver, and TUI tests
.venv/bin/python -m tools.simulate 300      # benchmark the bot levels
.venv/bin/python -m yahtzee_app --build-tables  # rebuild the solver tables
```

Built with [Textual](https://textual.textualize.io/) and NumPy.
