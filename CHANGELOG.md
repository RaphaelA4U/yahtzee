# Changelog

## v1.1.0

- Complete ASCII redesign: 3D dice with hover and an arrow-key cursor, and
  paper-style scorecards per player, like the real table game.
- COACH mode: every decision graded against the optimal solver, with a
  chess-style accuracy score and a post-game review (worst mistakes first).
- WIN mode (/win): endgame play for win probability instead of points.
  Exact win-chance calculation in the final round, variance control in the
  round before.
- Games are saved automatically; continue from the menu after quitting.
- CLI flags: yahtzee --bots 3 --level optimal --rules simple --seed 42.
- "What's new" message after every update, and CI on GitHub.

## v1.0.0

- First release: Yahtzee TUI with mouse, keyboard, and slash commands.
- Bots at four levels, up to a mathematically optimal solver based on the
  video "I Solved Yahtzee*" by Ballpark Figures.
- Hints with expected values, three rule variants, auto-update from GitHub.
