"""The Yahtzee TUI: fully playable with mouse, keyboard, and commands."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
)

from .. import __version__
from ..bots import (
    BOT_NAMES,
    DIFFICULTIES,
    DIFFICULTY_INFO,
    DIFFICULTY_LABELS,
    get_optimal_oracle,
    make_bot,
)
from ..config import (
    SPEED_DELAYS,
    load_settings,
    record_game,
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
from ..update import check_and_update, current_version, restart

MODES = ["normal", "hints", "auto"]
MODE_LABELS = {"normal": "NORMAL", "hints": "HINTS", "auto": "AUTO"}

HUMAN_NAME = "You"


@dataclass
class GameConfig:
    difficulties: list[str] = field(default_factory=lambda: ["medium", "medium"])
    mode: str = "normal"
    rules: str = "official"


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
# Widgets
# ---------------------------------------------------------------------------


class DieWidget(Static):
    """A single die; click to hold."""

    value: reactive[int] = reactive(1)
    held: reactive[bool] = reactive(False)
    empty: reactive[bool] = reactive(True)

    class Pressed(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    PIPS = {
        1: [(1, 1)],
        2: [(0, 2), (2, 0)],
        3: [(0, 2), (1, 1), (2, 0)],
        4: [(0, 0), (0, 2), (2, 0), (2, 2)],
        5: [(0, 0), (0, 2), (1, 1), (2, 0), (2, 2)],
        6: [(0, 0), (0, 2), (1, 0), (1, 2), (2, 0), (2, 2)],
    }

    def __init__(self, index: int) -> None:
        super().__init__(classes="die")
        self.index = index
        self.border_title = str(index + 1)

    def render(self) -> Text:
        if self.empty:
            return Text("\n   ?   \n", style="dim")
        lines = []
        pips = self.PIPS[self.value]
        for r in range(3):
            row = [" "] * 7
            for pr, pc in pips:
                if pr == r:
                    row[1 + 2 * pc] = "●"
            lines.append("".join(row))
        return Text("\n".join(lines))

    def watch_held(self, held: bool) -> None:
        self.set_class(held, "held")
        self.border_subtitle = "HELD" if held else ""

    def watch_value(self, _: int) -> None:
        self.refresh()

    def watch_empty(self, _: bool) -> None:
        self.refresh()

    def on_click(self) -> None:
        self.post_message(self.Pressed(self.index))


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
  [b]space / r[/b]      roll
  [b]1 to 5[/b]         hold / release a die (or click it)
  [b]arrow keys[/b]     pick a category on the scorecard
  [b]enter / click[/b]  score the selected category
  [b]h[/b]              hint (from the optimal solver)
  [b]shift+tab[/b]      switch mode: NORMAL, HINTS, AUTO
  [b]/[/b]              open the command bar
  [b]?[/b] or [b]F1[/b]        this help
  [b]n[/b]              new game (same settings)
  [b]escape[/b]         back / to menu
  [b]q[/b]              quit

[b u]Commands[/b u]  (type / followed by the command)
  [b]/help[/b] or [b]/?[/b]     this help
  [b]/hint[/b]           one-off hint for the current situation
  [b]/hints on|off[/b]   hint mode on or off (advice after every roll)
  [b]/auto[/b]           auto mode on/off (the solver plays your turns)
  [b]/mode X[/b]         pick a mode: normal, hints, or auto
  [b]/new [n] [level] [rules][/b]  new game, e.g. /new 3 optimal simple
                    or mixed levels: /new easy,medium,optimal
  [b]/rules[/b]          show the active rule variant
  [b]/speed X[/b]        bot speed: slow, normal, fast, instant
  [b]/stats[/b]          your statistics
  [b]/update[/b]         check for updates now and install
  [b]/restart[/b]        restart the app (after an update)
  [b]/version[/b]        show the version
  [b]/menu[/b]           back to the main menu
  [b]/quit[/b]           quit

[b u]Modes[/b u]
  [b]NORMAL[/b]  regular play
  [b]HINTS[/b]   advice from the optimal solver after every roll, with EV
  [b]AUTO[/b]    the solver plays your turns automatically

[b u]Opponents[/b u]
  [b]Easy[/b]     {DIFFICULTY_INFO['easy']}
  [b]Medium[/b]   {DIFFICULTY_INFO['medium']}
  [b]Hard[/b]     {DIFFICULTY_INFO['hard']}
  [b]Optimal[/b]  {DIFFICULTY_INFO['optimal']}

[b u]Game modes (rule variants)[/b u]
  [b]Official[/b]     {RULESET_INFO['official']}
  [b]Free joker[/b]   {RULESET_INFO['free_joker']}
  [b]Simple[/b]       {RULESET_INFO['simple']}

[b u]Rules in short[/b u]
13 rounds; up to 3 rolls per turn, holding dice in between.
Upper section: 63+ points earns a 35-point bonus. Extra yahtzees
score per the selected game mode (see above).

The solver, hints, and bot levels are based on the video
[i]I Solved Yahtzee*[/i] by Ballpark Figures (Patrick Liscio):
dynamic programming over all scorecard states, expected score ~254.6.
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape,q,question_mark,f1", "dismiss_help", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-box"):
            yield Static(HELP_TEXT, id="help-text", markup=True)
            yield Button("Close (esc)", id="help-close")

    @on(Button.Pressed, "#help-close")
    def _close(self) -> None:
        self.dismiss()

    def action_dismiss_help(self) -> None:
        self.dismiss()


class GameOverScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("n", "result('new')", "New game"),
        Binding("escape,m", "result('menu')", "Menu"),
    ]

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        ranked = self.game.rankings()
        winner, _ = ranked[0]
        lines = []
        title = "🎉 You win!" if not winner.is_bot else f"{winner.name} wins"
        for i, (p, score) in enumerate(ranked, start=1):
            diff = f" ({DIFFICULTY_LABELS[p.difficulty].lower()})" if p.difficulty else ""
            lines.append(f"  {i}. {p.name}{diff}: [b]{score}[/b] points")
        text = f"[b]{title}[/b]\n\n" + "\n".join(lines)
        with Container(id="gameover-box"):
            yield Static(text, id="gameover-text", markup=True)
            with Horizontal(id="gameover-buttons"):
                yield Button("New game (n)", variant="primary", id="new")
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
        logo = Text("\n▄██▄  YAHTZEE  ▄██▄\n", style="bold yellow")
        with Center(id="menu-center"):
            with Vertical(id="menu-box"):
                yield Static(logo, id="menu-logo")
                yield Label(f"v{__version__}", id="menu-version")
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
                yield Button("▶  Play", variant="primary", id="menu-play")
                yield Button("Help", id="menu-help")
                yield Button("Statistics", id="menu-stats")
                yield Button("Quit", id="menu-quit")
                yield Static("", id="menu-status", markup=True)

    def on_mount(self) -> None:
        self.query_one("#menu-play", Button).focus()

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


class GameScreen(Screen):
    BINDINGS = [
        Binding("space,r", "roll", "Roll"),
        Binding("1", "hold(0)", "Hold", show=False),
        Binding("2", "hold(1)", show=False),
        Binding("3", "hold(2)", show=False),
        Binding("4", "hold(3)", show=False),
        Binding("5", "hold(4)", show=False),
        Binding("h", "hint", "Hint"),
        Binding("shift+tab", "cycle_mode", "Mode", priority=True),
        Binding("slash", "command", "Command", show=False),
        Binding("question_mark,f1", "help", "Help"),
        Binding("n", "new_game", "New game", show=False),
        Binding("escape", "back", "Menu", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, config: GameConfig) -> None:
        super().__init__()
        self.config = config
        self.mode = config.mode
        self.settings = load_settings()
        self.players = build_players(config)
        self.game = Game(self.players)
        self.bots = {
            p.name: make_bot(p.difficulty, config.rules)
            for p in self.players
            if p.is_bot
        }
        self.oracle = get_optimal_oracle(config.rules)
        self._turn_worker = None
        self._recorded = False

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="game-grid"):
            with Vertical(id="left"):
                yield Static("", id="statusbar", markup=True)
                with Horizontal(id="dice-row"):
                    for i in range(5):
                        yield DieWidget(i)
                    with Vertical(id="roll-column"):
                        yield Button("Roll!", variant="primary", id="roll-button")
                        yield Static("", id="rolls-label")
                yield RichLog(id="log", markup=True, wrap=True, auto_scroll=True)
                yield Input(
                    placeholder="/help for all commands; / opens this bar",
                    id="command",
                )
            with Vertical(id="right"):
                yield DataTable(id="scorecard", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#scorecard", DataTable)
        table.add_column("Category", key="cat", width=16)
        for i, p in enumerate(self.players):
            table.add_column(p.name, key=f"p{i}", width=max(7, len(p.name) + 1))
        for c in range(6):
            table.add_row(CATEGORY_NAMES[c], *([""] * len(self.players)), key=f"cat-{c}")
        table.add_row(Text("Subtotal", style="dim"), *([""] * len(self.players)), key="sub-upper")
        table.add_row(Text("Bonus (63+)", style="dim"), *([""] * len(self.players)), key="bonus")
        for c in range(6, N_CATEGORIES):
            table.add_row(CATEGORY_NAMES[c], *([""] * len(self.players)), key=f"cat-{c}")
        table.add_row(Text("Yahtzee bonus", style="dim"), *([""] * len(self.players)), key="ybonus")
        table.add_row(Text("TOTAL", style="bold"), *([""] * len(self.players)), key="total")
        table.focus()

        log = self.query_one("#log", RichLog)
        names = ", ".join(
            f"{p.name} ({DIFFICULTY_LABELS[p.difficulty].lower()})"
            for p in self.players
            if p.is_bot
        )
        log.write(f"[b]New game![/b] Opponents: {names}.")
        log.write(f"Game mode: [b]{RULESET_LABELS[self.config.rules]}[/b]")
        log.write("Type [b]/help[/b] or press [b]?[/b] for all keys and commands.")
        if self.mode == "hints":
            log.write("[yellow]Hint mode is on.[/yellow]")
        self.refresh_table()
        self.start_turn()

    # -- helpers -----------------------------------------------------------

    @property
    def human(self) -> Player:
        return self.players[0]

    def is_human_turn(self) -> bool:
        return not self.game.finished and not self.game.current.is_bot

    def human_may_act(self) -> bool:
        return self.is_human_turn() and self.mode != "auto"

    def log_write(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def delay(self) -> float:
        return SPEED_DELAYS.get(self.settings.get("speed", "normal"), 0.65)

    def refresh_dice(self) -> None:
        turn = self.game.turn
        for i, w in enumerate(self.query(DieWidget)):
            w.empty = turn.rolls_used == 0
            w.value = turn.dice[i]
            w.held = turn.held[i] and turn.rolls_used > 0
        button = self.query_one("#roll-button", Button)
        label = self.query_one("#rolls-label", Static)
        if self.game.finished:
            button.disabled = True
            label.update("")
            return
        active = self.human_may_act()
        button.disabled = not (active and turn.can_roll())
        button.label = "Roll!" if turn.rolls_used == 0 else "Roll again"
        label.update(f"rolls left: {turn.rolls_left}")
        self.refresh_status()

    def refresh_status(self) -> None:
        status = self.query_one("#statusbar", Static)
        if self.game.finished:
            status.update("[b]Game over[/b]")
            return
        p = self.game.current
        who = "[b green]your turn[/b green]" if not p.is_bot else f"turn: [b]{p.name}[/b]"
        status.update(
            f"Round [b]{self.game.round}/13[/b]  |  {who}  |  "
            f"mode: [b]{MODE_LABELS[self.mode]}[/b] (shift+tab)  |  v{__version__}"
        )

    def refresh_table(self) -> None:
        table = self.query_one("#scorecard", DataTable)
        turn = self.game.turn
        show_preview = (
            self.is_human_turn() and turn.rolls_used > 0 and not self.game.finished
        )
        preview: dict[int, str] = {}
        if show_preview:
            for opt in self.human.card.options(turn.counts()):
                marker = "!" if opt.forced else ""
                preview[opt.category] = f"{opt.points}{marker}"
        for i, p in enumerate(self.players):
            col = f"p{i}"
            card = p.card
            for c in range(N_CATEGORIES):
                val = card.boxes[c]
                if val is not None:
                    cell: Text | str = Text(str(val), style="bold")
                elif i == 0 and c in preview:
                    cell = Text(f"→{preview[c]}", style="cyan")
                elif i == 0 and show_preview:
                    cell = Text("×", style="dim")  # joker rules forbid this box now
                else:
                    cell = Text("·", style="dim")
                table.update_cell(f"cat-{c}", col, cell)
            table.update_cell("sub-upper", col, Text(str(card.upper_subtotal()), style="dim"))
            bonus = card.upper_bonus()
            table.update_cell("bonus", col, Text(str(bonus), style="green" if bonus else "dim"))
            yb = card.yahtzee_bonus_count * 100
            table.update_cell("ybonus", col, Text(str(yb), style="magenta" if yb else "dim"))
            table.update_cell("total", col, Text(str(card.total()), style="bold yellow"))

    # -- turn flow ---------------------------------------------------------

    def start_turn(self) -> None:
        if self.game.finished:
            self.finish_game()
            return
        p = self.game.current
        self.refresh_dice()
        self.refresh_table()
        if p.is_bot:
            self._turn_worker = self.run_worker(
                self._auto_turn(self.bots[p.name], p), exclusive=False
            )
        elif self.mode == "auto":
            self.log_write("[cyan]AUTO is playing your turn...[/cyan]")
            self._turn_worker = self.run_worker(
                self._auto_turn(make_bot("optimal", self.config.rules), p),
                exclusive=False,
            )
        else:
            self.log_write(
                f"[b]— Round {self.game.round}: your turn —[/b] (space to roll)"
            )

    async def _auto_turn(self, bot, player: Player) -> None:
        """A bot's turn, or the human's turn in AUTO mode."""
        game = self.game
        turn = game.turn
        name = "AUTO" if not player.is_bot else player.name
        try:
            while True:
                if player is not game.current or game.finished:
                    return
                if not player.is_bot and self.mode != "auto":
                    # User switched AUTO off: hand the turn back.
                    self.log_write("[cyan]AUTO stopped; play on yourself.[/cyan]")
                    self.refresh_dice()
                    return
                if turn.rolls_used == 0:
                    turn.roll()
                    self.refresh_dice()
                    self.refresh_table()
                    await asyncio.sleep(self.delay())
                    continue
                counts = turn.counts()
                if turn.rolls_left > 0:
                    keep = bot.choose_keep(player.card, counts, turn.rolls_left)
                    if keep != counts:
                        turn.set_holds_for(keep)
                        self.refresh_dice()
                        await asyncio.sleep(self.delay())
                        turn.roll()
                        self.refresh_dice()
                        self.refresh_table()
                        await asyncio.sleep(self.delay())
                        continue
                break
            counts = turn.counts()
            option = bot.choose_option(player.card, counts)
            self._score(player, option, prefix=name)
        except asyncio.CancelledError:
            pass

    def _score(self, player: Player, option, prefix: str | None = None) -> None:
        counts = self.game.turn.counts()
        player.card.apply(option, counts)
        name = prefix or player.name
        extra = " [magenta]+100 yahtzee bonus![/magenta]" if option.extra_bonus else ""
        joker = " (joker)" if option.is_joker else ""
        dice_str = " ".join(str(d) for d in sorted(self.game.turn.dice))
        self.log_write(
            f"{name}: [{dice_str}] → [b]{CATEGORY_NAMES[option.category]}[/b]"
            f"{joker}: {option.points} pts{extra}"
        )
        self.game.advance()
        self.refresh_table()
        self.refresh_dice()
        self.set_timer(0.05, self.start_turn)

    def finish_game(self) -> None:
        if not self._recorded:
            self._recorded = True
            ranked = self.game.rankings()
            record_game([(p.name, p.is_bot, p.difficulty, s) for p, s in ranked])
            winner, _ = ranked[0]
            if winner.is_bot:
                self.log_write(f"[b]Game over! {winner.name} wins.[/b]")
            else:
                self.log_write("[b green]Game over! You win![/b green]")
        self.refresh_dice()

        def done(result: str | None) -> None:
            if result == "new":
                self.action_new_game()
            else:
                self.app.pop_screen()

        self.app.push_screen(GameOverScreen(self.game), done)

    # -- human actions -----------------------------------------------------

    def action_roll(self) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if not turn.can_roll():
            if turn.rolls_left == 0:
                self.notify("No rolls left; pick a category.", severity="warning")
            return
        turn.roll()
        self.refresh_dice()
        self.refresh_table()
        if turn.rolls_left == 0:
            self.log_write(
                f"Roll 3: [{' '.join(map(str, sorted(turn.dice)))}]. Pick a category."
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

    @on(DieWidget.Pressed)
    def _die_click(self, event: DieWidget.Pressed) -> None:
        self.action_hold(event.index)

    @on(Button.Pressed, "#roll-button")
    def _roll_button(self) -> None:
        self.action_roll()

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value or ""
        if not key.startswith("cat-"):
            return
        if not self.human_may_act():
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.notify("Roll first.", severity="warning")
            return
        cat = int(key.split("-")[1])
        try:
            option = self.human.card.score_option(cat, turn.counts())
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self._score(self.human, option, prefix="You")

    def _show_hint(self) -> None:
        if not self.is_human_turn():
            self.notify("Hints only work during your turn.", severity="warning")
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.log_write("[yellow]Hint: roll first.[/yellow]")
            return
        for line in hint_for(self.oracle, self.human.card, turn.counts(), turn.rolls_left):
            self.log_write(f"[yellow]💡 {line}[/yellow]")

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

    def action_new_game(self) -> None:
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(self.config, replace=True)

    def action_back(self) -> None:
        inp = self.query_one("#command", Input)
        if inp.has_focus:
            inp.value = ""
            self.query_one("#scorecard", DataTable).focus()
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.app.pop_screen()

        self.app.push_screen(ConfirmScreen("Leave this game and return to the menu?"), done)

    def action_quit_app(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                self.app.exit()

        self.app.push_screen(ConfirmScreen("Quit Yahtzee?"), done)

    # -- commands ----------------------------------------------------------

    @on(Input.Submitted, "#command")
    def _command_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        self.query_one("#scorecard", DataTable).focus()
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
        elif cmd == "auto":
            self._set_mode("auto" if self.mode != "auto" else "normal")
        elif cmd == "mode":
            if args and args[0].lower() in MODES:
                self._set_mode(args[0].lower())
            else:
                self.log_write("Usage: /mode normal|hints|auto")
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
            restart()
        elif cmd == "version":
            self.log_write(f"Yahtzee v{current_version()}")
        elif cmd == "menu":
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
        config = GameConfig(difficulties=diffs, mode=self.mode, rules=rules)
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(config, replace=True)

    def on_screen_resume(self) -> None:
        self.refresh_dice()
        self.refresh_table()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class YahtzeeApp(App):
    TITLE = f"Yahtzee v{__version__}"

    CSS = """
    Screen {
        background: $surface;
    }

    /* Menu */
    #menu-center { align: center middle; height: 1fr; }
    #menu-box {
        width: 44;
        height: auto;
        border: round $primary;
        padding: 1 2;
    }
    #menu-logo { text-align: center; }
    #menu-version { text-align: center; color: $text-muted; margin-bottom: 1; width: 100%; }
    .menu-label { margin-top: 1; }
    #menu-hints-row { height: auto; margin-top: 1; }
    #menu-hints-row Label { padding-top: 1; }
    #menu-box Button { width: 100%; margin-top: 1; }
    #menu-status { margin-top: 1; text-align: center; color: $text-muted; }

    /* Game */
    #game-grid { height: 1fr; }
    #left { width: 1fr; padding: 0 1; }
    #right { width: auto; padding: 0 1; }
    #statusbar { height: 1; margin-top: 1; }
    #dice-row { height: 7; margin-top: 1; }
    .die {
        width: 9;
        height: 5;
        border: round gray;
        margin-right: 1;
        content-align: center middle;
    }
    .die.held {
        border: heavy $warning;
        color: $warning;
    }
    #roll-column { width: 16; }
    #roll-button { width: 14; }
    #rolls-label { margin-top: 1; text-align: center; width: 14; }
    #log {
        height: 1fr;
        border: round gray;
        margin-top: 1;
        padding: 0 1;
    }
    #command { margin-top: 1; }
    #scorecard { height: 1fr; margin-top: 1; }

    /* Modals */
    ConfirmScreen, HelpScreen, GameOverScreen { align: center middle; }
    #confirm-box, #gameover-box {
        width: 50;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #confirm-buttons, #gameover-buttons { height: auto; margin-top: 1; align-horizontal: center; }
    #confirm-buttons Button, #gameover-buttons Button { margin-right: 2; }
    #help-box {
        width: 76;
        height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    #help-text { height: 1fr; overflow-y: auto; }
    #help-close { margin-top: 1; }
    """

    def __init__(self, no_update: bool = False) -> None:
        super().__init__()
        self.no_update = no_update

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())
        if not self.no_update:
            self._update_check()

    def start_game(self, config: GameConfig, replace: bool = False) -> None:
        if replace:
            self.pop_screen()
        self.push_screen(GameScreen(config))

    @work(thread=True, exclusive=True, group="update")
    def _update_check(self) -> None:
        result = check_and_update()
        if result.status == "updated":
            self.call_from_thread(self.notify, result.message, title="Update", timeout=10)
        elif result.status == "failed":
            self.call_from_thread(
                self.notify, result.message, title="Update", severity="warning", timeout=10
            )

    def manual_update(self, screen: GameScreen) -> None:
        self._manual_update(screen)

    @work(thread=True, exclusive=True, group="update")
    def _manual_update(self, screen: GameScreen) -> None:
        result = check_and_update()
        color = {"updated": "green", "uptodate": "cyan", "failed": "red"}.get(
            result.status, "white"
        )
        self.call_from_thread(screen.log_write, f"[{color}]{result.message}[/{color}]")


def run(no_update: bool = False) -> None:
    YahtzeeApp(no_update=no_update).run()
