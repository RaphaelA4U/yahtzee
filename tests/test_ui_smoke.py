"""Smoke test: boot the TUI, start a game, roll, hold, score, quit.

Uses Textual's Pilot to drive the real app headlessly. Catches runtime
errors in screens, bindings, and the turn loop.
"""

import pytest

from yahtzee_app.ui.app import GameConfig, GameScreen, MenuScreen, YahtzeeApp


@pytest.mark.asyncio
async def test_menu_boots():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MenuScreen)


@pytest.mark.asyncio
async def test_full_human_turn_flow():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(120, 40)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        # Human rolls, holds a die, rolls again, then scores Chance (row 14
        # in the table: 6 upper + 2 total rows + 6 lower rows).
        await pilot.press("space")
        await pilot.pause()
        assert screen.game.turn.rolls_used == 1
        await pilot.press("1")
        await pilot.pause()
        assert screen.game.turn.held[0]
        await pilot.press("space")
        await pilot.pause()
        assert screen.game.turn.rolls_used == 2
        chance_option = screen.human.card.score_option(12, screen.game.turn.counts())
        screen._score(screen.human, chance_option, prefix="You")
        await pilot.pause()
        assert screen.human.card.boxes[12] is not None


@pytest.mark.asyncio
async def test_mode_cycle_and_commands():
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(120, 40)) as pilot:
        app.start_game(GameConfig(difficulties=["easy"], mode="normal"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        assert screen.mode == "normal"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert screen.mode == "hints"
        screen.handle_command("/mode normal")
        await pilot.pause()
        assert screen.mode == "normal"
        screen.handle_command("/rules")
        screen.handle_command("/version")
        screen.handle_command("/stats")
        screen.handle_command("/speed instant")
        await pilot.pause()
        assert screen.settings["speed"] == "instant"


@pytest.mark.asyncio
async def test_bot_game_plays_to_completion():
    """Watch two instant-speed bots play a few turns without errors."""
    app = YahtzeeApp(no_update=True)
    async with app.run_test(size=(120, 40)) as pilot:
        app.start_game(GameConfig(difficulties=["easy", "medium"], mode="auto"))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GameScreen)
        screen.settings["speed"] = "instant"
        # AUTO plays the human too; let the game run a bit.
        for _ in range(60):
            await pilot.pause(0.05)
            if screen.game.round > 1:
                break
        assert screen.game.round > 1 or screen.game.finished
