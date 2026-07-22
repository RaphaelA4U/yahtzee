"""The Yahtzee TUI: ASCII table-top style, fully playable with mouse,
keyboard, and commands.

Design: everything that can be ASCII is ASCII. Dice are drawn as 3D dice
with a drop shadow, every player has their own paper-style scorecard, and
custom styling is kept to a minimum (colors and hover states only).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, HorizontalScroll, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, RichLog, Select, Static, Switch

from .. import __version__
from ..bots import (
    BOT_NAMES,
    DIFFICULTIES,
    DIFFICULTY_INFO,
    DIFFICULTY_LABELS,
    get_optimal_oracle,
    make_bot,
)
from ..coach import CoachTracker, Decision, record_keep, record_score, verdict_line
from ..config import (
    SPEED_DELAYS,
    clear_saved_game,
    load_game_snapshot,
    load_settings,
    record_game,
    save_game_snapshot,
    save_settings,
    stats_summary,
)
from ..game import (
    CATEGORY_NAMES,
    N_CATEGORIES,
    RULESET_INFO,
    RULESET_LABELS,
    RULESETS,
    Game,
    Player,
    Scorecard,
)
from ..hints import hint_for
from ..update import REPO_DIR, check_and_update, current_version
from .. import winmode

MODES = ["normal", "hints", "coach", "auto"]
MODE_LABELS = {"normal": "NORMAL", "hints": "HINTS", "coach": "COACH", "auto": "AUTO"}

HUMAN_NAME = "You"

CARD_LABELS = [
    "Ones", "Twos", "Threes", "Fours", "Fives", "Sixes",
    "3 of a Kind", "4 of a Kind", "Full House", "Sm Straight", "Lg Straight",
    "YAHTZEE", "Chance",
]

LOGO = r"""
 __ __   ____  __ __  ______  ____   ___  ___
|  |  | /    ||  |  ||      ||    | /  _]/  _]
|  |  ||  o  ||  |  ||      | |  | /  [_/  [_
|  ~  ||     ||  _  ||_|  |_| |  ||    |    _]
|___, ||  _  ||  |  |  |  |   |  ||   [|   [_
|     ||  |  ||  |  |  |  |   |  ||     |    |
|____/ |__|__||__|__|  |__|  |____|_____|____|

     .-------.        .-------.
     | o   o |\       | o     |\
     |   o   | |      |   o   | |
     | o   o | |      |     o | |
     '-------' |      '-------' |
      \________\       \________\
"""


@dataclass
class GameConfig:
    difficulties: list[str] = field(default_factory=lambda: ["medium", "medium"])
    mode: str = "normal"
    rules: str = "official"
    seed: int | None = None


def build_players(config: GameConfig) -> list[Player]:
    players = [Player(HUMAN_NAME, is_bot=False, card=Scorecard(config.rules))]
    used: dict[str, int] = {}
    for diff in config.difficulties:
        base = BOT_NAMES[diff]
        used[base] = used.get(base, 0) + 1
        name = base if used[base] == 1 else f"{base} {used[base]}"
        players.append(
            Player(name, is_bot=True, difficulty=diff, card=Scorecard(config.rules))
        )
    return players


# ---------------------------------------------------------------------------
# Dice
# ---------------------------------------------------------------------------


class AsciiDie(Static):
    """A 3D ASCII die with a drop shadow. Click to hold."""

    value: reactive[int] = reactive(1)
    held: reactive[bool] = reactive(False)
    blank: reactive[bool] = reactive(True)
    cursor: reactive[bool] = reactive(False)

    class Pressed(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    PIPS = {
        1: ["       ", "   o   ", "       "],
        2: [" o     ", "       ", "     o "],
        3: [" o     ", "   o   ", "     o "],
        4: [" o   o ", "       ", " o   o "],
        5: [" o   o ", "   o   ", " o   o "],
        6: [" o   o ", " o   o ", " o   o "],
    }

    def __init__(self, index: int) -> None:
        super().__init__(classes="die")
        self.index = index

    def render(self) -> Text:
        if self.blank:
            rows = ["       ", "   ?   ", "       "]
        else:
            rows = self.PIPS[self.value]
        face_style = "bold yellow" if self.held else ("dim" if self.blank else "")
        art = Text()
        art.append(".-------.  \n", style=face_style)
        for i, row in enumerate(rows):
            shadow = "\\ " if i == 0 else " |"
            art.append(f"|{row}|", style=face_style)
            art.append(f"{shadow}\n", style="dim")
        art.append("'-------'", style=face_style)
        art.append(" |\n", style="dim")
        art.append(" \\________\\|\n", style="dim")
        if self.held:
            label = f">[{self.index + 1}] HELD" if self.cursor else f" [{self.index + 1}] HELD"
            art.append(label.center(11), style="bold yellow")
        elif self.cursor:
            art.append(f">({self.index + 1})<".center(11), style="bold")
        else:
            art.append(f"({self.index + 1})".center(11), style="dim")
        return art

    def watch_value(self, _: int) -> None:
        self.refresh()

    def watch_held(self, _: bool) -> None:
        self.refresh()

    def watch_blank(self, _: bool) -> None:
        self.refresh()

    def watch_cursor(self, _: bool) -> None:
        self.refresh()

    def on_click(self) -> None:
        self.post_message(self.Pressed(self.index))


class DiceRow(Widget, can_focus=True):
    """The five dice plus an arrow-key cursor."""

    BINDINGS = [
        Binding("left", "cursor_left", "Left", show=False),
        Binding("right", "cursor_right", "Right", show=False),
        Binding("space,enter", "toggle", "Hold", show=False),
    ]

    cursor_idx: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        for i in range(5):
            yield AsciiDie(i)

    def dice(self) -> list[AsciiDie]:
        return list(self.query(AsciiDie))

    def show_cursor(self, show: bool) -> None:
        for i, die in enumerate(self.dice()):
            die.cursor = show and i == self.cursor_idx

    def action_cursor_left(self) -> None:
        self.cursor_idx = max(0, self.cursor_idx - 1)
        self.show_cursor(self.has_focus)

    def action_cursor_right(self) -> None:
        self.cursor_idx = min(4, self.cursor_idx + 1)
        self.show_cursor(self.has_focus)

    def action_toggle(self) -> None:
        self.post_message(AsciiDie.Pressed(self.cursor_idx))

    def on_focus(self) -> None:
        self.show_cursor(True)

    def on_blur(self) -> None:
        self.show_cursor(False)


class RollButton(Static):
    """ASCII roll button."""

    enabled: reactive[bool] = reactive(True)
    rolls_left: reactive[int] = reactive(3)

    def render(self) -> Text:
        if not self.enabled:
            return Text("[ .  .  . ]", style="dim")
        return Text.assemble(
            ("[ ROLL (r) ]", "bold reverse yellow"),
            (f"  {self.rolls_left} left", "dim"),
        )

    def watch_enabled(self, _: bool) -> None:
        self.refresh()

    def watch_rolls_left(self, _: int) -> None:
        self.refresh()

    def on_click(self) -> None:
        if self.enabled:
            self.post_message(self.Rolled())

    class Rolled(Message):
        pass


# ---------------------------------------------------------------------------
# Paper scorecards
# ---------------------------------------------------------------------------

CARD_WIDTH = 22
CARD_INNER = CARD_WIDTH - 2  # between the pipes


class PlayerCard(Widget):
    """One player's scorecard, drawn like the paper card on the table.

    Rows (0-based line numbers):
      0        top border with the name
      1-6      upper section (cats 0-5)
      7        Sum
      8        Bonus 63+
      9        divider
      10-16    lower section (cats 6-12)
      17       Yahtzee bonus
      18       divider
      19       TOTAL
      20       bottom border
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("space,enter", "pick", "Score", show=False),
    ]

    LINE_TO_CAT = {**{i + 1: i for i in range(6)}, **{i + 4: i for i in range(6, 13)}}
    CAT_TO_LINE = {v: k for k, v in LINE_TO_CAT.items()}

    class CategoryPicked(Message):
        def __init__(self, category: int) -> None:
            self.category = category
            super().__init__()

    cursor_cat: reactive[int | None] = reactive(None)

    def __init__(self, player: Player, interactive: bool) -> None:
        super().__init__(classes="playercard")
        self.player = player
        self.interactive = interactive
        self.can_focus = interactive
        self.is_turn = False
        self.preview: dict[int, str] = {}

    # -- data --------------------------------------------------------------

    def set_state(self, is_turn: bool, preview: dict[int, str]) -> None:
        self.is_turn = is_turn
        self.preview = preview
        if not self.interactive or not preview:
            self.cursor_cat = None
        elif self.cursor_cat not in preview:
            self.cursor_cat = next(iter(sorted(preview)), None)
        self.refresh()

    # -- rendering ---------------------------------------------------------

    def _row(self, label: str, value: Text, cursor: bool = False) -> Text:
        text = Text()
        marker = ">" if cursor else " "
        text.append("|", style="dim")
        text.append(marker, style="bold yellow" if cursor else "dim")
        body = Text(f"{label:<12}", style="" if cursor else "dim")
        text.append_text(body)
        value.align("right", 6)
        text.append_text(value)
        text.append(" |", style="dim")
        text.append("\n")
        if cursor:
            text.stylize("reverse", len("|"), len(text) - 2)
        return text

    def render(self) -> Text:
        card = self.player.card
        name = self.player.name
        if self.player.difficulty:
            name += f" ({self.player.difficulty})"
        head_style = "bold yellow" if self.is_turn else "bold"
        out = Text()
        dashes = CARD_WIDTH - 5 - len(name)
        out.append(".-- ", style="dim")
        out.append(name[: CARD_INNER - 4], style=head_style)
        out.append(" " + "-" * max(0, dashes - 1) + ".", style="dim")
        out.append("\n")

        def value_of(cat: int) -> Text:
            val = card.boxes[cat]
            if val is not None:
                return Text(str(val), style="bold")
            if cat in self.preview:
                return Text(self.preview[cat], style="cyan")
            if self.preview:
                return Text("x", style="dim red")
            return Text(".", style="dim")

        for cat in range(6):
            out.append_text(
                self._row(CARD_LABELS[cat], value_of(cat), cursor=cat == self.cursor_cat)
            )
        out.append_text(self._row("Sum", Text(str(card.upper_subtotal()), style="dim")))
        bonus = card.upper_bonus()
        out.append_text(
            self._row(
                "Bonus 63+",
                Text(str(bonus) if bonus else "-", style="green" if bonus else "dim"),
            )
        )
        out.append("|" + "-" * CARD_INNER + "|\n", style="dim")
        for cat in range(6, N_CATEGORIES):
            out.append_text(
                self._row(CARD_LABELS[cat], value_of(cat), cursor=cat == self.cursor_cat)
            )
        yb = card.yahtzee_bonus_count * 100
        out.append_text(
            self._row(
                "Y. bonus",
                Text(str(yb) if yb else "-", style="magenta" if yb else "dim"),
            )
        )
        out.append("|" + "=" * CARD_INNER + "|\n", style="dim")
        out.append_text(self._row("TOTAL", Text(str(card.total()), style="bold yellow")))
        out.append("'" + "-" * CARD_INNER + "'", style="dim")
        return out

    # -- interaction -------------------------------------------------------

    def _selectable(self) -> list[int]:
        return sorted(self.preview)

    def action_cursor_up(self) -> None:
        self._move_cursor(-1)

    def action_cursor_down(self) -> None:
        self._move_cursor(1)

    def _move_cursor(self, step: int) -> None:
        cats = self._selectable()
        if not cats:
            return
        if self.cursor_cat not in cats:
            self.cursor_cat = cats[0]
        else:
            idx = (cats.index(self.cursor_cat) + step) % len(cats)
            self.cursor_cat = cats[idx]
        self.refresh()

    def action_pick(self) -> None:
        if self.cursor_cat is not None:
            self.post_message(self.CategoryPicked(self.cursor_cat))

    def on_click(self, event) -> None:
        if not self.interactive:
            return
        cat = self.LINE_TO_CAT.get(event.y)
        if cat is None:
            return
        if cat in self.preview:
            self.cursor_cat = cat
            self.refresh()
            self.post_message(self.CategoryPicked(cat))

    def watch_cursor_cat(self, _) -> None:
        self.refresh()


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------


class ConfirmScreen(ModalScreen[bool]):
    """Simple yes/no question."""

    BINDINGS = [
        Binding("escape,n", "answer(False)", "No"),
        Binding("enter,y", "answer(True)", "Yes", priority=True),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Container(id="confirm-box"):
            yield Label(self.question, id="confirm-question")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="primary", id="yes")
                yield Button("No", id="no")

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, answer: bool) -> None:
        self.dismiss(answer)


HELP_TEXT = f"""[b]YAHTZEE v{__version__}[/b]

[b u]Keys[/b u]
  [b]r / space[/b]      roll
  [b]1 to 5[/b]         hold / release a die (or click it)
  [b]left/right[/b]     move the die cursor (with the dice focused)
  [b]up/down[/b]        move over your scorecard (with the card focused)
  [b]enter / space[/b]  hold the selected die, or score the selected box
  [b]tab[/b]            switch focus: dice, your card, command bar
  [b]h[/b]              hint (from the optimal solver)
  [b]shift+tab[/b]      switch mode: NORMAL, HINTS, COACH, AUTO
  [b]/[/b]              open the command bar
  [b]?[/b] or [b]F1[/b]        this help
  [b]n[/b]              new game (same settings)
  [b]escape[/b]         back / to menu
  [b]q[/b]              quit

[b u]Commands[/b u]  (type / followed by the command)
  [b]/help[/b] or [b]/?[/b]     this help
  [b]/hint[/b]           one-off hint for the current situation
  [b]/hints on|off[/b]   hint mode (advice after every roll)
  [b]/coach on|off[/b]   coach mode (EV verdict after every decision)
  [b]/auto[/b]           auto mode (the solver plays your turns)
  [b]/mode X[/b]         normal, hints, coach, or auto
  [b]/win on|off[/b]     endgame win-probability play in hints/auto
  [b]/review[/b]         your decisions so far, worst first
  [b]/new [n] [level] [rules][/b]  new game, e.g. /new 3 optimal simple
  [b]/rules[/b]          show the active rule variant
  [b]/speed X[/b]        bot speed: slow, normal, fast, instant
  [b]/stats[/b]          your statistics
  [b]/update[/b]         check for updates now and install
  [b]/restart[/b]        restart the app (after an update)
  [b]/version[/b]        show the version
  [b]/menu[/b]           back to the main menu
  [b]/quit[/b]           quit

[b u]Modes[/b u]  (shift+tab cycles)
  [b]NORMAL[/b]  regular play
  [b]HINTS[/b]   solver advice after every roll, before you decide
  [b]COACH[/b]   verdict after every decision, plus a post-game review
  [b]AUTO[/b]    the solver plays your turns automatically

[b u]WIN mode[/b u]  (/win, the video's asterisk)
Maximizing points is not maximizing win chance. With WIN on, hints and
AUTO switch in the last two rounds: exact win-probability play in the
final round, variance control in the one before.

[b u]Opponents[/b u]
  [b]Easy[/b]     {DIFFICULTY_INFO['easy']}
  [b]Medium[/b]   {DIFFICULTY_INFO['medium']}
  [b]Hard[/b]     {DIFFICULTY_INFO['hard']}
  [b]Optimal[/b]  {DIFFICULTY_INFO['optimal']}

[b u]Game modes (rule variants)[/b u]
  [b]Official[/b]     {RULESET_INFO['official']}
  [b]Free joker[/b]   {RULESET_INFO['free_joker']}
  [b]Simple[/b]       {RULESET_INFO['simple']}

The solver, hints, and bot levels are based on the video
[i]I Solved Yahtzee*[/i] by Ballpark Figures (Patrick Liscio):
dynamic programming over all scorecard states, expected score ~254.6.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark,f1", "dismiss_help", "Close")]

    def compose(self) -> ComposeResult:
        with Container(id="help-box"):
            yield Static(HELP_TEXT, id="help-text", markup=True)
            yield Button("Close (esc)", id="help-close")

    @on(Button.Pressed, "#help-close")
    def _close(self) -> None:
        self.dismiss()

    def action_dismiss_help(self) -> None:
        self.dismiss()


class ReviewScreen(ModalScreen[None]):
    """Post-game (or mid-game) coach review: every decision, worst first."""

    BINDINGS = [Binding("escape,q,v", "dismiss_review", "Close")]

    def __init__(self, tracker: CoachTracker, title: str = "Game review") -> None:
        super().__init__()
        self.tracker = tracker
        self.title_text = title

    def compose(self) -> ComposeResult:
        t = self.tracker
        lines = [
            f"[b]{self.title_text}[/b]",
            "",
            f"Accuracy: [b]{t.accuracy()}%[/b]   "
            f"(total EV given away: {t.total_loss:.1f} points, "
            f"{len(t.decisions)} decisions)",
            "",
        ]
        if not t.decisions:
            lines.append("No graded decisions yet. Play a turn first.")
        else:
            lines.append("[b u]Worst decisions[/b u]")
            for d in t.worst(8):
                if d.loss < 0.05:
                    continue
                lines.append(
                    f"  round {d.round:>2}  [{d.dice}]  you: {d.chosen}"
                )
                lines.append(
                    f"           best: {d.best}  [red]-{d.loss:.1f} EV[/red]"
                )
            perfect = sum(1 for d in t.decisions if d.loss < 0.05)
            lines.append("")
            lines.append(
                f"Perfect decisions: {perfect}/{len(t.decisions)}"
            )
        with Container(id="review-box"):
            yield Static("\n".join(lines), id="review-text", markup=True)
            yield Button("Close (esc)", id="review-close")

    @on(Button.Pressed, "#review-close")
    def _close(self) -> None:
        self.dismiss()

    def action_dismiss_review(self) -> None:
        self.dismiss()


class GameOverScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("n", "result('new')", "New game"),
        Binding("v", "result('review')", "Review"),
        Binding("escape,m", "result('menu')", "Menu"),
    ]

    def __init__(self, game: Game, accuracy: int | None) -> None:
        super().__init__()
        self.game = game
        self.accuracy = accuracy

    def compose(self) -> ComposeResult:
        ranked = self.game.rankings()
        winner, _ = ranked[0]
        title = "*** You win! ***" if not winner.is_bot else f"{winner.name} wins"
        lines = [f"[b]{title}[/b]", ""]
        for i, (p, score) in enumerate(ranked, start=1):
            diff = f" ({p.difficulty})" if p.difficulty else ""
            lines.append(f"  {i}. {p.name}{diff}: [b]{score}[/b] points")
        if self.accuracy is not None:
            lines.append("")
            lines.append(f"Your accuracy: [b]{self.accuracy}%[/b] (v for the review)")
        with Container(id="gameover-box"):
            yield Static("\n".join(lines), id="gameover-text", markup=True)
            with Horizontal(id="gameover-buttons"):
                yield Button("New game (n)", variant="primary", id="new")
                yield Button("Review (v)", id="review")
                yield Button("Menu (m)", id="menu")

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        self.dismiss(str(event.button.id))

    def action_result(self, what: str) -> None:
        self.dismiss(what)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


class MenuScreen(Screen):
    BINDINGS = [
        Binding("question_mark,f1", "help", "Help"),
        Binding("q,escape", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        settings = load_settings()
        with Center(id="menu-center"):
            with Vertical(id="menu-box"):
                yield Static(Text(LOGO, style="yellow"), id="menu-logo")
                yield Label(f"v{__version__}", id="menu-version")
                yield Button("Continue saved game", variant="success", id="menu-continue")
                yield Label("Opponents:", classes="menu-label")
                yield Select(
                    [(f"{n} bot{'s' if n > 1 else ''}", n) for n in range(1, 5)],
                    value=int(settings.get("n_bots", 2)),
                    allow_blank=False,
                    id="menu-bots",
                )
                yield Label("Difficulty:", classes="menu-label")
                yield Select(
                    [(DIFFICULTY_LABELS[d], d) for d in DIFFICULTIES],
                    value=settings.get("difficulty", "medium"),
                    allow_blank=False,
                    id="menu-difficulty",
                )
                yield Label("Game mode:", classes="menu-label")
                yield Select(
                    [(RULESET_LABELS[r], r) for r in RULESETS],
                    value=settings.get("ruleset", "official"),
                    allow_blank=False,
                    id="menu-rules",
                )
                with Horizontal(id="menu-hints-row"):
                    yield Label("Hints:", classes="menu-label")
                    yield Switch(value=settings.get("mode") == "hints", id="menu-hints")
                yield Button("Play", variant="primary", id="menu-play")
                yield Button("Help", id="menu-help")
                yield Button("Statistics", id="menu-stats")
                yield Button("Quit", id="menu-quit")

    def on_mount(self) -> None:
        self._refresh_continue()
        self.query_one("#menu-play", Button).focus()

    def on_screen_resume(self) -> None:
        self._refresh_continue()

    def _refresh_continue(self) -> None:
        self.query_one("#menu-continue", Button).display = (
            load_game_snapshot() is not None
        )

    @on(Button.Pressed, "#menu-continue")
    def _continue(self) -> None:
        snapshot = load_game_snapshot()
        app = self.app
        assert isinstance(app, YahtzeeApp)
        if snapshot:
            config = GameConfig(
                difficulties=snapshot["config"]["difficulties"],
                mode=snapshot["config"].get("mode", "normal"),
                rules=snapshot["config"].get("rules", "official"),
            )
            app.start_game(config, snapshot=snapshot)

    @on(Button.Pressed, "#menu-play")
    def _play(self) -> None:
        n = self.query_one("#menu-bots", Select).value
        difficulty = self.query_one("#menu-difficulty", Select).value
        rules = str(self.query_one("#menu-rules", Select).value)
        hints = self.query_one("#menu-hints", Switch).value
        settings = load_settings()
        settings.update(
            {
                "n_bots": n,
                "difficulty": difficulty,
                "ruleset": rules,
                "mode": "hints" if hints else "normal",
            }
        )
        save_settings(settings)
        config = GameConfig(
            difficulties=[str(difficulty)] * int(n),
            mode="hints" if hints else "normal",
            rules=rules,
        )
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(config)

    @on(Button.Pressed, "#menu-help")
    def _help(self) -> None:
        self.app.push_screen(HelpScreen())

    @on(Button.Pressed, "#menu-stats")
    def _stats(self) -> None:
        self.app.notify("\n".join(stats_summary()), title="Statistics", timeout=8)

    @on(Button.Pressed, "#menu-quit")
    def _quit(self) -> None:
        self.app.exit()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# The game itself
# ---------------------------------------------------------------------------

FOOTER_KEYS = (
    " r roll   1-5 hold   ←→ dice   ↑↓ card   enter select   "
    "tab focus   shift+tab mode   h hint   / cmd   ? help"
)


class GameScreen(Screen):
    BINDINGS = [
        Binding("r,space", "roll", "Roll"),
        Binding("1", "hold(0)", "Hold", show=False),
        Binding("2", "hold(1)", show=False),
        Binding("3", "hold(2)", show=False),
        Binding("4", "hold(3)", show=False),
        Binding("5", "hold(4)", show=False),
        Binding("left,right", "focus_dice", show=False),
        Binding("up,down", "focus_card", show=False),
        Binding("h", "hint", "Hint"),
        Binding("shift+tab", "cycle_mode", "Mode", priority=True),
        Binding("slash", "command", "Command", show=False),
        Binding("question_mark,f1", "help", "Help"),
        Binding("n", "new_game", "New game", show=False),
        Binding("v", "review", "Review", show=False),
        Binding("escape", "back", "Menu", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, config: GameConfig, snapshot: dict | None = None) -> None:
        super().__init__()
        self.config = config
        self.mode = config.mode
        self.settings = load_settings()
        self.win_mode = bool(self.settings.get("win_mode", False))
        if snapshot:
            self.players, self.game, self.coach = self._restore(snapshot)
        else:
            self.players = build_players(config)
            self.game = Game(self.players, seed=config.seed)
            self.coach = CoachTracker()
        self.bots = {
            p.name: make_bot(p.difficulty, config.rules)
            for p in self.players
            if p.is_bot
        }
        self.oracle = get_optimal_oracle(config.rules)
        self._turn_worker = None
        self._rolling = False
        self._recorded = False
        self._final_accuracy: int | None = None

    # -- resume ------------------------------------------------------------

    def _restore(self, snap: dict) -> tuple[list[Player], Game, CoachTracker]:
        players = []
        for p in snap["players"]:
            card = Scorecard(self.config.rules)
            card.boxes = [b if b is None else int(b) for b in p["boxes"]]
            card.yahtzee_bonus_count = int(p.get("ybonus", 0))
            players.append(
                Player(p["name"], is_bot=p["bot"], difficulty=p.get("difficulty"), card=card)
            )
        game = Game(players)
        game.round = int(snap["round"])
        game.current_idx = int(snap["current_idx"])
        turn = snap.get("turn") or {}
        game.turn.dice = [int(d) for d in turn.get("dice", [1] * 5)]
        game.turn.held = [bool(h) for h in turn.get("held", [False] * 5)]
        game.turn.rolls_used = int(turn.get("rolls_used", 0))
        coach = CoachTracker(
            decisions=[Decision(**d) for d in snap.get("coach", [])]
        )
        return players, game, coach

    def _snapshot(self) -> dict:
        turn = self.game.turn
        return {
            "version": __version__,
            "config": {
                "difficulties": self.config.difficulties,
                "mode": self.mode,
                "rules": self.config.rules,
            },
            "round": self.game.round,
            "current_idx": self.game.current_idx,
            "turn": {
                "dice": turn.dice,
                "held": turn.held,
                "rolls_used": turn.rolls_used,
            },
            "players": [
                {
                    "name": p.name,
                    "bot": p.is_bot,
                    "difficulty": p.difficulty,
                    "boxes": p.card.boxes,
                    "ybonus": p.card.yahtzee_bonus_count,
                }
                for p in self.players
            ],
            "coach": [vars(d) for d in self.coach.decisions],
        }

    def checkpoint(self) -> None:
        if not self.game.finished:
            save_game_snapshot(self._snapshot())

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="game-root"):
            yield Static("", id="statusbar", markup=True)
            with Horizontal(id="game-columns"):
                with Vertical(id="left-column"):
                    with Horizontal(id="dice-area"):
                        yield DiceRow(id="dice-row")
                        with Vertical(id="roll-column"):
                            yield RollButton(id="roll-button")
                            yield Static("", id="turn-note", markup=True)
                    yield RichLog(id="log", markup=True, wrap=True, auto_scroll=True)
                    yield Input(
                        placeholder="/help for commands", id="command"
                    )
                with HorizontalScroll(id="cards-row"):
                    for i, p in enumerate(self.players):
                        yield PlayerCard(p, interactive=(i == 0))
            yield Static(FOOTER_KEYS, id="footer-keys")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        names = ", ".join(
            f"{p.name} ({p.difficulty})" for p in self.players if p.is_bot
        )
        log.write(f"[b]New game![/b] Opponents: {names}.")
        log.write(
            f"Game mode: [b]{RULESET_LABELS[self.config.rules]}[/b]"
            + ("  ·  [b]WIN[/b] mode on" if self.win_mode else "")
        )
        log.write("Type [b]/help[/b] or press [b]?[/b] for all keys and commands.")
        if self.mode == "hints":
            log.write("[yellow]Hint mode is on.[/yellow]")
        if self.mode == "coach":
            log.write("[yellow]Coach mode is on: every decision gets a verdict.[/yellow]")
        self.query_one(DiceRow).focus()
        self.refresh_all()
        self.call_after_refresh(self.start_turn)

    # -- helpers -----------------------------------------------------------

    @property
    def human(self) -> Player:
        return self.players[0]

    def is_human_turn(self) -> bool:
        return not self.game.finished and not self.game.current.is_bot

    def human_may_act(self) -> bool:
        return self.is_human_turn() and self.mode != "auto" and not self._rolling

    def log_write(self, text: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#log", RichLog).write(text)

    def delay(self) -> float:
        return SPEED_DELAYS.get(self.settings.get("speed", "normal"), 0.65)

    def rounds_left_for(self, player: Player) -> int:
        return sum(1 for b in player.card.boxes if b is None)

    def _win_context(self) -> winmode.WinContext:
        return winmode.build_context(
            self.human,
            [p for p in self.players if p.is_bot],
            self.oracle,
            self.rounds_left_for(self.human),
            self.win_mode,
        )

    def refresh_all(self) -> None:
        self.refresh_dice()
        self.refresh_cards()
        self.refresh_status()

    def refresh_dice(self) -> None:
        if not self.is_mounted:
            return
        turn = self.game.turn
        row = self.query_one(DiceRow)
        for i, die in enumerate(row.dice()):
            die.blank = turn.rolls_used == 0
            die.value = turn.dice[i]
            die.held = turn.held[i] and turn.rolls_used > 0
        button = self.query_one(RollButton)
        note = self.query_one("#turn-note", Static)
        if self.game.finished:
            button.enabled = False
            note.update("")
            return
        active = self.human_may_act()
        button.enabled = active and turn.can_roll()
        button.rolls_left = turn.rolls_left
        p = self.game.current
        if not p.is_bot and self.mode == "auto":
            note.update("[cyan]AUTO plays for you[/cyan]")
        elif p.is_bot:
            note.update(f"[dim]{p.name} is thinking...[/dim]")
        elif turn.rolls_used == 0:
            note.update("[b]Your turn![/b] press r")
        elif turn.rolls_left == 0:
            note.update("Pick a box on your card")
        else:
            note.update("Hold dice, roll again,\nor score now")

    def refresh_status(self) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#statusbar", Static)
        if self.game.finished:
            status.update(" [b]Game over[/b]")
            return
        p = self.game.current
        who = "[b yellow]YOUR TURN[/b yellow]" if not p.is_bot else f"turn: [b]{p.name}[/b]"
        win = "on" if self.win_mode else "off"
        status.update(
            f" YAHTZEE [dim]v{__version__}[/dim]  ·  round [b]{self.game.round}/13[/b]"
            f"  ·  {who}  ·  [b]{MODE_LABELS[self.mode]}[/b] [dim](shift+tab)[/dim]"
            f"  ·  win {win}  ·  [dim]{RULESET_LABELS[self.config.rules]}[/dim]"
        )

    def refresh_cards(self) -> None:
        if not self.is_mounted:
            return
        turn = self.game.turn
        preview: dict[int, str] = {}
        if self.is_human_turn() and turn.rolls_used > 0 and not self.game.finished:
            for opt in self.human.card.options(turn.counts()):
                marker = "!" if opt.forced else ""
                preview[opt.category] = f"{opt.points}{marker}"
        for card_widget in self.query(PlayerCard):
            is_turn = (
                not self.game.finished and card_widget.player is self.game.current
            )
            card_widget.set_state(
                is_turn, preview if card_widget.player is self.human else {}
            )

    # -- turn flow ---------------------------------------------------------

    def start_turn(self) -> None:
        if not self.is_mounted:
            return
        if self.game.finished:
            self.finish_game()
            return
        self.checkpoint()
        p = self.game.current
        self.refresh_all()
        if p.is_bot:
            self._turn_worker = self.run_worker(
                self._auto_turn(self.bots[p.name], p), exclusive=False
            )
        elif self.mode == "auto":
            self._turn_worker = self.run_worker(
                self._auto_turn(make_bot("optimal", self.config.rules), p),
                exclusive=False,
            )
        else:
            self.log_write(
                f"[b]-- Round {self.game.round}: your turn --[/b] (r to roll)"
            )

    async def _animate_roll(self) -> None:
        """A short shuffle of the rolling dice before the real result."""
        turn = self.game.turn
        if self.delay() == 0:
            return
        row = self.query_one(DiceRow)
        rng = random.Random()
        for _ in range(3):
            for i, die in enumerate(row.dice()):
                if turn.rolls_used == 0 or not turn.held[i]:
                    die.blank = False
                    die.value = rng.randint(1, 6)
            await asyncio.sleep(0.06)

    async def _do_roll(self) -> None:
        self._rolling = True
        try:
            await self._animate_roll()
            self.game.turn.roll()
        finally:
            self._rolling = False
        self.refresh_all()

    async def _auto_turn(self, bot, player: Player) -> None:
        """A bot's turn, or the human's turn in AUTO mode."""
        game = self.game
        turn = game.turn
        is_auto_human = not player.is_bot
        name = "AUTO" if is_auto_human else player.name
        ctx = winmode.WinContext(active=False)
        if is_auto_human and self.win_mode:
            ctx = self._win_context()
        try:
            while True:
                if player is not game.current or game.finished:
                    return
                if is_auto_human and self.mode != "auto":
                    self.log_write("[cyan]AUTO stopped; play on yourself.[/cyan]")
                    self.refresh_all()
                    return
                if turn.rolls_used == 0:
                    await self._do_roll()
                    await asyncio.sleep(self.delay())
                    continue
                counts = turn.counts()
                if turn.rolls_left > 0:
                    if ctx.active:
                        keep, note = winmode.choose_keep(
                            self.oracle, player.card, counts, turn.rolls_left, ctx
                        )
                        if note:
                            self.log_write(f"[magenta]{note}[/magenta]")
                    else:
                        keep = bot.choose_keep(player.card, counts, turn.rolls_left)
                    if keep != counts:
                        turn.set_holds_for(keep)
                        self.refresh_dice()
                        await asyncio.sleep(self.delay())
                        await self._do_roll()
                        await asyncio.sleep(self.delay())
                        continue
                break
            counts = turn.counts()
            option = bot.choose_option(player.card, counts)
            self._score(player, option, prefix=name, grade=False)
        except asyncio.CancelledError:
            pass

    def _score(self, player: Player, option, prefix: str | None = None, grade: bool = True) -> None:
        turn = self.game.turn
        counts = turn.counts()
        if grade and player is self.human:
            decision = record_score(
                self.coach,
                self.oracle,
                player.card,
                counts,
                option.category,
                self.game.round,
                rolls_left=turn.rolls_left,
            )
            if self.mode == "coach":
                self.log_write(f"[yellow]{verdict_line(decision)}[/yellow]")
        player.card.apply(option, counts)
        name = prefix or player.name
        extra = " [magenta]+100 yahtzee bonus![/magenta]" if option.extra_bonus else ""
        joker = " (joker)" if option.is_joker else ""
        dice_str = " ".join(str(d) for d in sorted(turn.dice))
        self.log_write(
            f"{name}: [{dice_str}] -> [b]{CATEGORY_NAMES[option.category]}[/b]"
            f"{joker}: {option.points} pts{extra}"
        )
        self.game.advance()
        self.refresh_all()
        self.set_timer(0.05, self.start_turn)

    def finish_game(self) -> None:
        if not self._recorded:
            self._recorded = True
            clear_saved_game()
            self._final_accuracy = (
                self.coach.accuracy() if self.coach.decisions else None
            )
            ranked = self.game.rankings()
            record_game(
                [(p.name, p.is_bot, p.difficulty, s) for p, s in ranked],
                rules=self.config.rules,
                accuracy=self._final_accuracy,
            )
            winner, _ = ranked[0]
            if winner.is_bot:
                self.log_write(f"[b]Game over! {winner.name} wins.[/b]")
            else:
                self.log_write("[b green]Game over! You win![/b green]")
        self.refresh_all()

        def done(result: str | None) -> None:
            if result == "new":
                self.action_new_game()
            elif result == "review":
                self.app.push_screen(
                    ReviewScreen(self.coach), lambda _: self.finish_game()
                )
            else:
                self.app.pop_screen()

        self.app.push_screen(GameOverScreen(self.game, self._final_accuracy), done)

    # -- human actions -----------------------------------------------------

    def action_roll(self) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if not turn.can_roll():
            if turn.rolls_left == 0:
                self.notify("No rolls left; pick a box on your card.", severity="warning")
            return
        if turn.rolls_used > 0:
            decision = record_keep(
                self.coach,
                self.oracle,
                self.human.card,
                turn.counts(),
                turn.held_counts(),
                turn.rolls_left,
                self.game.round,
            )
            if self.mode == "coach":
                self.log_write(f"[yellow]{verdict_line(decision)}[/yellow]")
        self.run_worker(self._human_roll(), exclusive=True, group="roll")

    async def _human_roll(self) -> None:
        await self._do_roll()
        turn = self.game.turn
        if turn.rolls_left == 0:
            self.log_write(
                f"Roll 3: [{' '.join(map(str, sorted(turn.dice)))}]. Pick a box."
            )
        if self.mode == "hints":
            self._show_hint()

    def action_hold(self, idx: int) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.notify("Roll first.", severity="warning")
            return
        if turn.rolls_left == 0:
            return
        turn.toggle_hold(idx)
        self.refresh_dice()

    @on(AsciiDie.Pressed)
    def _die_pressed(self, event: AsciiDie.Pressed) -> None:
        row = self.query_one(DiceRow)
        row.cursor_idx = event.index
        row.show_cursor(row.has_focus)
        self.action_hold(event.index)

    @on(RollButton.Rolled)
    def _roll_clicked(self) -> None:
        self.action_roll()

    @on(PlayerCard.CategoryPicked)
    def _category_picked(self, event: PlayerCard.CategoryPicked) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.notify("Roll first.", severity="warning")
            return
        try:
            option = self.human.card.score_option(event.category, turn.counts())
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self._score(self.human, option, prefix="You")

    def action_focus_dice(self) -> None:
        self.query_one(DiceRow).focus()

    def action_focus_card(self) -> None:
        self.query(PlayerCard).first().focus()

    def _show_hint(self) -> None:
        if not self.is_human_turn():
            self.notify("Hints only work during your turn.", severity="warning")
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.log_write("[yellow]Hint: roll first.[/yellow]")
            return
        for line in hint_for(self.oracle, self.human.card, turn.counts(), turn.rolls_left):
            self.log_write(f"[yellow]* {line}[/yellow]")
        if self.win_mode and turn.rolls_left > 0:
            ctx = self._win_context()
            if ctx.active:
                keep, note = winmode.choose_keep(
                    self.oracle, self.human.card, turn.counts(), turn.rolls_left, ctx
                )
                if note:
                    self.log_write(f"[magenta]* {note}[/magenta]")

    def action_hint(self) -> None:
        self._show_hint()

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.log_write(f"Mode: [b]{MODE_LABELS[self.mode]}[/b]")
        self.refresh_status()
        if mode == "hints" and self.is_human_turn() and self.game.turn.rolls_used > 0:
            self._show_hint()
        if mode == "auto" and self.is_human_turn():
            self.start_turn()
        self.refresh_dice()

    def action_cycle_mode(self) -> None:
        self._set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])

    def action_command(self) -> None:
        inp = self.query_one("#command", Input)
        inp.focus()
        if not inp.value:
            inp.value = "/"
            inp.cursor_position = 1

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_review(self) -> None:
        self.app.push_screen(ReviewScreen(self.coach, title="Review so far"))

    def action_new_game(self) -> None:
        clear_saved_game()
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(self.config, replace=True)

    def action_back(self) -> None:
        inp = self.query_one("#command", Input)
        if inp.has_focus:
            inp.value = ""
            self.query_one(DiceRow).focus()
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.checkpoint()
                self.app.pop_screen()

        self.app.push_screen(
            ConfirmScreen("Back to the menu? (the game is saved)"), done
        )

    def action_quit_app(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                self.checkpoint()
                self.app.exit()

        self.app.push_screen(ConfirmScreen("Quit Yahtzee? (the game is saved)"), done)

    # -- commands ----------------------------------------------------------

    @on(Input.Submitted, "#command")
    def _command_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        self.query_one(DiceRow).focus()
        if text:
            self.handle_command(text)

    def handle_command(self, text: str) -> None:
        if not text.startswith("/"):
            self.log_write("Commands start with '/'. Type /help for the list.")
            return
        parts = text[1:].split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]

        if cmd in ("help", "?"):
            self.app.push_screen(HelpScreen())
        elif cmd == "hint":
            self._show_hint()
        elif cmd == "hints":
            on_ = not args or args[0].lower() in ("on", "yes", "true")
            self._set_mode("hints" if on_ else "normal")
        elif cmd == "coach":
            on_ = not args or args[0].lower() in ("on", "yes", "true")
            self._set_mode("coach" if on_ else "normal")
        elif cmd == "auto":
            self._set_mode("auto" if self.mode != "auto" else "normal")
        elif cmd == "mode":
            if args and args[0].lower() in MODES:
                self._set_mode(args[0].lower())
            else:
                self.log_write("Usage: /mode normal|hints|coach|auto")
        elif cmd == "win":
            if args and args[0].lower() in ("on", "off"):
                self.win_mode = args[0].lower() == "on"
            else:
                self.win_mode = not self.win_mode
            self.settings["win_mode"] = self.win_mode
            save_settings(self.settings)
            state = "on" if self.win_mode else "off"
            self.log_write(
                f"WIN mode [b]{state}[/b]: endgame play in hints/AUTO now "
                f"{'targets win probability' if self.win_mode else 'maximizes points'}."
            )
            self.refresh_status()
        elif cmd == "review":
            self.action_review()
        elif cmd == "new":
            self._cmd_new(args)
        elif cmd == "rules":
            self.log_write(
                f"Game mode: [b]{RULESET_LABELS[self.config.rules]}[/b]. "
                f"{RULESET_INFO[self.config.rules]}"
            )
        elif cmd == "speed":
            if args and args[0].lower() in SPEED_DELAYS:
                self.settings["speed"] = args[0].lower()
                save_settings(self.settings)
                self.log_write(f"Bot speed: [b]{args[0].lower()}[/b]")
            else:
                self.log_write("Usage: /speed slow|normal|fast|instant")
        elif cmd == "stats":
            for line in stats_summary():
                self.log_write(f"[cyan]{line}[/cyan]")
        elif cmd == "update":
            self.log_write("Checking for updates...")
            app = self.app
            assert isinstance(app, YahtzeeApp)
            app.manual_update(self)
        elif cmd == "restart":
            self.checkpoint()
            app = self.app
            assert isinstance(app, YahtzeeApp)
            app.request_restart(resume=not self.game.finished)
        elif cmd == "version":
            self.log_write(f"Yahtzee v{current_version()}")
        elif cmd == "menu":
            self.checkpoint()
            self.app.pop_screen()
        elif cmd in ("quit", "exit", "stop"):
            self.action_quit_app()
        else:
            self.log_write(f"Unknown command: /{cmd}. Type [b]/help[/b] for all commands.")

    def _cmd_new(self, args: list[str]) -> None:
        n = None
        diffs: list[str] | None = None
        rules = self.config.rules
        for arg in args:
            if arg.isdigit():
                n = max(1, min(4, int(arg)))
            elif arg.lower() in RULESETS:
                rules = arg.lower()
            else:
                chosen = [d.strip().lower() for d in arg.split(",") if d.strip()]
                bad = next((d for d in chosen if d not in DIFFICULTIES), None)
                if bad:
                    self.log_write(
                        f"Unknown difficulty or mode: {bad}. Difficulties: "
                        f"{', '.join(DIFFICULTIES)}. Modes: {', '.join(RULESETS)}."
                    )
                    return
                diffs = chosen
        if diffs is None:
            default = self.config.difficulties[0] if self.config.difficulties else "medium"
            diffs = [default] * (n or len(self.config.difficulties) or 2)
        elif n is not None and len(diffs) == 1:
            diffs = diffs * n
        clear_saved_game()
        config = GameConfig(difficulties=diffs, mode=self.mode, rules=rules)
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(config, replace=True)

    def on_screen_resume(self) -> None:
        self.refresh_all()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class YahtzeeApp(App):
    TITLE = f"Yahtzee v{__version__}"

    CSS = """
    Screen { background: $surface; }

    /* Menu */
    #menu-center { align: center middle; height: 1fr; }
    #menu-box { width: 52; height: auto; max-height: 100%; overflow-y: auto; padding: 0 2; }
    #menu-logo { text-align: center; }
    #menu-version { text-align: center; color: $text-muted; width: 100%; }
    .menu-label { margin-top: 1; }
    #menu-hints-row { height: auto; margin-top: 1; }
    #menu-hints-row Label { padding-top: 1; }
    #menu-box Button { width: 100%; margin-top: 1; }

    /* Game */
    #game-root { height: 1fr; }
    #statusbar { height: 1; }
    #game-columns { height: 1fr; }
    #left-column { width: 1fr; min-width: 58; padding: 0 1; }
    #dice-area { height: 8; margin-top: 1; }
    DiceRow { width: 60; height: 8; layout: horizontal; }
    .die { width: 12; height: 7; }
    .die:hover { background: $boost; }
    #roll-column { width: 24; padding-top: 1; }
    #roll-button { height: 1; }
    #roll-button:hover { text-style: bold; }
    #turn-note { margin-top: 1; }
    #log {
        height: 1fr; margin-top: 1; background: $surface;
        scrollbar-size-vertical: 1;
        scrollbar-background: $surface; scrollbar-color: $boost;
    }
    #command { margin-top: 0; border: none; height: 1; background: $boost; }
    #cards-row { width: auto; padding: 0 1; }
    PlayerCard { width: 22; height: 21; margin-right: 1; }
    PlayerCard:focus { background: $boost; }
    #footer-keys { height: 1; color: $text-muted; }

    /* Modals */
    ConfirmScreen, HelpScreen, GameOverScreen, ReviewScreen { align: center middle; }
    #confirm-box, #gameover-box, #review-box {
        width: 56; height: auto; border: ascii $primary;
        padding: 1 2; background: $surface;
    }
    #confirm-buttons, #gameover-buttons { height: auto; margin-top: 1; align-horizontal: center; }
    #confirm-buttons Button, #gameover-buttons Button { margin-right: 2; }
    #help-box {
        width: 78; height: 90%; border: ascii $primary;
        padding: 1 2; background: $surface;
    }
    #help-text { height: 1fr; overflow-y: auto; }
    #help-close, #review-close { margin-top: 1; }
    """

    def __init__(
        self,
        no_update: bool = False,
        initial: dict | None = None,
        resume: bool = False,
    ) -> None:
        super().__init__()
        self.no_update = no_update
        self.initial = initial
        self.resume = resume
        self._restart_args: list[str] | None = None

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())
        if self.initial:
            config = GameConfig(
                difficulties=self.initial["difficulties"],
                rules=self.initial["rules"],
                seed=self.initial.get("seed"),
                mode=load_settings().get("mode", "normal"),
            )
            self.start_game(config)
        elif self.resume:
            snapshot = load_game_snapshot()
            if snapshot:
                config = GameConfig(
                    difficulties=snapshot["config"]["difficulties"],
                    mode=snapshot["config"].get("mode", "normal"),
                    rules=snapshot["config"].get("rules", "official"),
                )
                self.start_game(config, snapshot=snapshot)
        self._whats_new()
        if not self.no_update:
            self._update_check()

    def request_restart(self, resume: bool = False) -> None:
        """Exit and relaunch into the (possibly just-updated) code.

        The exec happens after app.run() returns, so the terminal is
        restored cleanly first. With resume=True the saved game reopens
        automatically.
        """
        self._restart_args = ["--no-update"] + (["--resume"] if resume else [])
        self.exit()

    def start_game(
        self, config: GameConfig, replace: bool = False, snapshot: dict | None = None
    ) -> None:
        if replace:
            self.pop_screen()
        self.push_screen(GameScreen(config, snapshot=snapshot))

    def _whats_new(self) -> None:
        from ..config import SETTINGS_FILE

        first_run = not SETTINGS_FILE.exists()
        settings = load_settings()
        last_seen = settings.get("last_seen_version")
        if last_seen == __version__:
            return
        settings["last_seen_version"] = __version__
        save_settings(settings)
        if first_run:
            return  # brand-new install: nothing to announce
        summary = _changelog_summary(__version__)
        if summary:
            self.notify(summary, title=f"What's new in v{__version__}", timeout=12)

    @work(thread=True, exclusive=True, group="update")
    def _update_check(self) -> None:
        result = check_and_update()
        if result.status == "updated":
            self.call_from_thread(self._apply_background_update, result)
        elif result.status == "failed":
            self.call_from_thread(
                self.notify, result.message, title="Update", severity="warning", timeout=10
            )

    def _apply_background_update(self, result) -> None:
        """A background update landed: apply it immediately when possible."""
        in_game = any(isinstance(s, GameScreen) for s in self.screen_stack)
        if not in_game:
            # Still on the menu: relaunch seamlessly into the new version.
            self.request_restart(resume=False)
            return
        self.notify(
            f"Update installed: v{result.new_version or '?'}. "
            f"Type /restart to apply now (your game is saved).",
            title="Update",
            timeout=10,
        )

    def manual_update(self, screen: GameScreen) -> None:
        self._manual_update(screen)

    @work(thread=True, exclusive=True, group="update")
    def _manual_update(self, screen: GameScreen) -> None:
        result = check_and_update()
        if result.status == "updated":
            self.call_from_thread(self._apply_manual_update, screen, result)
            return
        color = {"uptodate": "cyan", "failed": "red"}.get(result.status, "white")
        self.call_from_thread(screen.log_write, f"[{color}]{result.message}[/{color}]")

    def _apply_manual_update(self, screen: GameScreen, result) -> None:
        screen.log_write(
            f"[green]Update installed: v{result.new_version or '?'}. "
            f"Restarting...[/green]"
        )
        screen.checkpoint()
        self.request_restart(resume=not screen.game.finished)


def _changelog_summary(version: str, max_lines: int = 6) -> str | None:
    """First lines of this version's CHANGELOG.md section."""
    path = Path(REPO_DIR) / "CHANGELOG.md"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("## "):
            if in_section:
                break
            in_section = version in line
            continue
        if in_section and line.strip():
            out.append(line.strip().lstrip("- "))
            if len(out) >= max_lines:
                break
    return "\n".join(out) if out else None


def run(no_update: bool = False, initial: dict | None = None, resume: bool = False) -> None:
    import os
    import sys

    app = YahtzeeApp(no_update=no_update, initial=initial, resume=resume)
    app.run()
    if app._restart_args is not None:
        # Terminal state is restored at this point; swap in the new code.
        os.execv(
            sys.executable,
            [sys.executable, "-m", "yahtzee_app", *app._restart_args],
        )
