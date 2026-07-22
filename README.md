# Yahtzee TUI

Yahtzee in your terminal, Claude-terminal style: your terminal's own colors,
everything in ASCII, no buttons and no dialogs. 3D dice with hover and an
arrow cursor, and the classic score sheet on the table: real cells, one
column per player. Fully playable with **mouse**, **keyboard**, and **slash
commands**, against bots ranging from clueless to mathematically perfect.
The solver, hints, and bot levels are based on the video
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
applies them instantly: on the menu it relaunches itself into the new
version automatically; mid-game your game is saved and `/restart` (or
`/update`) applies the update and drops you right back into your game.
If an update fails, run `/update` inside the app or reopen it with an
internet connection. Playing itself is fully offline.

## How to play

Everything works with the mouse (click dice to hold them, click a box on
your card to score) and with the keyboard:

| Key | Action |
| --- | --- |
| `r` / `space` | roll |
| `1` to `5` | hold / release a die |
| `left`/`right` | move the die cursor |
| `up`/`down` + `enter` | pick and fill a box on the score sheet |
| `tab` | switch focus: dice, score sheet, command bar |
| `h` | hint from the optimal solver |
| `shift+tab` | switch mode: NORMAL, HINTS, COACH, AUTO |
| `/` | open the command bar |
| `?` / `F1` | help |
| `n` | new game, `q` quit, `escape` menu |

Commands: `/help` `/hint` `/hints on|off` `/coach on|off` `/auto` `/mode`
`/win on|off` `/review` `/new` `/rules` `/speed` `/stats` `/update`
`/restart` `/version` `/menu` `/quit`.

Best played in a roomy terminal (about 120x30 or larger).

### Modes

- **NORMAL**: regular play.
- **HINTS**: after every roll the optimal solver tells you what to keep or
  score, with expected values and the video's rules of thumb.
- **COACH**: play on your own, but every decision gets a verdict (EV lost
  vs optimal), a chess-style accuracy score, and a post-game review with
  your worst mistakes.
- **AUTO**: the solver plays your turns while you watch.

### WIN mode

The video's asterisk: maximizing points is not maximizing win probability.
`/win on` makes hints and AUTO play for the win in the endgame: exact
win-chance calculation in the final round (via the same dice DP, run on a
success indicator) and variance control in the round before, based on the
projected scores of your opponents.

### More

- Games save automatically; continue from the menu after quitting.
- Skip the menu from the shell: `yahtzee --bots 3 --level optimal --rules
  simple`, reproducible dice with `--seed 42`.
- After an update the app shows what's new.

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
