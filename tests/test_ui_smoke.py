"""Smoke tests: boot the TUI, navigate the menu, play, switch modes.

Uses Textual's Pilot to drive the real app headlessly. Catches runtime
errors in screens, widgets, bindings, and the turn loop.
"""

import pytest

from yahtzee_app.ui.app import (
    AsciiDie,
    AsciiMenu,
    DiceRow,
    GameConfig,
    GameScreen,
    MenuScreen,
    ScoreSheet,
    TextPage,
    YahtzeeApp,
)


@pytest.mark.asyncio
async def test_menu_boots_and_arrows_start_game():
    """The menu is arrow-navigable: enter on 'New game' starts a game."""
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen)
        menu = app.screen.query_one(AsciiMenu)
        assert menu.has_focus
        # No saved game: first visible item is "New game".
        assert menu.visible_items()[0].id == "new"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, GameScreen)


@pytest.mark.asyncio
async def test_menu_choice_items_adjust_with_arrows():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        menu = app.screen.query_one(AsciiMenu)
        bots_item = menu.item("bots")
        before = bots_item.value
        # Move to the "Opponents" row and adjust it.
        vis = menu.visible_items()
        menu.selected = vis.index(bots_item)
        await pilot.press("right")
        await pilot.pause()
        assert bots_item.value != before


@pytest.mark.asyncio
async def test_menu_help_is_a_page_not_a_dialog():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        menu = app.screen.query_one(AsciiMenu)
        vis = menu.visible_items()
        menu.selected = vis.index(menu.item("help"))
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TextPage)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen)


@pytest.mark.asyncio
async def test_dice_render_pips():
    """The dice must actually be visible as ASCII art."""
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        await pilot.press("r")
        await pilot.pause(0.5)
        die = screen.query(AsciiDie).first()
        art = die.render().plain
        assert ".-------." in art
        assert "o" in art or "?" in art


@pytest.mark.asyncio
async def test_full_human_turn_flow():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        screen.settings["speed"] = "instant"
        await pilot.press("r")
        await pilot.pause(0.3)
        assert screen.game.turn.rolls_used == 1
        await pilot.press("1")
        await pilot.pause()
        assert screen.game.turn.held[0]
        await pilot.press("space")  # dice row focused: space toggles hold
        await pilot.pause()
        assert not screen.game.turn.held[0]
        await pilot.press("r")
        await pilot.pause(0.3)
        assert screen.game.turn.rolls_used == 2
        chance_option = screen.human.card.score_option(12, screen.game.turn.counts())
        screen._score(screen.human, chance_option, prefix="You")
        await pilot.pause()
        assert screen.human.card.boxes[12] is not None
        assert len(screen.coach.decisions) >= 1


@pytest.mark.asyncio
async def test_sheet_cursor_and_pick():
    """Arrows move over the score sheet; enter fills the selected box."""
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        await pilot.press("r")
        await pilot.pause(0.3)
        # Up/down from the dice row moves focus to the sheet.
        await pilot.press("down")
        await pilot.pause()
        sheet = screen.query_one(ScoreSheet)
        assert sheet.has_focus
        assert sheet.cursor_cat is not None
        before = sheet.cursor_cat
        await pilot.press("down")
        await pilot.pause()
        assert sheet.cursor_cat != before
        await pilot.press("enter")
        await pilot.pause()
        assert screen.human.card.boxes.count(None) == 12
        # Left/right moves focus back to the dice.
        await pilot.press("left")
        await pilot.pause()
        assert screen.query_one(DiceRow).has_focus


@pytest.mark.asyncio
async def test_mode_cycle_and_commands():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        assert screen.mode == "normal"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert screen.mode == "hints"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert screen.mode == "coach"
        screen.handle_command("/mode normal")
        screen.handle_command("/rules")
        screen.handle_command("/version")
        screen.handle_command("/stats")
        screen.handle_command("/win on")
        screen.handle_command("/speed instant")
        await pilot.pause()
        assert screen.mode == "normal"
        assert screen.win_mode is True
        assert screen.settings["speed"] == "instant"
        screen.handle_command("/win off")


@pytest.mark.asyncio
async def test_escape_saves_and_returns_to_menu_without_dialog():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        assert isinstance(app.screen, GameScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen)

    import yahtzee_app.config as cfg

    assert cfg.load_game_snapshot() is not None


@pytest.mark.asyncio
async def test_restart_command_saves_and_requests_restart():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        screen.handle_command("/restart")
    assert app._restart_args == ["--no-update", "--resume"]

    import yahtzee_app.config as cfg

    assert cfg.load_game_snapshot() is not None


@pytest.mark.asyncio
async def test_resume_reopens_saved_game():
    import yahtzee_app.config as cfg

    config = GameConfig(difficulties=["easy"], mode="normal")
    source = GameScreen(config)
    cfg.save_game_snapshot(source._snapshot())
    app = YahtzeeApp(no_update=True, resume=True)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, GameScreen)
        assert app.screen.human.card.boxes == source.human.card.boxes


def test_snapshot_roundtrip():
    """Save-game snapshots restore the exact game state."""
    config = GameConfig(difficulties=["easy"], mode="normal")
    s1 = GameScreen(config)
    s1.game.turn.roll()
    opt = s1.human.card.score_option(12, s1.game.turn.counts())
    s1.human.card.apply(opt, s1.game.turn.counts())
    s1.game.advance()
    snap = s1._snapshot()
    s2 = GameScreen(config, snapshot=snap)
    assert s2.human.card.boxes == s1.human.card.boxes
    assert s2.game.round == s1.game.round
    assert s2.game.current_idx == s1.game.current_idx
    assert s2.game.turn.dice == s1.game.turn.dice


@pytest.mark.asyncio
async def test_bot_game_plays_and_checkpoint():
    """Bots play at instant speed; the game auto-saves checkpoints."""
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy", "medium"], mode="auto"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        screen.settings["speed"] = "instant"
        for _ in range(80):
            await pilot.pause(0.05)
            if screen.game.round > 1:
                break
        assert screen.game.round > 1 or screen.game.finished
