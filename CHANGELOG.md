# Changelog

## v1.6.2

- Compact cards: on narrow terminals (quarter screen) the cards switch
  to abbreviated labels (1s..6s, 3K, FH, Y!, Ch) automatically, so three
  cards fit where one and a half used to.
- The relay at relay.rustema.app is live and publicly verified.

## v1.6.1

- The relay is now generic (service and container simply named "relay"),
  ready to be reused by other minigames; nothing Yahtzee-specific runs
  on it.

## v1.6.0

- ONLINE MULTIPLAYER: host a game from the menu and friends join by
  address, over LAN, Tailscale/ZeroTier, or the internet (the host tries
  UPnP automatically; otherwise forward a TCP port). Host-authoritative,
  no accounts, no servers: your device gets a one-time random ID, seats
  survive reconnects, and a bot fills in if someone stays away for 60s.
  Player stats are shared peer-to-peer in the lobby, nothing is stored
  centrally. Bots fill the remaining seats.
- Continue last game brings your full log back and marks where you
  continued; round headers only appear together with the round's first
  line, never dangling.
- Cards wrap into rows (2 or 3 per row depending on card width) with an
  invisible vertical scroll, so every card is reachable again; table
  size maxes at 5 bots.
- Footer actions are clickable on every screen, the menu scrollbar is
  hidden, and the "Free joker" arrow can no longer wrap.
- More breathing room in the log, and statistics no longer mention
  older-version matches.
- A public relay (relay.rustema.app) as the third transport rung, for
  when both players sit behind CGNAT: the host lobby shows a 6-letter
  code, the joiner just types it. The relay pairs and pipes; it stores
  nothing.
- AUTO retrained in a bigger arena (24 configs, confirmed on 20,000
  matches): endgame play now gives up nothing when ahead; the win-aware
  edge against a perfect opponent is small but free (+0.4% at the same
  254.5 average).

## v1.5.1

- Bot name pools grown to 100 female + 100 male US/UK names.

## v1.5.0

- Statistics rebuilt: every FINISHED game counts (even if you abandon
  the match afterwards), with breakdowns by assistance (none, hints,
  coach, auto), opponent difficulty, table size, and rule variant.
- The footer keys are clickable now: roll, mode, hint, cmd, help, menu.
- Up to 7 bots at the table (official Yahtzee has no player cap).
- Bot names come from big US/UK pools, half female, half male.
- Fixed: the last game column stayed empty on the cards at match end.
- Bots hold dice a bit more slowly; WIN notes stay quiet when the win
  is already locked (no more 'need -106 pts' lines).

## v1.4.1

- The accent border now follows your focus (like tab): around the dice
  while you are there, around your card when you move over.
- Held dice show the color of whoever holds them, and bots hold their
  dice one at a time, like a person would.
- The log always follows the game, gets a blank line between rounds, and
  no longer spams mode changes or duplicate hints while cycling modes.
- A breath of air above the dice border and after card labels.

## v1.4.0

- Every player has a color: you are purple-blue, bots get random names
  like "Carmen (BOT)" with their own color in the log, cards, and status.
- Clearer hints: a HINT/COACH/WIN label per line, bold advice, dim
  alternatives on one line. No yellow anywhere; orange for hints/bonuses.
- Switching into AUTO via shift+tab now counts down 3 seconds, so you
  can cycle past it without it taking over your turn.
- Focus stays on the dice until your rolls are done, then the border and
  focus move to the first open box on your card.
- What's new is a menu item now; the update banner shows old and new
  version; scrollbars are hidden with a "more cards" indicator instead.
- The menu dice are straightened, and Ybonus is now labeled
  Yahtzee bonus (the 100-point bonuses for extra yahtzees).

## v1.3.0

- Matches: 1 to 6 games per match (set Games in the menu); every player
  has their own card with a column per game and a running MATCH total,
  like the classic paper pad.
- True auto-update: the update is pulled and applied BEFORE the app
  starts, so you always open the latest version.
- Purple (Claude-style) selection color, the DOS Rebel logo with five
  random dice, and explanations under every menu setting.
- Clearer play: an accent border shows what to do (roll or fill), the
  first open box is focused automatically, crossed-out boxes show x, and
  the Bonus 63+ row shows how many points you still need.
- WIN mode tuned in the new arena (tools/arena.py, 3000-match runs):
  exact final-round win-probability play, now on by default; hints are
  standings-aware near the end.
- Finished matches can be reopened from the menu (View last game).

## v1.2.0

- Claude-terminal restyle: your terminal's own colors (no more forced dark
  background), everything drawn in ASCII.
- No more buttons or dialogs: the menu is arrow-navigable text (left/right
  adjusts settings), help/stats/review are full pages, game over happens
  inline, and quitting never asks (the game is always saved).
- The score sheet is now one classic sheet on the table: real cells, a
  column per player, with hover and an arrow cursor in your column.
- Arrow keys and mouse hover now work everywhere.

## v1.1.1

- Updates now apply instantly: on the menu the app relaunches itself into
  the new version automatically; mid-game, /restart or /update applies the
  update and reopens your saved game right where you were.
- New --resume flag to reopen the saved game from the shell.

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
