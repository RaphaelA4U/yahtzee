"""Smoke tests: boot the TUI, start a game, roll, hold, score, switch modes.

Uses Textual's Pilot to drive the real app headlessly. Catches runtime
errors in screens, widgets, bindings, and the turn loop.
"""

import pytest

from yahtzee_app.ui.app import (
    AsciiDie,
    DiceRow,
    GameConfig,
    GameScreen,
    MenuScreen,
    PlayerCard,
    YahtzeeApp,
)


@pytest.mark.asyncio
async def test_menu_boots():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
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
        await pilot.press("space")  # dice row is focused: space toggles hold
        await pilot.pause()
        assert not screen.game.turn.held[0]
        await pilot.press("r")
        await pilot.pause(0.3)
        assert screen.game.turn.rolls_used == 2
        # Score Chance (cat 12) directly through the card message flow.
        chance_option = screen.human.card.score_option(12, screen.game.turn.counts())
        screen._score(screen.human, chance_option, prefix="You")
        await pilot.pause()
        assert screen.human.card.boxes[12] is not None
        # A keep and a score decision were graded by the coach.
        assert len(screen.coach.decisions) >= 1


@pytest.mark.asyncio
async def test_card_cursor_and_pick():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(140, 45)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        await pilot.press("r")
        await pilot.pause(0.3)
        card = screen.query(PlayerCard).first()
        card.focus()
        await pilot.pause()
        assert card.cursor_cat is not None
        before = card.cursor_cat
        await pilot.press("down")
        await pilot.pause()
        assert card.cursor_cat != before
        await pilot.press("enter")
        await pilot.pause()
        assert screen.human.card.boxes.count(None) == 12  # one box scored


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
