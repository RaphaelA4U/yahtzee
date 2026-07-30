# Changelog

## v1.13.8

- No more spurious "Round 14/13" header on the joined side: after the
  final score the host briefly broadcasts round 14 before the match-over
  state, and the client turned that into a header. A match is capped at
  13 rounds now.

## v1.13.7

- Fix the match-over status bar telling every human "you won": it keyed
  on "the winner is not a bot" instead of "the winner is me", so online
  both players saw "you won". Only the actual winner sees "you" now.

## v1.13.6

- The joiner's log no longer repeats a move under the next round: the
  duplicate-line guard now compares the plain text, so a player's color
  settling after they join can't slip the same line through.

## v1.13.5

- --expect now accepts "Name:#color" so a pre-seated opponent shows their
  real color immediately, instead of a fallback pool color while the host
  waits for them to join.

## v1.13.4

- A remote player's own color (their avatar color) is now applied on every
  state, not only on the join event, so a reserved-seat joiner no longer
  briefly shows a fallback pool color (the "pink" seat).
- Chat battles are a single game (was inheriting the saved games-count).

## v1.13.3

- Fix "You joined as <the wrong player>" and wrong self-highlighting when
  joining a reserved-seat (chat battle) match: the first state can still
  carry the seat's placeholder id, so the client now identifies its own
  seat by name until its real id is bound, and re-resolves it on every
  state.

## v1.13.2

- Chat/relay battles no longer fail with "address in use" when several
  run on one machine: the direct-LAN port bind is now best-effort
  (the match plays over the relay regardless), so many battles run side
  by side and a busy port never dumps you back to the menu.

## v1.13.1

- Each player's scorecard now shows in that player's own color (column
  headers, cursor, totals), so an opponent's card no longer borrows your
  accent color; your own dice/turn UI stays in your color.

## v1.13.0

- --expect NAMES (with --host): pre-seat the named opponents and start
  the match at once, no lobby. They bind to their reserved seat by name
  whenever they join, so an expected player is never told "already
  started"; the game waits for them until then.
- With an explicit --color the WHOLE accent follows your color (dice
  cursor, YOUR TURN, borders), not just your name; normal play stays
  purple.
- Online log no longer repeats a move under the next round (exact-repeat
  event lines are dropped on the receiving side).

## v1.12.0

- --autostart (with --host): the match begins the moment the first
  opponent connects, so an orchestrated host never presses Enter; the
  lobby stays open until they join.
- Online log no longer double-prints a move: every state broadcast now
  carries a sequence number and a client ignores a re-delivered one.

## v1.11.0

- A scripted host (chat battles) now hosts a humans-only match: no bots
  are added regardless of your saved bot count.
- Shorter hosting intro, and the b-key (let a bot fill in for an absent
  player) is now a footer button instead of buried in the intro text.

## v1.10.2

- Version-string fix: __init__.py and pyproject.toml had silently stayed
  at 1.9.0 while the code advanced through 1.9.1-1.10.1 (the shipped
  features were all present; only the reported version was wrong). Now
  back in sync.

## v1.10.1

- Hotfix on v1.10.0: an indentation slip made joining a lobby fail for
  players without an explicit color. Do not host on v1.10.0.

## v1.10.0

- New --color #RRGGBB flag: give yourself a fixed player color that
  everyone sees as-is online (used by BM Beheer chat battles to match
  the chat avatar colors). Without it the everyone-sees-themselves-
  purple scheme applies as before.

## v1.9.0

- New CLI flags for scripted online play: --host CODE hosts with a fixed
  room code (and resumes an unfinished match with that code), --join CODE
  joins one directly, and --name sets your player name. Built for chat
  battles orchestrated from BM Beheer, handy for any automation.

## v1.8.3

- Dependency refreshes after updates keep the [solver] extra on
  machines that have numpy, so solver metadata stays correct.

## v1.8.2

- Lite mode actually starts on iSH now: one remaining module-level
  solver import (winmode) still pulled numpy in at startup and crashed
  the app before the menu. Verified against a numpy stub that fails
  exactly like iSH's.

## v1.8.1

- Your own card is now always the first card on your screen, also as an
  online joiner.
- iSH plays yahtzee now: its emulator cannot run numpy at all (no SSE),
  so numpy became an optional [solver] extra and the game runs in lite
  mode without it. Online play and the easy/medium bots work fully;
  hints, coach, auto and the hard/optimal bots need the solver and say
  so instead of crashing. The installer detects an unusable numpy and
  installs lite automatically; all other platforms keep the full solver.

## v1.8.0

- You are always purple on your own screen, online too: every player
  sees themselves in purple and the others in their own colors, on the
  cards and in the round log alike.
- Rolls now animate on the joined side as well, your own and those of
  the other players.
- Online matches survive closing the app. The host gets Resume hosting
  in the menu (same room code, seats stay reserved on device identity)
  and joined players get Rejoin online game (reconnects your seat
  automatically). Players who kept their app open reconnect by
  themselves the moment the host resumes.

## v1.7.9

- iSH fix: a virtualenv made by an older installer could not see apk's
  numpy, so pip tried to compile numpy from source (impossible there,
  no compiler). The installer now detects such a venv and recreates it,
  and forbids source builds on Alpine outright (--only-binary=:all:).

## v1.7.7

- Root cause of every 'Update failed' since v1.7.4: bin/yahtzee was
  committed without its executable bit, so the installer's chmod made
  every checkout permanently dirty and v1.7.4 (which edited that file)
  blocked the fast-forward. The bit is now committed; the installer
  also repairs blocked checkouts itself, like the in-app updater.
- Faster iSH installs: --no-compile and --no-cache-dir skip bytecode
  compilation and cache writes, the two things iSH's emulated CPU and
  filesystem choke on.

## v1.7.6

- The auto-updater now says WHY an update failed and heals a blocked
  checkout itself (hard reset to upstream; ~/.yahtzee is app-owned).
- Dependency refreshes after updates work on pip-less venvs (iSH/Alpine).
- iSH install: visible pip progress, a heads-up that the slow step can
  take 10-30 minutes on a phone, and --no-cache-dir to halve the writes.

## v1.7.5

- One install line for every platform: curl-or-wget fallback piped to sh.
  Works on macOS, Linux, WSL, iSH, and web/SSH terminals; in Git Bash on
  Windows install.sh now hands over to the PowerShell installer.

## v1.7.4

- Python 3.9 is now supported (was 3.10+): the code never needed 3.10,
  and all runtime dependencies resolve fine on 3.9 (textual 8.2.8,
  numpy 2.0.x, websockets 15.0.x). CI now tests 3.9 and 3.12.
- The installer was rebuilt for reliability: POSIX sh (works under
  busybox ash and dash, not just bash), platform and package-manager
  detection (apk/apt/dnf/pacman/brew), offers to install missing
  git/python/numpy with confirmation (YAHTZEE_YES=1 for non-interactive),
  checks the Python version before cloning anything, recreates broken or
  outdated virtualenvs, and verifies the install by importing the
  dependencies and running --version. Non-zero exit codes on failure.
- iSH (iOS) and Alpine are supported:
  wget -qO- https://raw.githubusercontent.com/RaphaelA4U/yahtzee/main/install.sh | sh
  Uses apk's python3/pip/numpy (PyPI has no musl-i686 numpy wheels) and
  creates the virtualenv without ensurepip, which is unusably slow on
  iSH, driving it with an upgraded outside pip instead.
- Honest dependency floors: websockets>=14 (the asyncio implementation
  the app actually uses), textual capped below 9, numpy floor per
  Python version.

## v1.7.3

- THE online freeze fix: the consume loops that apply incoming states
  raced screen mounting and could exit instantly, freezing a client (or
  host) on the first state forever. They now run for the screen's whole
  lifetime. This was the real cause behind both desync reports.
- Native Windows installer: iwr -useb .../install.ps1 | iex.
- Verified compatible with xterm-256color terminals and the xterm.js v6
  pipeline that BM Beheer's web SSH uses.

## v1.7.2

- Fixed: a player who joined through the relay froze after the first
  state. Overlapping broadcasts on the relay websocket tripped over the
  websocket library's no-concurrent-sends rule and silently dropped the
  seat; sends and broadcasts are serialized now, one bad state update
  can no longer stop the stream, and a regression test plays a host
  turn against a relay-connected client.

## v1.7.1

- Fixed: a room code stopped working after waiting a while in an empty
  lobby. The relay now keeps parked host connections alive (keepalive
  actually flows) and removes dead ones immediately, and the client
  retries instead of giving up when it hits a stale pairing.
- Fixed: after joining, the second player froze on the first state (the
  network loop died with the lobby screen); it now survives screen
  changes, with a regression test. Same fix protects the host's relay
  connection after the match starts.
- YOUR TURN now only lights up when it is genuinely YOUR turn (it lit
  up for every human's turn on every screen).
- The lobby name updates the table list letter by letter, and two
  players with the same name get numbered automatically.
- Statistics: highest/lowest score and accuracy per breakdown row.
- The in-app help lists the command line flags too.

## v1.7.0

- Host lobby redesigned: the room code front and center, direct
  LAN/Tailscale addresses behind d, c rerolls the code (players stay),
  1-5 kicks a joined player, and it says you are in the lobby.
- Online games wait for absent players as long as the host stays open
  (hours is fine); the host presses b to let a bot fill in until they
  return. No more automatic 60s takeover.
- Test multiplayer on one machine: yahtzee --profile second gives the
  second instance its own identity and settings.
- ctrl+q quits (plain q no longer closes the app by accident), the die
  cursor wraps around, and up/down moves between lobby fields.
- F2 or /screenshot saves a clean SVG of the screen to Downloads.
- The review lists decisions in order (with the biggest misses on top),
  statistics gained lowest score and per-category numbers, dice use the
  OS cryptographic RNG, and the roll animation always visibly rolls.
- Starting a new match and doing nothing no longer overwrites your
  saved game; the menu art shrinks on short terminals so nothing hides.
- New flags: --new and --profile (see yahtzee --help).

## v1.6.3

- Fixed: the host and join lobbies rendered empty (title and footer
  only); the body now shows the name field, share addresses, relay code,
  and player list as intended.

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
