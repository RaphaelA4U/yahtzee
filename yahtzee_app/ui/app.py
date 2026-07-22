"""The Yahtzee TUI, Claude-terminal style.

Design rules:
- The terminal's own colors: default background and foreground everywhere,
  with purple (ANSI magenta) as the selection/focus accent.
- Everything is text and ASCII. No buttons, no dialogs, no popups: menus
  are arrow-navigable text, confirmations do not exist (games auto-save),
  and help/stats/review are full pages you enter and leave with escape.
- Arrow keys work everywhere; the mouse works everywhere (hover highlights,
  click activates).
- Every player has their own score card, with a column per game of the
  match, like the classic paper pad.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from .. import __version__
from .. import winmode
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
    UPPER,
    UPPER_BONUS_THRESHOLD,
    Game,
    Player,
    Scorecard,
)
from ..hints import hint_for
from ..update import REPO_DIR, check_and_update, current_version

MODES = ["normal", "hints", "coach", "auto"]
MODE_LABELS = {"normal": "NORMAL", "hints": "HINTS", "coach": "COACH", "auto": "AUTO"}

HUMAN_NAME = "You"
ACCENT = "magenta"  # Claude-style purple selection/focus color

SHEET_LABELS = [
    "Ones", "Twos", "Threes", "Fours", "Fives", "Sixes",
    "3 of a Kind", "4 of a Kind", "Full House", "Sm Straight", "Lg Straight",
    "YAHTZEE", "Chance",
]

# figlet "DOS Rebel"
LOGO = """\
                      █████       █████
                     ░░███       ░░███
 █████ ████  ██████   ░███████   ███████    █████████  ██████   ██████
░░███ ░███  ░░░░░███  ░███░░███ ░░░███░    ░█░░░░███  ███░░███ ███░░███
 ░███ ░███   ███████  ░███ ░███   ░███     ░   ███░  ░███████ ░███████
 ░███ ░███  ███░░███  ░███ ░███   ░███ ███   ███░   █░███░░░  ░███░░░
 ░░███████ ░░████████ ████ █████  ░░█████   █████████░░██████ ░░██████
  ░░░░░███  ░░░░░░░░ ░░░░ ░░░░░    ░░░░░   ░░░░░░░░░  ░░░░░░   ░░░░░░
  ███ ░███
 ░░██████
  ░░░░░░
"""

DIE_ROWS = {
    1: ["       ", "   o   ", "       "],
    2: [" o     ", "       ", "     o "],
    3: [" o     ", "   o   ", "     o "],
    4: [" o   o ", "       ", " o   o "],
    5: [" o   o ", "   o   ", " o   o "],
    6: [" o   o ", " o   o ", " o   o "],
}


def dice_art(values: list[int]) -> str:
    """Five ASCII dice side by side (for the menu)."""
    lines = ["", "", "", "", "", ""]
    for v in values:
        rows = DIE_ROWS[v]
        lines[0] += ".-------.    "
        lines[1] += f"|{rows[0]}|\\   "
        lines[2] += f"|{rows[1]}| |  "
        lines[3] += f"|{rows[2]}| |  "
        lines[4] += "'-------' |  "
        lines[5] += " \\________\\|  "
    return "\n".join(lines)


@dataclass
class GameConfig:
    difficulties: list[str] = field(default_factory=lambda: ["medium", "medium"])
    mode: str = "normal"
    rules: str = "official"
    n_games: int = 3
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
    """A 3D ASCII die with a drop shadow. Click to hold, hover to highlight."""

    value: reactive[int] = reactive(1)
    held: reactive[bool] = reactive(False)
    blank: reactive[bool] = reactive(True)
    cursor: reactive[bool] = reactive(False)
    hovered: reactive[bool] = reactive(False)

    class Pressed(Message):
        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    def __init__(self, index: int) -> None:
        super().__init__(classes="die")
        self.index = index

    def render(self) -> Text:
        rows = ["       ", "   ?   ", "       "] if self.blank else DIE_ROWS[self.value]
        if self.held:
            face = f"bold {ACCENT}"
        elif self.cursor or self.hovered:
            face = "bold"
        elif self.blank:
            face = "dim"
        else:
            face = ""
        art = Text(no_wrap=True)
        art.append(".-------.  \n", style=face)
        for i, row in enumerate(rows):
            shadow = "\\ " if i == 0 else " |"
            art.append(f"|{row}|", style=face)
            art.append(f"{shadow}\n", style="dim")
        art.append("'-------'", style=face)
        art.append(" |\n", style="dim")
        art.append(" \\________\\|\n", style="dim")
        if self.held:
            label = f">[{self.index + 1}] HELD" if self.cursor else f" [{self.index + 1}] HELD"
            art.append(label.center(11), style=f"bold {ACCENT}")
        elif self.cursor:
            art.append(f">({self.index + 1})<".center(11), style="bold")
        else:
            art.append(f"({self.index + 1})".center(11), style="bold" if self.hovered else "dim")
        return art

    def watch_value(self, _) -> None:
        self.refresh()

    def watch_held(self, _) -> None:
        self.refresh()

    def watch_blank(self, _) -> None:
        self.refresh()

    def watch_cursor(self, _) -> None:
        self.refresh()

    def watch_hovered(self, _) -> None:
        self.refresh()

    def on_enter(self) -> None:
        self.hovered = True

    def on_leave(self) -> None:
        self.hovered = False

    def on_click(self) -> None:
        self.post_message(self.Pressed(self.index))


class DiceRow(Widget, can_focus=True):
    """The five dice plus an arrow-key cursor. Gets an accent border when
    it is your move to roll."""

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


class RollAction(Static):
    """The roll action as plain text: hover or focus highlights it."""

    enabled: reactive[bool] = reactive(True)
    rolls_left: reactive[int] = reactive(3)
    hovered: reactive[bool] = reactive(False)

    class Rolled(Message):
        pass

    def render(self) -> Text:
        if not self.enabled:
            return Text("  roll (r)", style="dim")
        style = f"bold {ACCENT}" if self.hovered else "bold"
        return Text.assemble(
            ("> Roll (r)", style),
            (f"   {self.rolls_left} left", "dim"),
        )

    def watch_enabled(self, _) -> None:
        self.refresh()

    def watch_rolls_left(self, _) -> None:
        self.refresh()

    def watch_hovered(self, _) -> None:
        self.refresh()

    def on_enter(self) -> None:
        self.hovered = True

    def on_leave(self) -> None:
        self.hovered = False

    def on_click(self) -> None:
        if self.enabled:
            self.post_message(self.Rolled())


# ---------------------------------------------------------------------------
# Score cards: one card per player, one column per game (like the paper pad)
# ---------------------------------------------------------------------------

LABEL_W = 13
COL_W = 6


class PlayerCard(Widget):
    """One player's score card with a column per game of the match.

    Only the active game column of YOUR card is interactive: arrows move
    over the open boxes, enter (or a click) fills the selected box.
    Cyan numbers preview the current dice; 'x' previews a cross-out
    (zero); '-' means the joker rules forbid that box right now.
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("space,enter", "pick", "Score", show=False),
    ]

    class CategoryPicked(Message):
        def __init__(self, category: int) -> None:
            self.category = category
            super().__init__()

    cursor_cat: reactive[int | None] = reactive(None)
    hovered_cat: reactive[int | None] = reactive(None)

    def __init__(self, player: Player, n_games: int, interactive: bool) -> None:
        super().__init__(classes="playercard")
        self.player = player
        self.n_games = n_games
        self.interactive = interactive
        self.can_focus = interactive
        self.is_turn = False
        self.match_over = False
        self.preview: dict[int, str] = {}
        self.line_to_cat = {**{i + 3: i for i in range(6)}, **{i + 7: i for i in range(6, 13)}}

    # -- data --------------------------------------------------------------

    def set_state(self, is_turn: bool, preview: dict[int, str], match_over: bool) -> None:
        self.is_turn = is_turn
        self.match_over = match_over
        self.preview = preview
        if not preview:
            self.cursor_cat = None
        elif self.cursor_cat not in preview:
            self.cursor_cat = next(iter(sorted(preview)), None)
        self.refresh()

    def _column_cards(self) -> list[Scorecard | None]:
        """Card per game column: finished games, the active game, then None."""
        cols: list[Scorecard | None] = list(self.player.history)
        if not self.match_over:
            cols.append(self.player.card)
        while len(cols) < self.n_games:
            cols.append(None)
        return cols[: self.n_games]

    @property
    def active_col(self) -> int:
        return len(self.player.history)

    # -- rendering ---------------------------------------------------------

    def _sep(self, heavy: bool = False) -> Text:
        ch = "=" if heavy else "-"
        line = "+" + ch * LABEL_W + ("+" + ch * COL_W) * self.n_games + "+"
        return Text(line + "\n", style="dim", no_wrap=True)

    def _row(self, label: Text, cells: list[Text]) -> Text:
        out = Text(no_wrap=True)
        out.append("|", style="dim")
        label.truncate(LABEL_W - 1)
        label.pad_right(LABEL_W - 1 - len(label.plain))
        out.append(" ")
        out.append_text(label)
        for cell in cells:
            out.append("|", style="dim")
            cell.truncate(COL_W - 2)
            cell.align("right", COL_W - 2)
            out.append(" ")
            out.append_text(cell)
            out.append(" ")
        out.append("|", style="dim")
        out.append("\n")
        return out

    def render(self) -> Text:
        p = self.player
        cols = self._column_cards()
        name = p.name + (f" ({p.difficulty})" if p.difficulty else "")
        width = 1 + LABEL_W + (1 + COL_W) * self.n_games
        out = Text(no_wrap=True)
        head_style = f"bold {ACCENT}" if self.is_turn else "bold"
        out.append("+= ", style="dim")
        out.append(name[: width - 6], style=head_style)
        out.append(" " + "=" * max(0, width - 4 - len(name)) + "+", style="dim")
        out.append("\n")

        if self.n_games > 1:
            header = []
            for i in range(self.n_games):
                style = f"bold {ACCENT}" if (i == self.active_col and not self.match_over) else "dim"
                header.append(Text(f"G{i + 1}", style=style))
            out.append_text(self._row(Text(""), header))
            out.append_text(self._sep())
        else:
            out.append_text(self._sep())

        def value_cell(card: Scorecard | None, cat: int, col: int) -> Text:
            if card is None:
                return Text("")
            val = card.boxes[cat]
            active = col == self.active_col and not self.match_over
            if val is not None:
                if val == 0:
                    return Text("x", style="bold" if active else "")
                return Text(str(val), style="bold")
            if active and not p.is_bot and cat in self.preview:
                shown = self.preview[cat]
                base = "x" if shown.rstrip("!") == "0" else shown
                style = "cyan"
                if cat == self.cursor_cat:
                    style = "reverse cyan"
                elif cat == self.hovered_cat:
                    style = "bold cyan underline"
                return Text(base, style=style)
            if active and not p.is_bot and self.preview:
                return Text("-", style="dim")  # joker rules forbid this box
            return Text(".", style="dim")

        def label_cell(cat: int) -> Text:
            interactive_now = self.interactive and self.preview and not self.match_over
            style = ""
            if cat == self.cursor_cat and interactive_now:
                style = f"bold {ACCENT}"
            elif cat == self.hovered_cat and interactive_now:
                style = "bold"
            marker = ">" if (cat == self.cursor_cat and interactive_now) else " "
            t = Text(no_wrap=True)
            t.append(marker, style=f"bold {ACCENT}" if marker == ">" else "")
            t.append(SHEET_LABELS[cat], style=style)
            return t

        for cat in range(6):
            out.append_text(
                self._row(label_cell(cat), [value_cell(c, cat, i) for i, c in enumerate(cols)])
            )
        out.append_text(self._sep())
        out.append_text(
            self._row(
                Text(" Sum", style="dim"),
                [
                    Text(str(c.upper_subtotal()) if c else "", style="dim")
                    for c in cols
                ],
            )
        )

        def bonus_cell(card: Scorecard | None, col: int) -> Text:
            if card is None:
                return Text("")
            if card.upper_bonus():
                return Text("35", style="green")
            need = UPPER_BONUS_THRESHOLD - card.upper_subtotal()
            uppers_open = any(card.boxes[c] is None for c in UPPER)
            if uppers_open and (col == self.active_col and not self.match_over):
                return Text(f"({need})", style="dim")
            return Text("-", style="dim")

        out.append_text(
            self._row(
                Text(" Bonus 63+", style="dim"),
                [bonus_cell(c, i) for i, c in enumerate(cols)],
            )
        )
        out.append_text(self._sep())
        for cat in range(6, N_CATEGORIES):
            out.append_text(
                self._row(label_cell(cat), [value_cell(c, cat, i) for i, c in enumerate(cols)])
            )
        out.append_text(
            self._row(
                Text(" Ybonus", style="dim"),
                [
                    Text(
                        str(c.yahtzee_bonus_count * 100) if c and c.yahtzee_bonus_count else ("-" if c else ""),
                        style="yellow" if c and c.yahtzee_bonus_count else "dim",
                    )
                    for c in cols
                ],
            )
        )
        out.append_text(self._sep())
        out.append_text(
            self._row(
                Text(" TOTAL", style="bold"),
                [
                    Text(str(c.total()) if c else "", style=f"bold {ACCENT}")
                    for c in cols
                ],
            )
        )
        if self.n_games > 1:
            running = 0
            match_cells = []
            for c in cols:
                if c is None:
                    match_cells.append(Text(""))
                else:
                    running += c.total()
                    match_cells.append(Text(str(running), style="bold"))
            out.append_text(self._sep())
            out.append_text(self._row(Text(" MATCH", style="bold"), match_cells))
        out.append_text(self._sep(heavy=True))
        return out

    # -- sizing ------------------------------------------------------------

    def get_content_width(self, container, viewport) -> int:
        lines = self.render().plain.splitlines()
        return max(len(line) for line in lines)

    def get_content_height(self, container, viewport, width) -> int:
        return len(self.render().plain.splitlines())

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
            self.cursor_cat = cats[(cats.index(self.cursor_cat) + step) % len(cats)]

    def action_pick(self) -> None:
        if self.cursor_cat is not None:
            self.post_message(self.CategoryPicked(self.cursor_cat))

    def _cat_at(self, y: int) -> int | None:
        # Event coordinates include the (blank or accent) border: -1. With a
        # single game there is no header row, shifting all lines up by 1.
        content_line = y - 1 + (1 if self.n_games == 1 else 0)
        return self.line_to_cat.get(content_line)

    def on_click(self, event: events.Click) -> None:
        if not self.interactive:
            return
        cat = self._cat_at(event.y)
        if cat is None or cat not in self.preview:
            return
        self.focus()
        self.cursor_cat = cat
        self.post_message(self.CategoryPicked(cat))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self.interactive:
            self.hovered_cat = self._cat_at(event.y)

    def on_leave(self) -> None:
        self.hovered_cat = None

    def watch_cursor_cat(self, _) -> None:
        self.refresh()

    def watch_hovered_cat(self, _) -> None:
        self.refresh()


# ---------------------------------------------------------------------------
# Arrow-navigable ASCII menu (no buttons, no widgets)
# ---------------------------------------------------------------------------


@dataclass
class MenuItem:
    id: str
    label: str
    kind: str = "action"                      # "action" | "choice"
    choices: list[tuple[str, object]] = field(default_factory=list)
    index: int = 0
    visible: bool = True

    @property
    def value(self):
        return self.choices[self.index][1] if self.choices else None

    @property
    def value_label(self) -> str:
        return self.choices[self.index][0] if self.choices else ""


class AsciiMenu(Widget, can_focus=True):
    """A Claude-terminal style menu: text lines, arrows, hover, click."""

    BINDINGS = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("left", "adjust(-1)", "Left", show=False),
        Binding("right", "adjust(1)", "Right", show=False),
        Binding("space,enter", "activate", "Select", show=False),
    ]

    selected: reactive[int] = reactive(0)
    hovered: reactive[int | None] = reactive(None)

    class Activated(Message):
        def __init__(self, item_id: str) -> None:
            self.item_id = item_id
            super().__init__()

    class Changed(Message):
        def __init__(self, item_id: str, value) -> None:
            self.item_id = item_id
            self.value = value
            super().__init__()

    class Highlighted(Message):
        def __init__(self, item_id: str) -> None:
            self.item_id = item_id
            super().__init__()

    def __init__(self, items: list[MenuItem], id: str | None = None) -> None:
        super().__init__(id=id)
        self.items = items

    def visible_items(self) -> list[MenuItem]:
        return [i for i in self.items if i.visible]

    def get_content_width(self, container, viewport) -> int:
        lines = self.render().plain.splitlines()
        return max((len(line) for line in lines), default=10) + 1

    def get_content_height(self, container, viewport, width) -> int:
        return len(self.visible_items())

    def item(self, item_id: str) -> MenuItem:
        return next(i for i in self.items if i.id == item_id)

    def set_visible(self, item_id: str, visible: bool) -> None:
        self.item(item_id).visible = visible
        vis = self.visible_items()
        self.selected = min(self.selected, len(vis) - 1)
        self.refresh()

    def current_item(self) -> MenuItem | None:
        vis = self.visible_items()
        return vis[self.selected] if vis else None

    def render(self) -> Text:
        out = Text(no_wrap=True)
        for idx, item in enumerate(self.visible_items()):
            selected = idx == self.selected and self.has_focus
            hovered = idx == self.hovered
            if selected:
                style = f"bold {ACCENT}"
            elif hovered:
                style = "bold"
            else:
                style = ""
            out.append("> " if selected else "  ", style=f"bold {ACCENT}" if selected else "")
            if item.kind == "choice":
                out.append(f"{item.label:<12}", style=style)
                out.append("< ", style="dim")
                out.append(item.value_label, style=style if selected or hovered else "")
                out.append(" >", style="dim")
            else:
                out.append(item.label, style=style)
            out.append("\n")
        return out

    def action_move(self, step: int) -> None:
        vis = self.visible_items()
        if vis:
            self.selected = (self.selected + step) % len(vis)

    def action_adjust(self, step: int) -> None:
        vis = self.visible_items()
        if not vis:
            return
        item = vis[self.selected]
        if item.kind == "choice" and item.choices:
            item.index = (item.index + step) % len(item.choices)
            self.refresh()
            self.post_message(self.Changed(item.id, item.value))

    def action_activate(self) -> None:
        vis = self.visible_items()
        if not vis:
            return
        item = vis[self.selected]
        if item.kind == "choice":
            self.action_adjust(1)
        else:
            self.post_message(self.Activated(item.id))

    def on_click(self, event: events.Click) -> None:
        vis = self.visible_items()
        if 0 <= event.y < len(vis):
            self.focus()
            self.selected = event.y
            self.action_activate()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        vis = self.visible_items()
        self.hovered = event.y if 0 <= event.y < len(vis) else None

    def on_leave(self) -> None:
        self.hovered = None

    def watch_selected(self, _) -> None:
        self.refresh()
        item = self.current_item()
        if item:
            self.post_message(self.Highlighted(item.id))

    def watch_hovered(self, _) -> None:
        self.refresh()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


# ---------------------------------------------------------------------------
# Full-screen text pages (help, stats, review): no dialogs
# ---------------------------------------------------------------------------


class TextPage(Screen):
    """A scrollable full-screen text page. Escape (or q) goes back."""

    BINDINGS = [
        Binding("escape,q,backspace", "go_back", "Back"),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        yield Static(f" {self.title_text}", id="page-title", markup=True)
        with VerticalScroll(id="page-scroll"):
            yield Static(self.body, id="page-body", markup=True)
        yield Static(" up/down scroll   esc back", id="page-footer")

    def on_mount(self) -> None:
        self.query_one("#page-scroll", VerticalScroll).focus()

    def action_go_back(self) -> None:
        self.app.pop_screen()


HELP_TEXT = f"""[b]YAHTZEE v{__version__}[/b]

[b u]Keys[/b u]
  [b]r / space[/b]      roll
  [b]1 to 5[/b]         hold / release a die (or click it)
  [b]left/right[/b]     move the die cursor
  [b]up/down[/b]        move over your score card
  [b]enter / space[/b]  hold the selected die, or fill the selected box
  [b]tab[/b]            switch focus: dice, your card, command bar
  [b]h[/b]              hint (from the optimal solver)
  [b]shift+tab[/b]      switch mode: NORMAL, HINTS, COACH, AUTO
  [b]/[/b]              open the command bar
  [b]?[/b] or [b]F1[/b]        help
  [b]n[/b]              new match   [b]v[/b] review   [b]m[/b]/[b]esc[/b] menu   [b]q[/b] quit
                 (leaving always saves; continue from the menu)

[b u]Commands[/b u]  (type / followed by the command)
  [b]/help[/b] or [b]/?[/b]     this help
  [b]/hint[/b]           one-off hint for the current situation
  [b]/hints on|off[/b]   hint mode (advice after every roll)
  [b]/coach on|off[/b]   coach mode (EV verdict after every decision)
  [b]/auto[/b]           auto mode (the solver plays your turns)
  [b]/mode X[/b]         normal, hints, coach, or auto
  [b]/win on|off[/b]     endgame win-probability play in AUTO
  [b]/review[/b]         your decisions so far, worst first
  [b]/new [n] [level] [rules][/b]  new match, e.g. /new 3 optimal simple
  [b]/rules[/b]          show the active rule variant
  [b]/speed X[/b]        bot speed: slow, normal, fast, instant
  [b]/stats[/b]          your statistics
  [b]/update[/b]         check for updates now and install
  [b]/restart[/b]        restart the app
  [b]/version[/b]        show the version
  [b]/menu[/b]           back to the main menu
  [b]/quit[/b]           quit

[b u]Modes[/b u]  (shift+tab cycles)
  [b]NORMAL[/b]  regular play
  [b]HINTS[/b]   BEFORE you decide, the optimal solver shows the best keep
           or box with expected values, so you can follow or ignore it
  [b]COACH[/b]   you decide first; AFTER each decision the solver grades it
           (EV lost vs optimal), and the match ends with an accuracy
           score and a review of your worst mistakes
  [b]AUTO[/b]    the solver plays your turns automatically

[b u]The match[/b u]
A match is 1 to 6 games; every game fills one column on your card, like
the classic paper pad. The MATCH row keeps the running total; the highest
match total wins.

[b u]WIN mode[/b u]  (/win, the video's asterisk)
Maximizing points is not maximizing win chance. With WIN on (default),
AUTO plays the endgame for win probability: exact win-chance calculation
in the final round, variance control just before. Hints always show the
standings-aware advice near the end.

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


def review_text(tracker: CoachTracker, title: str) -> str:
    lines = [
        f"[b]{title}[/b]",
        "",
        f"Accuracy: [b]{tracker.accuracy()}%[/b]   "
        f"(total EV given away: {tracker.total_loss:.1f} points, "
        f"{len(tracker.decisions)} decisions)",
        "",
    ]
    if not tracker.decisions:
        lines.append("No graded decisions yet. Play a turn first.")
        return "\n".join(lines)
    lines.append("[b u]Worst decisions[/b u]")
    for d in tracker.worst(8):
        if d.loss < 0.05:
            continue
        lines.append(f"  game {d.game} round {d.round:>2}  ({d.dice})  you: {d.chosen}")
        lines.append(f"             best: {d.best}  [red]-{d.loss:.1f} EV[/red]")
    perfect = sum(1 for d in tracker.decisions if d.loss < 0.05)
    lines.append("")
    lines.append(f"Perfect decisions: {perfect}/{len(tracker.decisions)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU_INFO = {
    "continue": "Reopen your last game right where it stopped.",
    "view": "Look back at the final cards of your last match.",
    "new": "Start a new match with the settings below.",
    "bots": "Number of computer opponents at the table.",
    "games": "Games per match; every game fills one column on your card.",
    "hints": "Solver advice after every roll (switch anytime with shift+tab).",
    "help": "All keys, commands, modes, and rules.",
    "stats": "Your match history and averages.",
    "quit": "See you next time.",
}


class MenuScreen(Screen):
    BINDINGS = [
        Binding("question_mark,f1", "help", "Help"),
        Binding("q,escape", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        settings = load_settings()
        diff = settings.get("difficulty", "medium")
        diff_idx = DIFFICULTIES.index(diff) if diff in DIFFICULTIES else 1
        rules = settings.get("ruleset", "official")
        rules_idx = RULESETS.index(rules) if rules in RULESETS else 0
        n_bots = int(settings.get("n_bots", 2))
        n_games = int(settings.get("n_games", 3))
        items = [
            MenuItem("continue", "Continue last game"),
            MenuItem("new", "New game"),
            MenuItem(
                "bots", "Opponents", "choice",
                [(f"{n} bot{'s' if n > 1 else ''}", n) for n in range(1, 5)],
                index=max(0, min(3, n_bots - 1)),
            ),
            MenuItem(
                "difficulty", "Difficulty", "choice",
                [(DIFFICULTY_LABELS[d], d) for d in DIFFICULTIES],
                index=diff_idx,
            ),
            MenuItem(
                "rules", "Game mode", "choice",
                [(RULESET_LABELS[r], r) for r in RULESETS],
                index=rules_idx,
            ),
            MenuItem(
                "games", "Games", "choice",
                [(str(n), n) for n in range(1, 7)],
                index=max(0, min(5, n_games - 1)),
            ),
            MenuItem(
                "hints", "Hints", "choice",
                [("off", "normal"), ("on", "hints")],
                index=1 if settings.get("mode") == "hints" else 0,
            ),
            MenuItem("help", "Help"),
            MenuItem("stats", "Statistics"),
            MenuItem("quit", "Quit"),
        ]
        with Center(id="menu-center"):
            with Vertical(id="menu-box"):
                yield Static(LOGO, id="menu-logo")
                yield Static(
                    dice_art([random.randint(1, 6) for _ in range(5)]),
                    id="menu-dice",
                )
                yield Static(f"v{__version__}", id="menu-version")
                yield AsciiMenu(items, id="menu")
                yield Static("", id="menu-info", markup=True)
                yield Static(" ↑↓ select  ←→ change  enter confirm", id="menu-footer")

    def on_mount(self) -> None:
        self._refresh_continue()
        self.query_one(AsciiMenu).focus()
        self._update_info()

    def on_screen_resume(self) -> None:
        self._refresh_continue()
        self.query_one("#menu-dice", Static).update(
            dice_art([random.randint(1, 6) for _ in range(5)])
        )

    def _refresh_continue(self) -> None:
        menu = self.query_one(AsciiMenu)
        snapshot = load_game_snapshot()
        item = menu.item("continue")
        item.label = "View last game" if (snapshot or {}).get("finished") else "Continue last game"
        menu.set_visible("continue", snapshot is not None)

    def _update_info(self) -> None:
        menu = self.query_one(AsciiMenu)
        item = menu.current_item()
        if item is None:
            return
        if item.id == "difficulty":
            info = DIFFICULTY_INFO[str(item.value)]
        elif item.id == "rules":
            info = RULESET_INFO[str(item.value)]
        elif item.id == "continue":
            snapshot = load_game_snapshot()
            info = MENU_INFO["view"] if (snapshot or {}).get("finished") else MENU_INFO["continue"]
        else:
            info = MENU_INFO.get(item.id, "")
        self.query_one("#menu-info", Static).update(f"[dim]{info}[/dim]")

    @on(AsciiMenu.Highlighted)
    def _highlighted(self, _: AsciiMenu.Highlighted) -> None:
        self._update_info()

    @on(AsciiMenu.Changed)
    def _changed(self, event: AsciiMenu.Changed) -> None:
        settings = load_settings()
        if event.item_id == "bots":
            settings["n_bots"] = event.value
        elif event.item_id == "difficulty":
            settings["difficulty"] = event.value
        elif event.item_id == "rules":
            settings["ruleset"] = event.value
        elif event.item_id == "games":
            settings["n_games"] = event.value
        elif event.item_id == "hints":
            settings["mode"] = event.value
        save_settings(settings)
        self._update_info()

    @on(AsciiMenu.Activated)
    def _activated(self, event: AsciiMenu.Activated) -> None:
        menu = self.query_one(AsciiMenu)
        app = self.app
        assert isinstance(app, YahtzeeApp)
        if event.item_id == "continue":
            snapshot = load_game_snapshot()
            if snapshot:
                config = GameConfig(
                    difficulties=snapshot["config"]["difficulties"],
                    mode=snapshot["config"].get("mode", "normal"),
                    rules=snapshot["config"].get("rules", "official"),
                    n_games=int(snapshot.get("n_games", 1)),
                )
                app.start_game(config, snapshot=snapshot)
        elif event.item_id == "new":
            config = GameConfig(
                difficulties=[str(menu.item("difficulty").value)]
                * int(menu.item("bots").value),
                mode=str(menu.item("hints").value),
                rules=str(menu.item("rules").value),
                n_games=int(menu.item("games").value),
            )
            app.start_game(config)
        elif event.item_id == "help":
            app.push_screen(TextPage("Help", HELP_TEXT))
        elif event.item_id == "stats":
            app.push_screen(TextPage("Statistics", "\n".join(stats_summary())))
        elif event.item_id == "quit":
            app.exit()

    def action_help(self) -> None:
        self.app.push_screen(TextPage("Help", HELP_TEXT))

    def action_quit_app(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# The game itself
# ---------------------------------------------------------------------------

FOOTER_PLAYING = (
    " r roll   1-5 hold   arrows navigate   enter select   tab focus   "
    "shift+tab mode   h hint   / cmd   ? help   esc menu"
)
FOOTER_GAME_OVER = " n new match   v review   m menu   q quit"


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
        Binding("n", "new_game", "New match", show=False),
        Binding("v", "review", "Review", show=False),
        Binding("m", "to_menu", "Menu", show=False),
        Binding("escape", "back", "Menu", show=False),
        Binding("q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, config: GameConfig, snapshot: dict | None = None) -> None:
        super().__init__()
        self.config = config
        self.mode = config.mode
        self.settings = load_settings()
        self.win_mode = bool(self.settings.get("win_mode", True))
        self.n_games = max(1, min(6, config.n_games))
        self.game_no = 1
        self._view_only = False
        if snapshot:
            self._restore(snapshot)
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
        self._last_logged = (0, 0)

    # -- resume ------------------------------------------------------------

    def _restore(self, snap: dict) -> None:
        players = []
        for p in snap["players"]:
            card = Scorecard(self.config.rules)
            card.boxes = [b if b is None else int(b) for b in p["boxes"]]
            card.yahtzee_bonus_count = int(p.get("ybonus", 0))
            player = Player(
                p["name"], is_bot=p["bot"], difficulty=p.get("difficulty"), card=card
            )
            for h in p.get("history", []):
                past = Scorecard(self.config.rules)
                past.boxes = [b if b is None else int(b) for b in h["boxes"]]
                past.yahtzee_bonus_count = int(h.get("ybonus", 0))
                player.history.append(past)
            players.append(player)
        game = Game(players)
        game.round = int(snap["round"])
        game.current_idx = int(snap["current_idx"])
        turn = snap.get("turn") or {}
        game.turn.dice = [int(d) for d in turn.get("dice", [1] * 5)]
        game.turn.held = [bool(h) for h in turn.get("held", [False] * 5)]
        game.turn.rolls_used = int(turn.get("rolls_used", 0))
        self.players = players
        self.game = game
        self.coach = CoachTracker(
            decisions=[Decision(**d) for d in snap.get("coach", [])]
        )
        self.game_no = int(snap.get("game_no", 1))
        self.n_games = int(snap.get("n_games", self.n_games))
        if snap.get("finished"):
            self.game.finished = True
            self._view_only = True

    def _snapshot(self, finished: bool = False) -> dict:
        turn = self.game.turn
        return {
            "version": __version__,
            "config": {
                "difficulties": self.config.difficulties,
                "mode": self.mode,
                "rules": self.config.rules,
            },
            "n_games": self.n_games,
            "game_no": self.game_no,
            "finished": finished,
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
                    "history": [
                        {"boxes": h.boxes, "ybonus": h.yahtzee_bonus_count}
                        for h in p.history
                    ],
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
                            yield RollAction(id="roll-action")
                            yield Static("", id="turn-note", markup=True)
                    yield RichLog(id="log", markup=True, wrap=True, auto_scroll=True)
                    yield Input(placeholder="/help for commands", id="command")
                with HorizontalScroll(id="cards-row"):
                    for i, p in enumerate(self.players):
                        yield PlayerCard(p, self.n_games, interactive=(i == 0))
            yield Static(FOOTER_PLAYING, id="footer-keys")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        names = ", ".join(f"{p.name} ({p.difficulty})" for p in self.players if p.is_bot)
        if self._view_only:
            log.write("[b]Your last match.[/b] Press n for a new one, m for the menu.")
        else:
            log.write(f"[b]New match![/b] Opponents: {names}.")
            log.write(
                f"Mode [b]{RULESET_LABELS[self.config.rules]}[/b] · "
                f"{self.n_games} game{'s' if self.n_games > 1 else ''} per match"
            )
            log.write("Type [b]/help[/b] or press [b]?[/b] for all keys and commands.")
            if self.mode == "hints":
                log.write("[yellow]Hint mode is on.[/yellow]")
            if self.mode == "coach":
                log.write("[yellow]Coach mode is on: every decision gets a verdict.[/yellow]")
        self.query_one(DiceRow).focus()
        self.refresh_all()
        if self._view_only:
            self._recorded = True
            self._final_accuracy = self.coach.accuracy() if self.coach.decisions else None
            self.finish_match(record=False)
        else:
            self.call_after_refresh(self.start_turn)

    # -- helpers -----------------------------------------------------------

    @property
    def human(self) -> Player:
        return self.players[0]

    def human_card_widget(self) -> PlayerCard:
        return self.query(PlayerCard).first()

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

    def _win_context(self, enabled: bool = True) -> winmode.WinContext:
        return winmode.build_context(
            self.human,
            [p for p in self.players if p.is_bot],
            self.oracle,
            self.rounds_left_for(self.human),
            enabled,
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
        roll = self.query_one(RollAction)
        note = self.query_one("#turn-note", Static)
        must_roll = self.human_may_act() and turn.rolls_used == 0
        must_fill = self.human_may_act() and turn.rolls_left == 0
        row.set_class(must_roll, "attention")
        self.human_card_widget().set_class(must_fill, "attention")
        if self.game.finished:
            roll.enabled = False
            note.update("[b]Match over[/b]")
            return
        roll.enabled = self.human_may_act() and turn.can_roll()
        roll.rolls_left = turn.rolls_left
        p = self.game.current
        lines = []
        if not p.is_bot and self.mode == "auto":
            lines.append("[cyan]AUTO plays for you[/cyan]")
        elif p.is_bot:
            lines.append(f"[dim]{p.name} is thinking...[/dim]")
        elif turn.rolls_used == 0:
            lines.append(f"[b {ACCENT}]Your turn![/b {ACCENT}] press r")
        elif turn.rolls_left == 0:
            lines.append("Fill a box on your card")
        else:
            lines.append("Hold dice, roll again,\nor score now")
        if self.is_human_turn():
            card = self.human.card
            need = UPPER_BONUS_THRESHOLD - card.upper_subtotal()
            if need > 0 and any(card.boxes[c] is None for c in UPPER):
                lines.append(f"[dim]Bonus 63+: need {need} more[/dim]")
        note.update("\n".join(lines))

    def refresh_status(self) -> None:
        if not self.is_mounted:
            return
        status = self.query_one("#statusbar", Static)
        game_part = (
            f"game [b]{self.game_no}/{self.n_games}[/b]  ·  " if self.n_games > 1 else ""
        )
        if self.game.finished:
            ranked = sorted(self.players, key=lambda p: p.match_total(), reverse=True)
            winner = ranked[0]
            who = "you" if not winner.is_bot else winner.name
            status.update(
                f" [b]MATCH OVER[/b]  ·  {who} won with [b]{winner.match_total()}[/b] points"
            )
            return
        p = self.game.current
        who = f"[b {ACCENT}]YOUR TURN[/b {ACCENT}]" if not p.is_bot else f"turn: [b]{p.name}[/b]"
        win = "on" if self.win_mode else "off"
        status.update(
            f" YAHTZEE [dim]v{__version__}[/dim]  ·  {game_part}"
            f"round [b]{self.game.round}/13[/b]  ·  {who}  ·  "
            f"[b]{MODE_LABELS[self.mode]}[/b] [dim](shift+tab)[/dim]  ·  "
            f"win {win}  ·  [dim]{RULESET_LABELS[self.config.rules]}[/dim]"
        )

    def refresh_cards(self) -> None:
        if not self.is_mounted:
            return
        turn = self.game.turn
        preview: dict[int, str] = {}
        if self.is_human_turn() and turn.rolls_used > 0:
            for opt in self.human.card.options(turn.counts()):
                marker = "!" if opt.forced else ""
                preview[opt.category] = f"{opt.points}{marker}"
        for widget in self.query(PlayerCard):
            is_turn = not self.game.finished and widget.player is self.game.current
            widget.set_state(
                is_turn,
                preview if widget.player is self.human else {},
                match_over=self.game.finished,
            )

    # -- turn flow ---------------------------------------------------------

    def start_turn(self) -> None:
        if not self.is_mounted or self._view_only:
            return
        if self.game.finished:
            self.next_game_or_finish()
            return
        self.checkpoint()
        p = self.game.current
        if self.game.current_idx == 0 and self._last_logged != (self.game_no, self.game.round):
            self._last_logged = (self.game_no, self.game.round)
            game_part = f"Game {self.game_no} · " if self.n_games > 1 else ""
            self.log_write(f"[dim]── {game_part}Round {self.game.round}/13 " + "─" * 18 + "[/dim]")
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
            self.query_one(DiceRow).focus()

    async def _animate_roll(self) -> None:
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
                            self.log_write(f"[cyan]{note}[/cyan]")
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
                game_no=self.game_no,
            )
            if self.mode == "coach":
                self.log_write(f"[yellow]{verdict_line(decision)}[/yellow]")
        player.card.apply(option, counts)
        name = prefix or player.name
        name_style = ACCENT if player is self.human else "bold"
        extra = " [yellow]+100 bonus![/yellow]" if option.extra_bonus else ""
        joker = " [dim](joker)[/dim]" if option.is_joker else ""
        dice_str = " ".join(str(d) for d in sorted(turn.dice))
        pts = f"[b]{option.points}[/b]" if option.points else "[dim]x[/dim]"
        self.log_write(
            f"[{name_style}]{name:<6}[/{name_style}] [dim]({dice_str})[/dim] "
            f"{CATEGORY_NAMES[option.category]}{joker} → {pts}{extra}"
        )
        self.game.advance()
        self.refresh_all()
        self.set_timer(0.05, self.start_turn)

    def next_game_or_finish(self) -> None:
        """One game finished: next column, or wrap up the match."""
        if self.game_no < self.n_games:
            standings = sorted(self.players, key=lambda p: p.match_total(), reverse=True)
            line = "  ·  ".join(f"{p.name} {p.match_total()}" for p in standings)
            self.log_write(f"[b]Game {self.game_no} done.[/b] Standings: {line}")
            for p in self.players:
                p.history.append(p.card)
                p.card = Scorecard(self.config.rules)
            self.game_no += 1
            self.game = Game(self.players)
            self.log_write(f"[b]Game {self.game_no} of {self.n_games}![/b]")
            self.checkpoint()
            self.refresh_all()
            self.set_timer(1.0, self.start_turn)
        else:
            self.finish_match()

    def finish_match(self, record: bool = True) -> None:
        """Match over, inline: no popup. The footer and log take over."""
        if record and not self._recorded:
            self._recorded = True
            save_game_snapshot(self._snapshot(finished=True))
            self._final_accuracy = (
                self.coach.accuracy() if self.coach.decisions else None
            )
            ranked = sorted(self.players, key=lambda p: p.match_total(), reverse=True)
            record_game(
                [(p.name, p.is_bot, p.difficulty, p.match_total()) for p in ranked],
                rules=self.config.rules,
                accuracy=self._final_accuracy,
            )
        ranked = sorted(self.players, key=lambda p: p.match_total(), reverse=True)
        winner = ranked[0]
        bar = "=" * 44
        self.log_write(f"[dim]{bar}[/dim]")
        if winner.is_bot:
            self.log_write(f"[b]  MATCH OVER  ·  {winner.name} wins[/b]")
        else:
            self.log_write("[b green]  MATCH OVER  ·  You win![/b green]")
        for i, p in enumerate(ranked, start=1):
            diff = f" ({p.difficulty})" if p.difficulty else ""
            self.log_write(f"  {i}. {p.name}{diff}: [b]{p.match_total()}[/b] points")
        if self._final_accuracy is not None:
            self.log_write(
                f"  Your accuracy: [b]{self._final_accuracy}%[/b] "
                f"(press [b]v[/b] for the review)"
            )
        self.log_write(f"[dim]{bar}[/dim]")
        self.query_one("#footer-keys", Static).update(FOOTER_GAME_OVER)
        self.refresh_all()

    # -- human actions -----------------------------------------------------

    def action_roll(self) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if not turn.can_roll():
            if turn.rolls_left == 0:
                self.log_write("[dim]No rolls left; fill a box on your card.[/dim]")
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
                game_no=self.game_no,
            )
            if self.mode == "coach":
                self.log_write(f"[yellow]{verdict_line(decision)}[/yellow]")
        self.run_worker(self._human_roll(), exclusive=True, group="roll")

    async def _human_roll(self) -> None:
        await self._do_roll()
        turn = self.game.turn
        if turn.rolls_left == 0:
            self.log_write(
                f"Roll 3: ({' '.join(map(str, sorted(turn.dice)))}). Fill a box."
            )
            self.human_card_widget().focus()
        if self.mode == "hints":
            self._show_hint()

    def action_hold(self, idx: int) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.log_write("[dim]Roll first (r).[/dim]")
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

    @on(RollAction.Rolled)
    def _roll_clicked(self) -> None:
        self.action_roll()

    @on(PlayerCard.CategoryPicked)
    def _category_picked(self, event: PlayerCard.CategoryPicked) -> None:
        if not self.human_may_act():
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.log_write("[dim]Roll first (r).[/dim]")
            return
        try:
            option = self.human.card.score_option(event.category, turn.counts())
        except ValueError as exc:
            self.log_write(f"[dim]{exc}[/dim]")
            return
        self._score(self.human, option, prefix="You")

    def action_focus_dice(self) -> None:
        self.query_one(DiceRow).focus()

    def action_focus_card(self) -> None:
        self.human_card_widget().focus()

    def _show_hint(self) -> None:
        if not self.is_human_turn():
            self.log_write("[dim]Hints only work during your turn.[/dim]")
            return
        turn = self.game.turn
        if turn.rolls_used == 0:
            self.log_write("[yellow]Hint: roll first.[/yellow]")
            return
        for line in hint_for(self.oracle, self.human.card, turn.counts(), turn.rolls_left):
            self.log_write(f"[yellow]* {line}[/yellow]")
        # Standings-aware advice near the end of the game (the video's
        # asterisk): always shown, AUTO follows it only with win mode on.
        if turn.rolls_left > 0:
            ctx = self._win_context(enabled=True)
            if ctx.active:
                keep, note = winmode.choose_keep(
                    self.oracle, self.human.card, turn.counts(), turn.rolls_left, ctx
                )
                if note:
                    self.log_write(f"[cyan]* {note}[/cyan]")

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
        self.app.push_screen(TextPage("Help", HELP_TEXT))

    def action_review(self) -> None:
        title = "Match review" if self.game.finished else "Review so far"
        self.app.push_screen(TextPage("Review", review_text(self.coach, title)))

    def action_new_game(self) -> None:
        clear_saved_game()
        app = self.app
        assert isinstance(app, YahtzeeApp)
        app.start_game(self.config, replace=True)

    def action_to_menu(self) -> None:
        self.checkpoint()
        if not self.game.finished:
            self.log_write("Game saved.")
        self.app.pop_screen()

    def action_back(self) -> None:
        inp = self.query_one("#command", Input)
        if inp.has_focus:
            inp.value = ""
            self.query_one(DiceRow).focus()
            return
        self.action_to_menu()

    def action_quit_app(self) -> None:
        self.checkpoint()
        self.app.exit()

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
            self.action_help()
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
                f"WIN mode [b]{state}[/b]: endgame play in AUTO now "
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
            self.action_to_menu()
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
        config = GameConfig(
            difficulties=diffs, mode=self.mode, rules=rules, n_games=self.n_games
        )
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
    Screen { background: ansi_default; color: ansi_default; }

    /* Menu */
    #menu-center { align: center middle; height: 1fr; }
    #menu-box { width: auto; height: auto; max-height: 100%; overflow-y: auto; }
    #menu-logo { width: auto; }
    #menu-dice { width: auto; margin-top: 1; color: ansi_bright_black; }
    #menu-version { color: ansi_bright_black; margin-bottom: 1; }
    AsciiMenu { width: auto; height: auto; padding-left: 4; }
    #menu-info { height: 2; margin-top: 1; padding-left: 4; }
    #menu-footer { color: ansi_bright_black; }

    /* Game */
    #game-root { height: 1fr; }
    #statusbar { height: 1; }
    #game-columns { height: 1fr; }
    #left-column { width: 1fr; min-width: 90; padding: 0 1; }
    #dice-area { height: 10; }
    DiceRow { width: 62; height: 10; layout: horizontal; border: blank; }
    DiceRow.attention { border: ascii ansi_magenta; }
    .die { width: 12; height: 7; background: ansi_default; }
    #roll-column { width: 26; padding-top: 1; }
    #roll-action { height: 1; }
    #turn-note { margin-top: 1; }
    #log {
        height: 1fr; margin-top: 1; background: ansi_default;
        scrollbar-size-vertical: 1;
        scrollbar-background: ansi_default; scrollbar-color: ansi_bright_black;
        scrollbar-background-hover: ansi_default; scrollbar-color-hover: ansi_white;
        scrollbar-background-active: ansi_default; scrollbar-color-active: ansi_white;
    }
    #command { border: none; height: 1; padding: 0; background: ansi_default; }
    #cards-row {
        width: auto; padding: 0;
        scrollbar-size-horizontal: 1;
        scrollbar-background: ansi_default; scrollbar-color: ansi_bright_black;
    }
    PlayerCard { width: auto; height: auto; margin-right: 1; border: blank; }
    PlayerCard.attention { border: ascii ansi_magenta; }
    #footer-keys { height: 1; color: ansi_bright_black; }

    /* Text pages */
    #page-title { height: 1; text-style: bold; }
    #page-scroll {
        height: 1fr; scrollbar-size-vertical: 1;
        scrollbar-background: ansi_default; scrollbar-color: ansi_bright_black;
        scrollbar-background-hover: ansi_default; scrollbar-color-hover: ansi_white;
        scrollbar-background-active: ansi_default; scrollbar-color-active: ansi_white;
    }
    #page-body { padding: 1 2; }
    #page-footer { height: 1; color: ansi_bright_black; }
    """

    def __init__(
        self,
        no_update: bool = False,
        initial: dict | None = None,
        resume: bool = False,
    ) -> None:
        super().__init__(ansi_color=True)
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
                n_games=int(self.initial.get("n_games", 1)),
                mode=load_settings().get("mode", "normal"),
            )
            self.start_game(config)
        elif self.resume:
            snapshot = load_game_snapshot()
            if snapshot and not snapshot.get("finished"):
                config = GameConfig(
                    difficulties=snapshot["config"]["difficulties"],
                    mode=snapshot["config"].get("mode", "normal"),
                    rules=snapshot["config"].get("rules", "official"),
                    n_games=int(snapshot.get("n_games", 1)),
                )
                self.start_game(config, snapshot=snapshot)
        self._whats_new()
        if not self.no_update:
            self._update_check()

    def start_game(
        self, config: GameConfig, replace: bool = False, snapshot: dict | None = None
    ) -> None:
        if replace:
            self.pop_screen()
        self.push_screen(GameScreen(config, snapshot=snapshot))

    def request_restart(self, resume: bool = False) -> None:
        """Exit and relaunch into the (possibly just-updated) code."""
        self._restart_args = ["--no-update"] + (["--resume"] if resume else [])
        self.exit()

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
        """A background update landed mid-session: apply when possible."""
        in_game = any(isinstance(s, GameScreen) for s in self.screen_stack)
        if not in_game:
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
    app = YahtzeeApp(no_update=no_update, initial=initial, resume=resume)
    app.run()
    if app._restart_args is not None:
        # Terminal state is restored at this point; swap in the new code.
        os.execv(
            sys.executable,
            [sys.executable, "-m", "yahtzee_app", *app._restart_args],
        )
